from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .config import Settings, get_settings
from .db import Base, make_engine, make_sessionmaker
from .models import ACTIVE_STATUSES, TERMINAL_STATUSES, Job, Node, User, utcnow
from .realtime import Hub
from .routers import auth, jobs, nodes, ui_ws, users, worker
from .storage import remove_job_dir
from .security import LoginLimiter, generate_password, hash_node_token, hash_password

log = logging.getLogger("snackdrop")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "snackdrop"


def bootstrap(settings: Settings, SessionLocal) -> None:
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.role == "admin"))
        if db.scalar(select(User).limit(1)) is None:
            password = settings.admin_password
            if not password:
                password = generate_password()
                log.warning("Usuario %s creado con contraseña aleatoria: %s", settings.admin_username, password)
            admin = User(username=settings.admin_username, role="admin", password_hash=hash_password(password))
            db.add(admin)
            db.commit()
            log.info("Administrador inicial '%s' creado", settings.admin_username)

        if settings.local_node_token and admin is not None:
            token_hash = hash_node_token(settings.local_node_token)
            if db.scalar(select(Node).where(Node.token_hash == token_hash)) is None:
                master = db.scalar(select(Node).where(Node.kind == "master"))
                if master is None:
                    master = Node(
                        name=settings.local_node_name,
                        owner_id=admin.id,
                        kind="master",
                        shared_with_all=True,
                        capabilities=[],
                    )
                    db.add(master)
                master.token_hash = token_hash
                db.commit()

        # Tras un reinicio ningún nodo está conectado: lo que estaba en curso vuelve a la cola.
        for job in db.scalars(select(Job).where(Job.status.in_(ACTIVE_STATUSES))):
            job.status = "queued"
            job.assigned_node_id = None
            job.progress = 0.0
            job.message = "Reencolado tras reinicio del servidor"
        db.commit()
    finally:
        db.close()


PURGE_INTERVAL_SECONDS = 3600


async def purge_expired(app: FastAPI) -> int:
    """Elimina trabajos terminados (y sus archivos) más antiguos que la retención configurada."""
    settings: Settings = app.state.settings
    if settings.retention_days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=settings.retention_days)
    hub = app.state.hub
    db = app.state.SessionLocal()
    removed = 0
    try:
        old = db.scalars(
            select(Job).where(Job.status.in_(TERMINAL_STATUSES), Job.finished_at.is_not(None), Job.finished_at < cutoff)
        ).all()
        for job in old:
            await hub.notify_job_removed(db, job)
            job_id = job.id
            db.delete(job)
            db.commit()
            remove_job_dir(settings, job_id)
            removed += 1
    finally:
        db.close()
    if removed:
        log.info("Limpieza: %d trabajo(s) con más de %d días eliminados", removed, settings.retention_days)
    return removed


async def _purge_loop(app: FastAPI) -> None:
    while True:
        try:
            await purge_expired(app)
        except Exception:  # noqa: BLE001 - la limpieza nunca debe tumbar el servidor
            log.exception("Error en la limpieza periódica")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    SessionLocal = make_sessionmaker(engine)
    Base.metadata.create_all(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bootstrap(settings, SessionLocal)
        purger = asyncio.create_task(_purge_loop(app))
        yield
        purger.cancel()
        with suppress(asyncio.CancelledError):
            await purger
        engine.dispose()

    app = FastAPI(title="Snack-Drop", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.SessionLocal = SessionLocal
    app.state.hub = Hub(SessionLocal, settings)
    app.state.login_limiter = LoginLimiter()

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        path = request.url.path
        if (
            request.method in UNSAFE_METHODS
            and path.startswith("/api/")
            and not path.startswith("/api/worker/")
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            return JSONResponse({"detail": "Falta cabecera anti-CSRF"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.get("/api/health")
    def health():
        return {"ok": True}

    for module in (auth, users, nodes, jobs, worker, ui_ws):
        app.include_router(module.router)
    return app
