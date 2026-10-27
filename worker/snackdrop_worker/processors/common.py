"""Utilidades compartidas por las operaciones del catálogo."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


class ProcessingError(Exception):
    """Error esperado y legible para el usuario (se muestra tal cual en la interfaz)."""


class Cancelled(Exception):
    pass


@dataclass
class Context:
    """Lo que una operación puede hacer mientras corre: informar progreso, revisar cancelación, escribir logs."""

    index: int = 0
    total: int = 1
    on_progress: Callable[[float], None] | None = None
    on_log: Callable[[str], None] | None = None
    is_cancelled: Callable[[], bool] | None = None
    tmp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))

    def progress(self, fraction: float) -> None:
        if self.on_progress:
            self.on_progress(max(0.0, min(1.0, fraction)))

    def log(self, line: str) -> None:
        if self.on_log:
            self.on_log(line)

    def cancelled(self) -> bool:
        return bool(self.is_cancelled and self.is_cancelled())

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()


Output = tuple[Path, str]  # (archivo generado, línea de log)


def models_dir() -> Path:
    path = Path(os.getenv("SNACKDROP_MODELS_DIR") or Path.home() / ".cache" / "snackdrop" / "models")
    return path


def unique(out_dir: Path, stem: str, ext: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(stem)
    candidate = out_dir / f"{stem}{ext}"
    n = 1
    while candidate.exists():
        candidate = out_dir / f"{stem} ({n}){ext}"
        n += 1
    return candidate


def safe_stem(name: str, fallback: str = "archivo") -> str:
    name = unicodedata.normalize("NFC", name)
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"/\\|?*')
    name = name.strip().strip(".")
    return name[:180] or fallback


def clamp_int(value, lo: int, hi: int, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def clamp_float(value, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def choice(value, options, default):
    return value if value in options else default


def fmt_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # pragma: no cover


def ratio(before: int, after: int) -> str:
    if not before:
        return ""
    return f" ({after * 100 / before:.0f}% del original)"


def which(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


@lru_cache
def ffmpeg_path() -> str | None:
    path = which("ffmpeg")
    if path:
        return path
    try:  # binario estático empaquetado (útil fuera de Docker)
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def run(cmd: list[str], ctx: Context, timeout: float = 3600, cwd: Path | None = None, env: dict | None = None,
        on_stdout: Callable[[str], None] | None = None) -> str:
    """Ejecuta un programa (sin shell), respetando cancelación y tiempo máximo. Devuelve el final de stderr."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        env=env,
        text=True,
        errors="replace",
    )
    tail: deque[str] = deque(maxlen=40)

    def drain_stderr():
        for line in proc.stderr:  # type: ignore[union-attr]
            tail.append(line.rstrip())

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    def drain_stdout():
        for line in proc.stdout:  # type: ignore[union-attr]
            if on_stdout:
                on_stdout(line.rstrip())

    t2 = threading.Thread(target=drain_stdout, daemon=True)
    t2.start()

    start = time.monotonic()
    while proc.poll() is None:
        if ctx.cancelled():
            proc.kill()
            proc.wait()
            raise Cancelled()
        if time.monotonic() - start > timeout:
            proc.kill()
            proc.wait()
            raise ProcessingError(f"Tiempo agotado ({int(timeout)} s)")
        time.sleep(0.2)
    t.join(timeout=5)
    t2.join(timeout=5)
    err = "\n".join(tail)
    if proc.returncode != 0:
        raise ProcessingError(_short_error(err) or f"El programa terminó con código {proc.returncode}")
    return err


def _short_error(stderr: str) -> str:
    lines = [l for l in stderr.splitlines() if l.strip()]
    return " | ".join(lines[-3:])[-500:]


_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)?)?\s*$")


def parse_ranges(spec: str, page_count: int) -> list[list[int]]:
    """«1-3,7,10-» → [[0,1,2],[6],[9..fin]] (índices base 0). Lanza ProcessingError si no es válido."""
    if not spec or not spec.strip():
        raise ProcessingError("Indica las páginas, por ejemplo 1-3,7")
    groups: list[list[int]] = []
    for part in spec.split(","):
        m = _RANGE_RE.match(part)
        if not m:
            raise ProcessingError(f"Rango de páginas inválido: «{part.strip()}»")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else (page_count if "-" in part else start)
        if start < 1 or end < start:
            raise ProcessingError(f"Rango de páginas inválido: «{part.strip()}»")
        if start > page_count:
            raise ProcessingError(f"La página {start} no existe (el documento tiene {page_count})")
        groups.append(list(range(start - 1, min(end, page_count))))
    return groups


def pages_from_spec(spec: str | None, page_count: int) -> list[int]:
    if not spec or spec.strip().lower() in {"", "todas", "all"}:
        return list(range(page_count))
    seen: list[int] = []
    for group in parse_ranges(spec, page_count):
        for p in group:
            if p not in seen:
                seen.append(p)
    return seen
