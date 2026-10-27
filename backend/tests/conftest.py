from __future__ import annotations

import os
import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("SNACKDROP_SECRET_KEY", "test-secret-key-" + "x" * 40)
os.environ.setdefault("SNACKDROP_DATA_DIR", "/tmp/snackdrop-test-unused")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "worker"))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN_PASSWORD = "Admin-Password-123"
LOCAL_TOKEN = "sdn_local-test-token-abcdefghijklmnopqrstuvwxyz"
CSRF = {"X-Requested-With": "snackdrop"}


def make_settings(tmp_path: Path):
    base = get_settings()
    return replace(
        base,
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        admin_password=ADMIN_PASSWORD,
        local_node_token=LOCAL_TOKEN,
        local_node_name="LilNasX",
        deepseek_api_key="",
    )


@pytest.fixture
def app(tmp_path):
    return create_app(make_settings(tmp_path))


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://testserver", headers=CSRF) as c:
        yield c


def login(c: TestClient, username: str = "admin", password: str = ADMIN_PASSWORD):
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(client):
    login(client)
    return client


def new_client(app) -> TestClient:
    return TestClient(app, base_url="http://testserver", headers=CSRF)


def create_user(admin_client: TestClient, app, username: str, role: str = "user") -> TestClient:
    """Crea un usuario, cambia su contraseña temporal y devuelve un cliente autenticado."""
    r = admin_client.post("/api/users", json={"username": username, "role": role})
    assert r.status_code == 201, r.text
    temp = r.json()["temporary_password"]
    c = new_client(app)
    c.__enter__()
    login(c, username, temp)
    r = c.post("/api/auth/change-password", json={"current_password": temp, "new_password": "New-Password-456"})
    assert r.status_code == 200, r.text
    return c


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    """Servidor uvicorn real en un hilo, para probar el agente de verdad."""
    import uvicorn

    app = create_app(make_settings(tmp_path))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="auto"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn no arrancó")
        time.sleep(0.05)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
