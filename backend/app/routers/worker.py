"""API para los agentes ejecutores (nodos). Autenticación con token Bearer del nodo."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..catalog import OPERATIONS, scrub
from ..deps import get_db, get_node_from_bearer, node_from_token
from ..models import ACTIVE_STATUSES, TERMINAL_STATUSES, Job, JobFailure, JobFile, JobLog, Node, iso, utcnow
from ..realtime import NodeConn
from ..storage import UploadTooLarge, file_path, new_stored_name, remove_inputs_dir, safe_filename, save_upload

log = logging.getLogger("snackdrop.worker")
router = APIRouter(tags=["worker"])

MAX_LOG_LINES = 5000
PROGRESS_STATUSES = {"downloading", "processing", "uploading"}


class FailureIn(BaseModel):
    filename: str = Field(max_length=255)
    error: str = Field(max_length=2000)


class CompleteIn(BaseModel):
    ok: bool
    error: str | None = Field(None, max_length=4000)
    summary: str | None = Field(None, max_length=255)
    failures: list[FailureIn] = Field(default_factory=list, max_length=5000)


def _active_job_for_node(db: Session, node: Node, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.assigned_node_id != node.id:
        raise HTTPException(404, "Trabajo no asignado a este nodo")
    if job.status not in ACTIVE_STATUSES:
        raise HTTPException(409, f"El trabajo está {job.status}")
    return job


@router.get("/api/worker/jobs/{job_id}/inputs/{file_id}")
def download_input(
    job_id: str, file_id: int, request: Request, node: Node = Depends(get_node_from_bearer), db: Session = Depends(get_db)
):
    job = _active_job_for_node(db, node, job_id)
    jf = db.get(JobFile, file_id)
    if jf is None or jf.job_id != job.id or jf.kind != "input":
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(file_path(request.app.state.settings, job.id, "input", jf.stored_name), filename=jf.filename)


@router.post("/api/worker/jobs/{job_id}/outputs", status_code=201)
async def upload_output(
    job_id: str,
    request: Request,
    file: UploadFile = File(...),
    node: Node = Depends(get_node_from_bearer),
    db: Session = Depends(get_db),
):
    job = _active_job_for_node(db, node, job_id)
    settings = request.app.state.settings
    name = safe_filename(file.filename, "resultado")
    stored = new_stored_name(name)
    try:
        size = await save_upload(file, file_path(settings, job.id, "output", stored), settings.max_upload_mb * 1024 * 1024)
    except UploadTooLarge as exc:
        raise HTTPException(413, "Resultado demasiado grande") from exc
    jf = JobFile(job_id=job.id, kind="output", filename=name, stored_name=stored, size=size)
    db.add(jf)
    db.commit()
    return {"id": jf.id, "filename": jf.filename, "size": jf.size}


@router.post("/api/worker/jobs/{job_id}/complete")
async def complete_job(
    job_id: str,
    body: CompleteIn,
    request: Request,
    node: Node = Depends(get_node_from_bearer),
    db: Session = Depends(get_db),
):
    hub = request.app.state.hub
    job = db.get(Job, job_id)
    if job is None or job.assigned_node_id != node.id:
        raise HTTPException(404, "Trabajo no asignado a este nodo")
    conn = hub.nodes.get(node.id)
    if conn is not None and conn.job_id == job.id:
        conn.job_id = None
    if job.status in ACTIVE_STATUSES:
        job.finished_at = utcnow()
        if body.ok:
            job.status = "done"
            job.progress = 100.0
            job.message = body.summary or "Completado"
            node.jobs_done += 1
        else:
            job.status = "failed"
            job.error = body.error or "Error desconocido"
            job.message = "Falló"
            node.jobs_failed += 1
        job.params = scrub(job.operation, job.params)  # no guardar contraseñas más allá del trabajo
        for f in body.failures:
            job.failures.append(JobFailure(filename=safe_filename(f.filename), error=f.error))
        db.add(JobLog(job_id=job.id, line=f"[{node.name}] {job.message if body.ok else 'ERROR: ' + job.error}"))
        db.commit()
        await hub.notify_job(db, job)
    if job.status in TERMINAL_STATUSES and request.app.state.settings.delete_inputs_on_finish:
        remove_inputs_dir(request.app.state.settings, job.id)
    await hub.notify_node(db, node)
    await hub.dispatch()
    return {"status": job.status}


async def _handle_node_message(hub, db: Session, conn: NodeConn, node: Node, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "ping":
        await conn.send({"type": "pong"})
        return
    job_id = msg.get("job_id")
    if not job_id or job_id != conn.job_id:
        return
    job = db.get(Job, job_id)
    if job is None or job.status not in ACTIVE_STATUSES:
        return
    if kind == "job.progress":
        status_ = msg.get("status")
        if status_ in PROGRESS_STATUSES:
            job.status = status_
        try:
            job.progress = max(0.0, min(100.0, float(msg.get("progress", job.progress))))
        except (TypeError, ValueError):
            pass
        job.message = str(msg.get("message") or "")[:255]
        db.commit()
        await hub.notify_job(db, job)
        await hub.notify_node(db, node)
    elif kind == "job.log":
        line = str(msg.get("line") or "")[:2000]
        count = db.scalar(select(func.count()).select_from(JobLog).where(JobLog.job_id == job.id))
        if line and count < MAX_LOG_LINES:
            entry = JobLog(job_id=job.id, line=f"[{node.name}] {line}")
            db.add(entry)
            db.commit()
            await hub.notify_job_log(db, job, entry.line, iso(entry.ts))


@router.websocket("/ws/node")
async def node_socket(ws: WebSocket):
    app = ws.app
    hub = app.state.hub
    auth = ws.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    db: Session = app.state.SessionLocal()
    conn: NodeConn | None = None
    try:
        node = node_from_token(db, token)
        if node is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=15)
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
            await ws.close(code=4400)
            return
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await ws.close(code=4400)
            return
        info = hello.get("info") if isinstance(hello.get("info"), dict) else {}
        caps = [c for c in hello.get("capabilities", []) if isinstance(c, str) and c in OPERATIONS]
        node.hostname = str(info.get("hostname") or "")[:128] or None
        node.os = str(info.get("os") or "")[:64] or None
        node.arch = str(info.get("arch") or "")[:64] or None
        node.accelerator = str(info.get("accelerator") or "")[:64] or None
        node.capabilities = caps
        node.last_seen = utcnow()
        db.commit()

        previous = hub.nodes.get(node.id)
        if previous is not None:
            try:
                await previous.ws.close(code=4409)
            except Exception:  # noqa: BLE001
                pass
        hw = [e for e in info.get("hw_encoders", []) if isinstance(e, str)][:10] if isinstance(info.get("hw_encoders"), list) else []
        conn = NodeConn(ws=ws, node_id=node.id, capabilities=caps, hw_encoders=hw,
                        gpu=bool(hw) or str(info.get("accelerator") or "") == "Nvidia")
        hub.nodes[node.id] = conn
        # Un trabajo que quedó a medias en este nodo vuelve a la cola.
        for job in db.scalars(select(Job).where(Job.assigned_node_id == node.id, Job.status.in_(ACTIVE_STATUSES))):
            hub.requeue(db, job, "Reintentando tras reconexión del nodo")
            await hub.notify_job(db, job)
        await conn.send({"type": "welcome", "node": {"id": node.id, "name": node.name}})
        log.info("Nodo conectado: %s (%s)", node.name, node.id)
        await hub.notify_node(db, node)
        await hub.dispatch()

        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            db.expire_all()  # ver cambios hechos por otras peticiones (cancelaciones, pausas)
            node.last_seen = utcnow()
            await _handle_node_message(hub, db, conn, node, msg)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            if conn is not None and hub.nodes.get(conn.node_id) is conn:
                del hub.nodes[conn.node_id]
                db.rollback()
                if conn.job_id:
                    job = db.get(Job, conn.job_id)
                    if job is not None:
                        hub.requeue(db, job, "El nodo se desconectó; trabajo devuelto a la cola")
                        await hub.notify_job(db, job)
                node = db.get(Node, conn.node_id)
                if node is not None:
                    node.last_seen = utcnow()
                    db.commit()
                    await hub.notify_node(db, node)
                await hub.dispatch()
        finally:
            db.close()
