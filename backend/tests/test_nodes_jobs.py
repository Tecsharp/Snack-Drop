from __future__ import annotations

import asyncio
import io
import json
import threading
import time
import zipfile

import httpx
import pytest
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from conftest import CSRF, LOCAL_TOKEN, create_user, login


def png_bytes(size=(800, 600), color=(200, 30, 120, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_master_node_bootstrapped(admin):
    nodes = admin.get("/api/nodes").json()
    assert len(nodes) == 1
    assert nodes[0]["name"] == "LilNasX" and nodes[0]["kind"] == "master"
    assert nodes[0]["state"] == "offline"


def test_node_access_and_grants(admin, app):
    owner = create_user(admin, app, "dueno")
    guest = create_user(admin, app, "invitado")
    r = owner.post("/api/nodes", json={"name": "SHRIMPDADDY"})
    assert r.status_code == 201
    node = r.json()["node"]
    assert r.json()["install"]["token"].startswith("sdn_")
    nid = node["id"]

    guest_ids = {n["id"] for n in guest.get("/api/nodes").json()}
    assert nid not in guest_ids
    assert guest.patch(f"/api/nodes/{nid}", json={"is_paused": True}).status_code == 404
    files = {"files": ("a.png", png_bytes(), "image/png")}
    r = guest.post("/api/jobs", data={"operation": "image.convert", "node_id": str(nid)}, files=files)
    assert r.status_code == 404

    assert owner.post(f"/api/nodes/{nid}/grants", json={"username": "invitado"}).status_code == 201
    assert nid in {n["id"] for n in guest.get("/api/nodes").json()}
    # El invitado puede usarlo pero no administrarlo.
    assert guest.patch(f"/api/nodes/{nid}", json={"is_paused": True}).status_code == 403
    r = guest.post("/api/jobs", data={"operation": "image.convert", "node_id": str(nid)}, files=files)
    assert r.status_code == 201

    uid = guest.get("/api/auth/me").json()["id"]
    owner.delete(f"/api/nodes/{nid}/grants/{uid}")
    assert nid not in {n["id"] for n in guest.get("/api/nodes").json()}
    # Solo admin comparte con todos
    assert owner.patch(f"/api/nodes/{nid}", json={"shared_with_all": True}).status_code == 403


def test_job_validation(admin):
    files = {"files": ("doc.pdf", b"%PDF-1.4", "application/pdf")}
    r = admin.post("/api/jobs", data={"operation": "image.convert"}, files=files)
    assert r.status_code == 400
    r = admin.post("/api/jobs", data={"operation": "shell.exec"}, files=files)
    assert r.status_code == 400
    r = admin.post("/api/jobs", data={"operation": "pdf.compress", "params": "not json"}, files=files)
    assert r.status_code == 400
    r = admin.post("/api/jobs", data={"operation": "pdf.compress", "params": json.dumps({"level": "high"})}, files=files)
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "queued" and job["inputs"][0]["filename"] == "doc.pdf"
    assert admin.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert admin.delete(f"/api/jobs/{job['id']}").status_code == 204


def test_jobs_are_private(admin, app):
    a = create_user(admin, app, "usuario_a")
    b = create_user(admin, app, "usuario_b")
    files = {"files": ("x.png", png_bytes(), "image/png")}
    job = a.post("/api/jobs", data={"operation": "image.convert"}, files=files).json()
    assert b.get(f"/api/jobs/{job['id']}").status_code == 404
    assert job["id"] not in {j["id"] for j in b.get("/api/jobs").json()}
    assert job["id"] in {j["id"] for j in admin.get("/api/jobs").json()}


def test_worker_api_requires_token(client):
    assert client.get("/api/worker/jobs/" + "0" * 32 + "/inputs/1").status_code == 401
    r = client.get("/api/worker/jobs/" + "0" * 32 + "/inputs/1", headers={"Authorization": "Bearer sdn_bad"})
    assert r.status_code == 401


def test_ui_websocket_auth_and_origin(admin):
    with pytest.raises(WebSocketDisconnect):
        with admin.websocket_connect("/ws/ui", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
    with admin.websocket_connect("/ws/ui", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_node_websocket_rejects_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/node", headers={"authorization": "Bearer nope"}) as ws:
            ws.receive_json()


# --- Extremo a extremo con el agente real -------------------------------------


def _run_agent(server_url: str, token: str, tmp_path, stop: threading.Event):
    from snackdrop_worker.agent import Agent, WorkerConfig

    cfg = WorkerConfig(
        server=server_url,
        token=token,
        work_dir=tmp_path / "worker",
        allowed_operations=["image.convert", "pdf.compress"],
        hostname="test-node",
    )

    async def main():
        agent = Agent(cfg)
        task = asyncio.create_task(agent.run_forever())
        while not stop.is_set():
            await asyncio.sleep(0.05)
        agent.stop()
        if agent._ws is not None:
            await agent._ws.close()
        await asyncio.wait_for(task, timeout=10)

    asyncio.run(main())


def _wait_job(http: httpx.Client, job_id: str, timeout=30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = http.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"El trabajo no terminó: {job}")


def _wait_online(http: httpx.Client, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        nodes = http.get("/api/nodes").json()
        if nodes and nodes[0]["online"]:
            return nodes[0]
        time.sleep(0.1)
    raise AssertionError("El nodo no se conectó")


def test_end_to_end_webp_batch(live_server, tmp_path):
    from conftest import ADMIN_PASSWORD

    _app, url = live_server
    stop = threading.Event()
    thread = threading.Thread(target=_run_agent, args=(url, LOCAL_TOKEN, tmp_path, stop), daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=url, headers=CSRF, timeout=30) as http:
            assert http.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
            node = _wait_online(http)
            assert node["os"] and "image.convert" in node["capabilities"]

            files = [("files", (f"foto{i}.png", png_bytes(), "image/png")) for i in range(5)]
            params = json.dumps({"format": "webp", "quality": 70, "max_width": 400})
            r = http.post("/api/jobs", data={"operation": "image.convert", "params": params, "node_id": str(node["id"])}, files=files)
            assert r.status_code == 201, r.text
            job = _wait_job(http, r.json()["id"])
            assert job["status"] == "done", job
            assert len(job["outputs"]) == 5
            assert job["assigned_node_name"] == "LilNasX"

            z = http.get(f"/api/jobs/{job['id']}/download")
            assert z.status_code == 200
            with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                names = sorted(zf.namelist())
                assert names == [f"foto{i}.webp" for i in range(5)]
                with Image.open(io.BytesIO(zf.read(names[0]))) as im:
                    assert im.format == "WEBP" and im.size == (400, 300)

            logs = http.get(f"/api/jobs/{job['id']}/logs").json()
            assert any("foto0.png → foto0.webp" in l["line"] for l in logs)

            # PDF con pikepdf/ghostscript
            import pikepdf

            buf = io.BytesIO()
            pdf = pikepdf.new()
            for _ in range(3):
                pdf.add_blank_page()
            pdf.save(buf)
            r = http.post(
                "/api/jobs",
                data={"operation": "pdf.compress", "params": json.dumps({"level": "high"})},
                files=[("files", ("reporte.pdf", buf.getvalue(), "application/pdf"))],
            )
            job = _wait_job(http, r.json()["id"])
            assert job["status"] == "done", job
            out = http.get(f"/api/jobs/{job['id']}/download")
            assert out.content.startswith(b"%PDF-")

            # Un archivo corrupto termina en fallo controlado.
            r = http.post(
                "/api/jobs",
                data={"operation": "image.convert"},
                files=[("files", ("rota.png", b"no soy una imagen", "image/png"))],
            )
            job = _wait_job(http, r.json()["id"])
            assert job["status"] == "failed" and "rota.png" in job["error"]

            nodes = http.get("/api/nodes").json()
            assert nodes[0]["jobs_done"] == 2 and nodes[0]["jobs_failed"] == 1
    finally:
        stop.set()
        thread.join(timeout=15)


def test_paused_node_does_not_take_jobs(live_server, tmp_path):
    from conftest import ADMIN_PASSWORD

    _app, url = live_server
    stop = threading.Event()
    with httpx.Client(base_url=url, headers=CSRF, timeout=30) as http:
        http.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        nid = http.get("/api/nodes").json()[0]["id"]
        http.patch(f"/api/nodes/{nid}", json={"is_paused": True})
        thread = threading.Thread(target=_run_agent, args=(url, LOCAL_TOKEN, tmp_path, stop), daemon=True)
        thread.start()
        try:
            _wait_online(http)
            r = http.post("/api/jobs", data={"operation": "image.convert"}, files=[("files", ("a.png", png_bytes(), "image/png"))])
            jid = r.json()["id"]
            time.sleep(1)
            assert http.get(f"/api/jobs/{jid}").json()["status"] == "queued"
            http.patch(f"/api/nodes/{nid}", json={"is_paused": False})
            assert _wait_job(http, jid)["status"] == "done"
        finally:
            stop.set()
            thread.join(timeout=15)


def test_login_helper_used():
    assert callable(login)
