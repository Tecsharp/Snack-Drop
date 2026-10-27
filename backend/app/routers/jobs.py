from __future__ import annotations

import json
import os
import tempfile
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .. import assistant
from ..catalog import CatalogError, accepts_file, public_catalog, validate_job
from ..deps import can_use_node, get_current_user, get_db
from ..models import ACTIVE_STATUSES, TERMINAL_STATUSES, Job, JobFile, JobLog, Node, User, iso, utcnow
from ..storage import (
    UploadTooLarge,
    file_path,
    new_stored_name,
    remove_inputs_dir,
    remove_job_dir,
    safe_filename,
    save_upload,
)

router = APIRouter(prefix="/api", tags=["jobs"])


class AssistantIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=assistant.MAX_INSTRUCTION)


def _visible_query(user: User):
    q = select(Job)
    if not user.is_admin:
        owned_nodes = select(Node.id).where(Node.owner_id == user.id)
        q = q.where(or_(Job.owner_id == user.id, Job.assigned_node_id.in_(owned_nodes)))
    return q


def _get_job(db: Session, user: User, job_id: str, *, owner_only: bool = False) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Trabajo no encontrado")
    if user.is_admin or job.owner_id == user.id:
        return job
    if not owner_only and job.assigned_node_id:
        node = db.get(Node, job.assigned_node_id)
        if node is not None and node.owner_id == user.id:
            return job
    raise HTTPException(404, "Trabajo no encontrado")


@router.get("/catalog")
def catalog(_: User = Depends(get_current_user)):
    return public_catalog()


@router.post("/assistant/plan")
async def assistant_plan(
    body: AssistantIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    nodes = {n.id: n.name for n in db.scalars(select(Node)).all() if can_use_node(db, user, n)}
    try:
        return await assistant.plan(body.instruction, request.app.state.settings, nodes)
    except CatalogError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/jobs")
def list_jobs(
    request: Request, limit: int = 100, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    limit = max(1, min(limit, 500))
    jobs = db.scalars(_visible_query(user).order_by(Job.created_at.desc()).limit(limit)).all()
    hub = request.app.state.hub
    return [hub.job_out(db, j) for j in jobs]


@router.post("/jobs", status_code=201)
async def create_job(
    request: Request,
    operation: str = Form(...),
    params: str = Form("{}"),
    node_id: str = Form(""),
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    try:
        parsed = json.loads(params or "{}")
        if not isinstance(parsed, dict):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(400, "params debe ser un objeto JSON") from exc
    try:
        clean_params = validate_job(operation, parsed)
    except CatalogError as exc:
        raise HTTPException(400, str(exc)) from exc

    target: Node | None = None
    if node_id not in ("", "auto"):
        try:
            target = db.get(Node, int(node_id))
        except ValueError:
            target = None
        if target is None or not can_use_node(db, user, target):
            raise HTTPException(404, "Nodo no encontrado o sin autorización")

    if not files:
        raise HTTPException(400, "Agrega al menos un archivo")
    if len(files) > settings.max_files_per_job:
        raise HTTPException(400, f"Máximo {settings.max_files_per_job} archivos por trabajo")
    names = [safe_filename(f.filename) for f in files]
    rejected = [n for n in names if not accepts_file(operation, n)]
    if rejected:
        raise HTTPException(400, f"Archivos no compatibles con la operación: {', '.join(rejected[:5])}")

    job = Job(owner_id=user.id, operation=operation, params=clean_params, target_node_id=target.id if target else None)
    job.title = names[0] if len(names) == 1 else f"{names[0]} y {len(names) - 1} más"
    db.add(job)
    db.flush()

    remaining = settings.max_upload_mb * 1024 * 1024
    try:
        for upload, name in zip(files, names):
            stored = new_stored_name(name)
            size = await save_upload(upload, file_path(settings, job.id, "input", stored), remaining)
            remaining -= size
            job.files.append(JobFile(kind="input", filename=name, stored_name=stored, size=size))
    except UploadTooLarge as exc:
        db.rollback()
        remove_job_dir(settings, job.id)
        raise HTTPException(413, f"El trabajo supera el límite de {settings.max_upload_mb} MB") from exc
    except BaseException:
        db.rollback()
        remove_job_dir(settings, job.id)
        raise

    job.message = "En cola"
    db.add(JobLog(job_id=job.id, line=f"Trabajo creado por {user.username}: {operation} con {len(names)} archivo(s)"))
    db.commit()
    hub = request.app.state.hub
    await hub.notify_job(db, job)
    await hub.dispatch()
    db.refresh(job)
    return hub.job_out(db, job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return request.app.state.hub.job_out(db, _get_job(db, user, job_id))


@router.get("/jobs/{job_id}/logs")
def get_logs(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _get_job(db, user, job_id)
    logs = db.scalars(select(JobLog).where(JobLog.job_id == job.id).order_by(JobLog.id).limit(5000)).all()
    return [{"ts": iso(l.ts), "line": l.line} for l in logs]


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = _get_job(db, user, job_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(409, "El trabajo ya terminó")
    hub = request.app.state.hub
    was_active = job.status in ACTIVE_STATUSES
    node_id = job.assigned_node_id
    job.status = "cancelled"
    job.message = f"Cancelado por {user.username}"
    job.finished_at = utcnow()
    db.add(JobLog(job_id=job.id, line=job.message))
    db.commit()
    if was_active and node_id is not None:
        conn = hub.nodes.get(node_id)
        if conn is not None and conn.job_id == job.id:
            # El nodo queda ocupado hasta que confirme la cancelación (POST /complete).
            await conn.send({"type": "job.cancel", "job_id": job.id})
    elif request.app.state.settings.delete_inputs_on_finish:
        # Si estaba en curso, se borran cuando el nodo confirma la cancelación.
        remove_inputs_dir(request.app.state.settings, job.id)
    await hub.notify_job(db, job)
    return hub.job_out(db, job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = _get_job(db, user, job_id, owner_only=True)
    if job.status not in TERMINAL_STATUSES:
        raise HTTPException(409, "Cancela el trabajo antes de eliminarlo")
    hub = request.app.state.hub
    await hub.notify_job_removed(db, job)
    db.delete(job)
    db.commit()
    remove_job_dir(request.app.state.settings, job_id)


def _output_or_404(db: Session, job: Job, file_id: int) -> JobFile:
    jf = db.get(JobFile, file_id)
    if jf is None or jf.job_id != job.id or jf.kind != "output":
        raise HTTPException(404, "Archivo no encontrado")
    return jf


@router.get("/jobs/{job_id}/outputs/{file_id}")
def download_output(
    job_id: str, file_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = _get_job(db, user, job_id, owner_only=True)
    jf = _output_or_404(db, job, file_id)
    path = file_path(request.app.state.settings, job.id, "output", jf.stored_name)
    if not path.exists():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(path, filename=jf.filename)


@router.get("/jobs/{job_id}/download")
def download_all(job_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _get_job(db, user, job_id, owner_only=True)
    outputs = [f for f in job.files if f.kind == "output"]
    if job.status != "done" or not outputs:
        raise HTTPException(404, "El trabajo no tiene resultados")
    settings = request.app.state.settings
    if len(outputs) == 1:
        jf = outputs[0]
        return FileResponse(file_path(settings, job.id, "output", jf.stored_name), filename=jf.filename)
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=settings.data_dir)
    os.close(fd)
    used: set[str] = set()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
        for jf in outputs:
            name, n = jf.filename, 1
            while name in used:
                stem, dot, ext = jf.filename.rpartition(".")
                name = f"{stem} ({n}).{ext}" if dot else f"{jf.filename} ({n})"
                n += 1
            used.add(name)
            zf.write(file_path(settings, job.id, "output", jf.stored_name), arcname=name)
    return FileResponse(
        tmp,
        filename=f"snackdrop-{job.id[:8]}.zip",
        media_type="application/zip",
        background=BackgroundTask(os.unlink, tmp),
    )
