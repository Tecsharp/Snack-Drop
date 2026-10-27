from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snackdrop_worker.agent import WorkerConfig, system_info  # noqa: E402
from snackdrop_worker.processors import ProcessingError, process  # noqa: E402


def make_image(path: Path, mode="RGBA", size=(1200, 800)) -> Path:
    Image.new(mode, size, (10, 120, 200, 128) if mode == "RGBA" else (10, 120, 200)).save(path)
    return path


def test_png_to_webp_resized(tmp_path):
    src = make_image(tmp_path / "in.png")
    out, info = process("image.convert", {"format": "webp", "quality": 60, "max_width": 600}, src, tmp_path / "out", "Vacaciones.png")
    assert out.name == "Vacaciones.webp"
    with Image.open(out) as im:
        assert im.format == "WEBP" and im.size == (600, 400) and im.mode == "RGBA"
    assert "1200x800 → 600x400" in info


def test_rgba_to_jpeg_flattens(tmp_path):
    src = make_image(tmp_path / "in.png")
    out, _ = process("image.convert", {"format": "jpeg"}, src, tmp_path / "out", "a.png")
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.mode == "RGB"


def test_name_collisions(tmp_path):
    src = make_image(tmp_path / "in.png", "RGB")
    a, _ = process("image.convert", {}, src, tmp_path / "out", "x.png")
    b, _ = process("image.convert", {}, src, tmp_path / "out", "x.jpg")
    assert a.name == "x.webp" and b.name == "x (1).webp"


def test_invalid_image(tmp_path):
    src = tmp_path / "bad.png"
    src.write_bytes(b"nope")
    with pytest.raises(ProcessingError):
        process("image.convert", {}, src, tmp_path / "out", "bad.png")


def test_unknown_operation_rejected(tmp_path):
    with pytest.raises(ProcessingError):
        process("shell.exec", {"cmd": "id"}, tmp_path, tmp_path / "out", "x")


def test_bad_params_clamped(tmp_path):
    src = make_image(tmp_path / "in.png", "RGB")
    out, _ = process("image.convert", {"quality": 9999, "max_width": "abc"}, src, tmp_path / "out", "q.png")
    assert out.exists()
    with pytest.raises(ProcessingError):
        process("image.convert", {"format": "exe"}, src, tmp_path / "out", "q.png")


def test_pdf_compress(tmp_path):
    src = tmp_path / "doc.pdf"
    pdf = pikepdf.new()
    for _ in range(5):
        pdf.add_blank_page()
    pdf.save(src, compress_streams=False)
    out, info = process("pdf.compress", {"level": "high"}, src, tmp_path / "out", "Contrato.pdf")
    assert out.name == "Contrato.pdf" and out.read_bytes().startswith(b"%PDF-")
    assert out.stat().st_size <= src.stat().st_size
    assert "Contrato.pdf" in info


def test_pdf_rejects_non_pdf(tmp_path):
    src = tmp_path / "fake.pdf"
    src.write_bytes(b"MZ executable")
    with pytest.raises(ProcessingError):
        process("pdf.compress", {}, src, tmp_path / "out", "fake.pdf")


def test_config_and_sysinfo(monkeypatch):
    monkeypatch.setenv("SNACKDROP_SERVER", "https://snack.example.com/")
    monkeypatch.setenv("SNACKDROP_TOKEN", "sdn_x")
    monkeypatch.setenv("SNACKDROP_ALLOWED_OPERATIONS", "image.convert,shell.exec")
    cfg = WorkerConfig.from_env()
    assert cfg.ws_url == "wss://snack.example.com/ws/node"
    assert cfg.allowed_operations == ["image.convert"]
    info = system_info("host")
    assert info["hostname"] == "host" and info["os"]


def _camera_jpeg(path: Path, size=(1600, 1200), quality=82) -> Path:
    """JPEG con ruido, parecido a una foto de celular ya comprimida."""
    import os

    noise = Image.frombytes("L", size, os.urandom(size[0] * size[1])).convert("RGB")
    noise.save(path, quality=quality)
    return path


def test_iphone_mpo_uses_main_image(tmp_path):
    # Los JPEG de iPhone son MPO: foto principal + mapa secundario de otro tamaño.
    src = tmp_path / "IMG_1144.jpg"
    main = Image.new("RGB", (1200, 900), (200, 50, 50))
    depth = Image.new("RGB", (300, 200), (10, 10, 10))
    main.save(src, format="MPO", save_all=True, append_images=[depth])
    with Image.open(src) as im:
        assert im.format == "MPO" and im.is_animated
    out, _ = process("image.convert", {"format": "webp"}, src, tmp_path / "out", "IMG_1144.jpg")
    with Image.open(out) as im:
        assert im.format == "WEBP" and im.size == (1200, 900)
        assert not getattr(im, "is_animated", False)


def test_quality_100_never_larger(tmp_path):
    src = _camera_jpeg(tmp_path / "foto.jpg")
    out, info = process("image.convert", {"format": "webp", "quality": 100}, src, tmp_path / "out", "foto.jpg")
    assert out.stat().st_size < src.stat().st_size, info
    assert "calidad ajustada" in info


def test_same_format_keeps_original_when_cannot_shrink(tmp_path):
    src = _camera_jpeg(tmp_path / "foto.jpg", quality=30)
    out, info = process(
        "image.convert", {"format": "jpeg", "quality": 100, "strip_metadata": False}, src, tmp_path / "out", "foto.jpg"
    )
    assert out.stat().st_size <= src.stat().st_size, info


def test_never_larger_can_be_disabled(tmp_path):
    src = _camera_jpeg(tmp_path / "foto.jpg")
    out, _ = process(
        "image.convert", {"format": "webp", "quality": 100, "never_larger": False}, src, tmp_path / "out", "foto.jpg"
    )
    assert out.stat().st_size > src.stat().st_size
