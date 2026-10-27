"""Estado en tiempo real: conexiones WebSocket de navegadores y nodos, cola y despacho."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from dataclasses import dataclass, field

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import OPERATIONS, redact
from .config import Settings
from .deps import can_manage_node, can_use_node
from .storage import remove_outputs_dir
from .models import ACTIVE_STATUSES, TERMINAL_STATUSES, Job, Node, User, iso, utcnow

log = logging.getLogger("snackdrop.realtime")


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, msg: dict) -> bool:
        try:
            async with self.lock:
                await self.ws.send_json(msg)
            return True
        except Exception:  # noqa: BLE001 - conexión cerrada o rota
            return False


@dataclass(eq=False)
class UIConn(Conn):
    user_id: int = 0


@dataclass(eq=False)
class NodeConn(Conn):
    node_id: int = 0
    capabilities: list[str] = field(default_factory=list)
    job_id: str | None = None
    hw_encoders: list[str] = field(default_factory=list)
    gpu: bool = False


class Hub:
    def __init__(self, session_factory, settings: Settings):
        self.SessionLocal = session_factory
        self.settings = settings
        self.ui: set[UIConn] = set()
        self.nodes: dict[int, NodeConn] = {}
        self.dispatch_lock = asyncio.Lock()

    # --- Serialización -------------------------------------------------------

    def node_out(self, db: Session, node: Node, viewer: User | None = None) -> dict:
        conn = self.nodes.get(node.id)
        online = conn is not None
        current_job = None
        if conn and conn.job_id:
            job = db.get(Job, conn.job_id)
            if job is not None:
                current_job = {"id": job.id, "status": job.status, "title": job.title, "progress": job.progress}
        if not online:
            state = "offline"
        elif current_job:
            state = current_job["status"]
        elif node.is_paused:
            state = "paused"
        else:
            state = "online"
        manage = viewer is not None and can_manage_node(viewer, node)
        data = {
            "id": node.id,
            "name": node.name,
            "kind": node.kind,
            "owner_id": node.owner_id,
            "owner": node.owner.username if node.owner else None,
            "shared_with_all": node.shared_with_all,
            "is_paused": node.is_paused,
            "hostname": node.hostname,
            "os": node.os,
            "arch": node.arch,
            "accelerator": node.accelerator,
            "capabilities": list(conn.capabilities) if conn else list(node.capabilities or []),
            "hw_encoders": list(conn.hw_encoders) if conn else [],
            "gpu": bool(conn and conn.gpu),
            "jobs_done": node.jobs_done,
            "jobs_failed": node.jobs_failed,
            "last_seen": iso(node.last_seen),
            "online": online,
            "state": state,
            "current_job": current_job,
            "can_manage": manage,
        }
        if manage:
            data["grants"] = [{"user_id": g.user_id, "username": g.user.username} for g in node.grants]
        return data

    def job_out(self, db: Session, job: Job) -> dict:
        names: dict[int, str] = {}
        for nid in {job.assigned_node_id, job.target_node_id} - {None}:
            n = db.get(Node, nid)
            if n is not None:
                names[nid] = n.name
        inputs = [f for f in job.files if f.kind == "input"]
        outputs = [f for f in job.files if f.kind == "output"]
        return {
            "id": job.id,
            "title": job.title,
            "operation": job.operation,
            "params": redact(job.operation, job.params),
            "status": job.status,
            "progress": round(job.progress or 0.0, 1),
            "message": job.message,
            "error": job.error,
            "owner_id": job.owner_id,
            "owner": job.owner.username if job.owner else None,
            "target_node_id": job.target_node_id,
            "target_node_name": names.get(job.target_node_id),
            "assigned_node_id": job.assigned_node_id,
            "assigned_node_name": names.get(job.assigned_node_id),
            "created_at": iso(job.created_at),
            "started_at": iso(job.started_at),
            "finished_at": iso(job.finished_at),
            "inputs": [{"id": f.id, "filename": f.filename, "size": f.size} for f in inputs],
            "outputs": [{"id": f.id, "filename": f.filename, "size": f.size} for f in outputs],
            "failures": [{"filename": f.filename, "error": f.error} for f in job.failures],
            "inputs_deleted": job.status in TERMINAL_STATUSES and self.settings.delete_inputs_on_finish,
            "expires_at": iso(job.finished_at + timedelta(days=self.settings.retention_days))
            if job.finished_at and self.settings.retention_days
            else None,
            "input_size": sum(f.size for f in inputs),
            "output_size": sum(f.size for f in outputs),
        }

    # --- Difusión ------------------------------------------------------------

    async def _send_many(self, conns: list[Conn], msg: dict) -> None:
        if not conns:
            return
        results = await asyncio.gather(*(c.send(msg) for c in conns))
        for conn, ok in zip(conns, results):
            if not ok and isinstance(conn, UIConn):
                self.ui.discard(conn)

    def _job_viewers(self, db: Session, job: Job) -> set[int]:
        viewers = {job.owner_id}
        viewers.update(db.scalars(select(User.id).where(User.role == "admin")).all())
        if job.assigned_node_id:
            node = db.get(Node, job.assigned_node_id)
            if node is not None:
                viewers.add(node.owner_id)
        return viewers

    async def notify_job(self, db: Session, job: Job) -> None:
        viewers = self._job_viewers(db, job)
        payload = {"type": "job.update", "job": self.job_out(db, job)}
        await self._send_many([c for c in self.ui if c.user_id in viewers], payload)

    async def notify_job_removed(self, db: Session, job: Job) -> None:
        viewers = self._job_viewers(db, job)
        await self._send_many([c for c in self.ui if c.user_id in viewers], {"type": "job.removed", "id": job.id})

    async def notify_job_log(self, db: Session, job: Job, line: str, ts: str) -> None:
        viewers = self._job_viewers(db, job)
        msg = {"type": "job.log", "job_id": job.id, "line": line, "ts": ts}
        await self._send_many([c for c in self.ui if c.user_id in viewers], msg)

    async def notify_node(self, db: Session, node: Node) -> None:
        tasks = []
        for conn in list(self.ui):
            user = db.get(User, conn.user_id)
            if user is not None and can_use_node(db, user, node):
                tasks.append(conn.send({"type": "node.update", "node": self.node_out(db, node, user)}))
        if tasks:
            await asyncio.gather(*tasks)

    async def notify_node_removed(self, node_id: int) -> None:
        await self._send_many(list(self.ui), {"type": "node.removed", "id": node_id})

    # --- Cola y despacho -----------------------------------------------------

    @staticmethod
    def worker_payload(job: Job) -> dict:
        return {
            "id": job.id,
            "operation": job.operation,
            "params": job.params,
            "inputs": [{"id": f.id, "filename": f.filename, "size": f.size} for f in job.files if f.kind == "input"],
        }

    async def dispatch(self) -> None:
        async with self.dispatch_lock:
            db = self.SessionLocal()
            try:
                idle: list[tuple[NodeConn, Node]] = []
                for node_id, conn in list(self.nodes.items()):
                    if conn.job_id is not None:
                        continue
                    node = db.get(Node, node_id)
                    if node is not None and not node.is_paused:
                        idle.append((conn, node))
                if not idle:
                    return
                queued = db.scalars(select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(500)).all()
                for job in queued:
                    if not idle:
                        break
                    eligible = [
                        (c, n) for c, n in idle
                        if job.operation in c.capabilities
                        and job.target_node_id in (None, n.id)
                        and can_use_node(db, job.owner, n)
                    ]
                    if not eligible:
                        continue
                    op = OPERATIONS.get(job.operation)
                    # Video/IA prefieren nodos con GPU; el resto deja esos nodos libres si hay alternativa.
                    eligible.sort(key=lambda cn: (not cn[0].gpu) if op and op.gpu else cn[0].gpu)
                    conn, node = eligible[0]
                    idle.remove((conn, node))
                    job.assigned_node_id = node.id
                    job.status = "assigned"
                    job.progress = 0.0
                    job.message = f"Asignado a {node.name}"
                    job.started_at = utcnow()
                    db.commit()
                    conn.job_id = job.id
                    if not await conn.send({"type": "job.assign", "job": self.worker_payload(job)}):
                        conn.job_id = None
                        self.requeue(db, job, "El nodo no respondió")
                    await self.notify_job(db, job)
                    await self.notify_node(db, node)
            finally:
                db.close()

    def requeue(self, db: Session, job: Job, reason: str) -> None:
        if job.status in ACTIVE_STATUSES:
            job.status = "queued"
            job.assigned_node_id = None
            job.progress = 0.0
            job.message = reason
            job.started_at = None
            for f in [f for f in job.files if f.kind == "output"]:
                job.files.remove(f)
            job.failures.clear()
            db.commit()
            remove_outputs_dir(self.settings, job.id)
