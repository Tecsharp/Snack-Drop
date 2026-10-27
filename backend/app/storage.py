from __future__ import annotations

import re
import shutil
import unicodedata
import uuid
from pathlib import Path

from fastapi import UploadFile

from .config import Settings

_CHUNK = 1024 * 1024
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class UploadTooLarge(Exception):
    pass


def safe_filename(name: str | None, fallback: str = "archivo") -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFC", name)
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    name = name.strip().strip(".")
    if not name:
        name = fallback
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 190] + dot + ext[:9]) if dot else name[:200]
    return name


def job_dir(settings: Settings, job_id: str) -> Path:
    if not _JOB_ID_RE.match(job_id):
        raise ValueError("job id inválido")
    return settings.jobs_dir / job_id


def file_path(settings: Settings, job_id: str, kind: str, stored_name: str) -> Path:
    if kind not in {"input", "output"} or not re.match(r"^[0-9a-f]{32}(\.[a-z0-9]{1,8})?$", stored_name):
        raise ValueError("ruta inválida")
    return job_dir(settings, job_id) / ("in" if kind == "input" else "out") / stored_name


def new_stored_name(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if not re.match(r"^\.[a-z0-9]{1,8}$", ext):
        ext = ""
    return uuid.uuid4().hex + ext


async def save_upload(upload: UploadFile, dest: Path, limit_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with dest.open("wb") as fh:
            while chunk := await upload.read(_CHUNK):
                written += len(chunk)
                if written > limit_bytes:
                    raise UploadTooLarge()
                fh.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return written


def remove_job_dir(settings: Settings, job_id: str) -> None:
    shutil.rmtree(job_dir(settings, job_id), ignore_errors=True)


def remove_outputs_dir(settings: Settings, job_id: str) -> None:
    shutil.rmtree(job_dir(settings, job_id) / "out", ignore_errors=True)
