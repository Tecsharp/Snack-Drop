"""Agente ejecutor de Snack-Drop.

Se conecta al servidor por WebSocket, anuncia sus capacidades, recibe trabajos,
descarga las entradas por HTTP, procesa localmente y sube los resultados.
No abre puertos ni permite acceso remoto al equipo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from . import __version__
from .processors import PROCESSORS, ProcessingError, process

log = logging.getLogger("snackdrop.worker")


class JobCancelled(Exception):
    pass


@dataclass
class WorkerConfig:
    server: str
    token: str
    work_dir: Path
    allowed_operations: list[str]
    hostname: str
    verify_tls: bool = True

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        server = os.getenv("SNACKDROP_SERVER", "").rstrip("/")
        token = os.getenv("SNACKDROP_TOKEN", "")
        if not server or not token:
            raise SystemExit("Define SNACKDROP_SERVER y SNACKDROP_TOKEN (ver setup-worker.sh).")
        allowed_env = os.getenv("SNACKDROP_ALLOWED_OPERATIONS", "").strip()
        allowed = [op.strip() for op in allowed_env.split(",") if op.strip()] if allowed_env else list(PROCESSORS)
        return cls(
            server=server,
            token=token,
            work_dir=Path(os.getenv("SNACKDROP_WORK_DIR", tempfile.gettempdir())) / "snackdrop-worker",
            allowed_operations=[op for op in allowed if op in PROCESSORS],
            hostname=os.getenv("SNACKDROP_NODE_HOSTNAME") or socket.gethostname(),
            verify_tls=os.getenv("SNACKDROP_VERIFY_TLS", "true").lower() not in {"0", "false", "no"},
        )

    @property
    def ws_url(self) -> str:
        if self.server.startswith("https://"):
            return "wss://" + self.server[len("https://") :] + "/ws/node"
        if self.server.startswith("http://"):
            return "ws://" + self.server[len("http://") :] + "/ws/node"
        raise SystemExit("SNACKDROP_SERVER debe empezar con http:// o https://")


def system_info(hostname: str) -> dict:
    system = platform.system()
    os_name = {"Darwin": "macOS"}.get(system, system) or "Desconocido"
    arch = platform.machine() or "?"
    accelerator = os.getenv("SNACKDROP_ACCELERATOR") or ""
    if not accelerator:
        if shutil.which("nvidia-smi"):
            accelerator = "Nvidia"
        elif system == "Darwin" and arch in {"arm64", "aarch64"}:
            accelerator = "Apple"
        else:
            accelerator = _cpu_vendor() or "CPU"
    return {"hostname": hostname, "os": os_name, "arch": arch, "accelerator": accelerator, "version": __version__}


def _cpu_vendor() -> str | None:
    try:
        text = Path("/proc/cpuinfo").read_text(errors="ignore")
    except OSError:
        text = platform.processor()
    if "GenuineIntel" in text or "Intel" in text:
        return "Intel"
    if "AuthenticAMD" in text or "AMD" in text:
        return "AMD"
    if "ARM" in text.upper() or "aarch64" in text:
        return "ARM"
    return None


@dataclass
class Agent:
    config: WorkerConfig
    _ws: object | None = None
    _current: asyncio.Task | None = None
    _current_id: str | None = None
    _cancel: asyncio.Event = field(default_factory=asyncio.Event)
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    # --- Conexión ------------------------------------------------------------

    async def run_forever(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                await self.session()
                delay = 1.0
            except InvalidStatus as exc:
                log.error("El servidor rechazó la conexión (%s). ¿Token correcto?", exc.response.status_code)
                delay = 30.0
            except (OSError, ConnectionClosed) as exc:
                log.warning("Conexión perdida: %s", exc)
            if self._stop.is_set():
                break
            log.info("Reintentando en %.0f s", delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 60.0)

    def stop(self) -> None:
        self._stop.set()

    async def session(self) -> None:
        headers = {"Authorization": f"Bearer {self.config.token}"}
        ssl_ctx = None
        if self.config.ws_url.startswith("wss://") and not self.config.verify_tls:
            import ssl

            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        kwargs = {"ssl": ssl_ctx} if ssl_ctx else {}
        async with connect(
            self.config.ws_url, additional_headers=headers, ping_interval=20, max_size=2**20, **kwargs
        ) as ws:
            self._ws = ws
            await ws.send(_json({
                "type": "hello",
                "info": system_info(self.config.hostname),
                "capabilities": self.config.allowed_operations,
            }))
            log.info("Conectado a %s con capacidades %s", self.config.server, self.config.allowed_operations)
            try:
                async for raw in ws:
                    await self._on_message(_loads(raw))
                    if self._stop.is_set():
                        break
            finally:
                self._ws = None
                if self._current and not self._current.done():
                    # El servidor reencola el trabajo al perder la conexión.
                    self._cancel.set()
                    self._current.cancel()

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "welcome":
            log.info("Registrado como nodo '%s'", msg.get("node", {}).get("name"))
        elif kind == "job.assign":
            job = msg.get("job") or {}
            if self._current and not self._current.done():
                log.warning("Trabajo recibido mientras otro está en curso; se ignora %s", job.get("id"))
                return
            self._cancel = asyncio.Event()
            self._current_id = job.get("id")
            self._current = asyncio.create_task(self.run_job(job))
        elif kind == "job.cancel":
            if msg.get("job_id") == self._current_id:
                log.info("Cancelación solicitada para %s", self._current_id)
                self._cancel.set()

    async def _send(self, msg: dict) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(_json(msg))
            except ConnectionClosed:
                pass

    async def progress(self, job_id: str, status: str, progress: float, message: str) -> None:
        await self._send({"type": "job.progress", "job_id": job_id, "status": status, "progress": progress, "message": message})

    async def log_line(self, job_id: str, line: str) -> None:
        log.info("[%s] %s", job_id[:8], line)
        await self._send({"type": "job.log", "job_id": job_id, "line": line})

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    # --- Ejecución -----------------------------------------------------------

    async def run_job(self, job: dict) -> None:
        job_id = str(job.get("id", ""))
        operation = job.get("operation")
        params = job.get("params") or {}
        inputs = job.get("inputs") or []
        headers = {"Authorization": f"Bearer {self.config.token}"}
        work = self.config.work_dir / job_id
        in_dir, out_dir = work / "in", work / "out"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = f"{self.config.server}/api/worker/jobs/{job_id}"
        async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60, read=300), verify=self.config.verify_tls) as client:
            try:
                if operation not in self.config.allowed_operations:
                    raise ProcessingError(f"Este nodo no acepta la operación {operation}")
                total = max(1, len(inputs))
                total_bytes = sum(int(f.get("size") or 0) for f in inputs) or 1
                done_bytes = 0
                local: list[tuple[Path, str]] = []
                await self.log_line(job_id, f"Descargando {len(inputs)} archivo(s)")
                for i, f in enumerate(inputs):
                    self._check_cancel()
                    dest = in_dir / f"{i:05d}"
                    async with client.stream("GET", f"{base}/inputs/{int(f['id'])}") as resp:
                        resp.raise_for_status()
                        with dest.open("wb") as fh:
                            async for chunk in resp.aiter_bytes(1024 * 1024):
                                fh.write(chunk)
                                done_bytes += len(chunk)
                    local.append((dest, str(f.get("filename") or f"archivo-{i}")))
                    await self.progress(job_id, "downloading", 20 * min(1, done_bytes / total_bytes), f"Descargando {i + 1}/{total}")

                outputs: list[Path] = []
                for i, (src, name) in enumerate(local):
                    self._check_cancel()
                    await self.progress(job_id, "processing", 20 + 70 * i / total, f"Procesando {i + 1}/{total}: {name}")
                    out, info = await asyncio.to_thread(process, operation, params, src, out_dir, name)
                    outputs.append(out)
                    await self.log_line(job_id, info)
                await self.progress(job_id, "processing", 90, "Procesamiento terminado")

                for i, out in enumerate(outputs):
                    self._check_cancel()
                    with out.open("rb") as fh:
                        resp = await client.post(f"{base}/outputs", files={"file": (out.name, fh)})
                    resp.raise_for_status()
                    await self.progress(job_id, "uploading", 90 + 10 * (i + 1) / len(outputs), f"Subiendo {i + 1}/{len(outputs)}")

                before = sum(int(f.get("size") or 0) for f in inputs)
                after = sum(p.stat().st_size for p in outputs)
                summary = f"{len(outputs)} archivo(s) listos"
                if before:
                    summary += f" · {after * 100 / before:.0f}% del tamaño original"
                await client.post(f"{base}/complete", json={"ok": True, "summary": summary})
            except (JobCancelled, asyncio.CancelledError):
                await self.log_line(job_id, "Trabajo cancelado")
                await _safe_post(client, f"{base}/complete", {"ok": False, "error": "Cancelado"})
            except Exception as exc:  # noqa: BLE001 - se reporta al servidor
                message = str(exc) if isinstance(exc, ProcessingError) else f"{type(exc).__name__}: {exc}"
                log.exception("Trabajo %s falló", job_id)
                await self.log_line(job_id, f"ERROR: {message}")
                await _safe_post(client, f"{base}/complete", {"ok": False, "error": message[:4000]})
            finally:
                shutil.rmtree(work, ignore_errors=True)
                self._current_id = None


async def _safe_post(client: httpx.AsyncClient, url: str, payload: dict) -> None:
    try:
        await client.post(url, json=payload)
    except httpx.HTTPError:
        pass


def _json(msg: dict) -> str:
    import json

    return json.dumps(msg)


def _loads(raw) -> dict:
    import json

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
