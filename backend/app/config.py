"""Configuración leída desde variables de entorno (generadas por setup.sh)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    secret_key: str
    data_dir: Path
    database_url: str
    admin_username: str
    admin_password: str
    local_node_token: str
    local_node_name: str
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str
    session_ttl_minutes: int
    cookie_secure: bool
    max_upload_mb: int
    max_files_per_job: int
    retention_days: int = 7
    delete_inputs_on_finish: bool = True

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


@lru_cache
def get_settings() -> Settings:
    secret = os.getenv("SNACKDROP_SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError(
            "SNACKDROP_SECRET_KEY debe tener al menos 32 caracteres. Ejecuta ./setup.sh para generarla."
        )
    data_dir = Path(os.getenv("SNACKDROP_DATA_DIR", "/data"))
    return Settings(
        secret_key=secret,
        data_dir=data_dir,
        database_url=os.getenv("SNACKDROP_DATABASE_URL", f"sqlite:///{data_dir / 'snackdrop.db'}"),
        admin_username=os.getenv("SNACKDROP_ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("SNACKDROP_ADMIN_PASSWORD", ""),
        local_node_token=os.getenv("SNACKDROP_LOCAL_NODE_TOKEN", ""),
        local_node_name=os.getenv("SNACKDROP_LOCAL_NODE_NAME", "master"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        session_ttl_minutes=_int(os.getenv("SNACKDROP_SESSION_TTL_MINUTES"), 720),
        cookie_secure=_bool(os.getenv("SNACKDROP_COOKIE_SECURE"), False),
        max_upload_mb=_int(os.getenv("SNACKDROP_MAX_UPLOAD_MB"), 2048),
        max_files_per_job=_int(os.getenv("SNACKDROP_MAX_FILES_PER_JOB"), 500),
        retention_days=max(0, _int(os.getenv("SNACKDROP_RETENTION_DAYS"), 7)),
        delete_inputs_on_finish=_bool(os.getenv("SNACKDROP_DELETE_INPUTS_ON_FINISH"), True),
    )
