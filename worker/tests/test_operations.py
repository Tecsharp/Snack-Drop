from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snackdrop_worker.processors import Cancelled, Context, ProcessingError, available_operations, run_batch, run_each  # noqa: E402
from snackdrop_worker.processors.common import ffmpeg_path, parse_ranges  # noqa: E402

AVAILABLE = set(available_operations())
AI = os.getenv("SNACKDROP_TEST_AI") == "1"


def needs(op):
    return pytest.mark.skipif(op not in AVAILABLE, reason=f"{op} no disponible en este equipo")


def img(path: Path, size=(800, 600), color=(30, 120, 200), fmt=None, **kw) -> Path:
    im = Image.new("RGB", size, color)
    # Un poco de detalle a la derecha para el recorte inteligente
    for x in range(size[0] * 3 // 4, size[0]):
        for y in range(0, size[1], 7):
            im.putpixel((x, y), (255, (x * 7) % 255, (y * 3) % 255))
    im.save(path, format=fmt, **kw)
    return path


def pdf(path: Path, pages=3, size=(595, 842)) -> Path:
    doc = pikepdf.new()
    for _ in range(pages):
        doc.add_blank_page(page_size=size)
    doc.save(path)
    return path


# --- utilidades ------------------------------------------------------------------


def test_parse_ranges():
    assert parse_ranges("1-3,5", 10) == [[0, 1, 2], [4]]
    assert parse_ranges("8-", 10) == [[7, 8, 9]]
    with pytest.raises(ProcessingError):
        parse_ranges("4-2", 10)
    with pytest.raises(ProcessingError):
        parse_ranges("20", 10)
    with pytest.raises(ProcessingError):
        parse_ranges("abc", 10)


# --- imágenes ----------------------------------------------------------------------


@needs("image.heic")
def test_heic_to_jpeg(tmp_path):
    import pillow_heif  # noqa: F401

    src = img(tmp_path / "IMG_0001.HEIC", fmt="HEIF")
    out, _ = run_each("image.heic", {"format": "jpeg"}, src, tmp_path / "out", "IMG_0001.HEIC")[0]
    assert out.name == "IMG_0001.jpg"
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.size == (800, 600)


@needs("image.avif")
def test_avif(tmp_path):
    src = img(tmp_path / "a.png")
    out, _ = run_each("image.avif", {"quality": 60}, src, tmp_path / "out", "a.png")[0]
    with Image.open(out) as im:
        assert im.format == "AVIF"


def test_watermark_positions(tmp_path):
    src = img(tmp_path / "foto.jpg", fmt="JPEG")
    for pos in ("bottom-right", "center", "tiled"):
        out, info = run_each("image.watermark", {"text": "© Abisai 2026", "position": pos, "opacity": 70},
                             src, tmp_path / pos, "foto.jpg")[0]
        with Image.open(out) as im, Image.open(src) as orig:
            assert im.format == "JPEG" and im.size == orig.size
            assert im.tobytes() != orig.convert("RGB").tobytes()
        assert "© Abisai 2026" in info
    with pytest.raises(ProcessingError):
        run_each("image.watermark", {"text": "  "}, src, tmp_path / "x", "foto.jpg")


def test_crop_aspects(tmp_path):
    src = img(tmp_path / "a.png", size=(1600, 900))
    out, _ = run_each("image.crop", {"aspect": "1:1", "mode": "smart", "format": "png"}, src, tmp_path / "o1", "a.png")[0]
    with Image.open(out) as im:
        assert im.size == (900, 900)
        # el recorte inteligente se va hacia la zona con detalle (derecha)
        assert im.getpixel((im.width - 1, 0))[0] == 255
    out, _ = run_each("image.crop", {"aspect": "9:16", "mode": "center"}, src, tmp_path / "o2", "a.png")[0]
    with Image.open(out) as im:
        assert im.size == (506, 900)


def test_strip_jpeg_lossless(tmp_path):
    src = tmp_path / "gps.jpg"
    im = Image.new("RGB", (300, 200), (10, 200, 10))
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0132] = "2026:10:27 10:00:00"
    im.save(src, format="JPEG", exif=exif.tobytes(), quality=90)
    out, info = run_each("image.strip", {}, src, tmp_path / "out", "gps.jpg")[0]
    with Image.open(out) as res:
        assert not res.getexif()
    # sin recomprimir: los datos de imagen son idénticos
    assert src.read_bytes().split(b"\xff\xda", 1)[1] == out.read_bytes().split(b"\xff\xda", 1)[1]
    assert "sin recomprimir" in info


def test_strip_respects_orientation(tmp_path):
    src = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[274] = 6  # rotar 90°
    Image.new("RGB", (300, 200)).save(src, exif=exif.tobytes())
    out, _ = run_each("image.strip", {}, src, tmp_path / "out", "rot.jpg")[0]
    with Image.open(out) as res:
        assert res.size == (200, 300) and not res.getexif().get(274)


def test_rename_by_date(tmp_path):
    files = []
    for name, date in (("b.jpg", "2026:05:02 10:00:00"), ("a.jpg", "2026:01:15 09:30:00"), ("c.jpg", None)):
        p = tmp_path / name
        exif = Image.Exif()
        if date:
            exif.get_ifd(0x8769)[36867] = date
        Image.new("RGB", (10, 10)).save(p, exif=exif.tobytes())
        files.append((p, name))
    outs = run_batch("image.rename", {"pattern": "viaje_{fecha}_{n}", "sort": "date"}, files, tmp_path / "out")
    assert [o.name for o, _ in outs] == ["viaje_2026-01-15_001.jpg", "viaje_2026-05-02_002.jpg", "viaje_sin-fecha_003.jpg"]


@pytest.mark.skipif(not AI or "image.remove_bg" not in AVAILABLE, reason="define SNACKDROP_TEST_AI=1 (descarga modelo)")
def test_remove_background(tmp_path):
    src = tmp_path / "obj.png"
    im = Image.new("RGB", (320, 320), (240, 240, 240))
    for x in range(100, 220):
        for y in range(80, 260):
            im.putpixel((x, y), (200, 30, 30))
    im.save(src)
    out, _ = run_each("image.remove_bg", {"model": "u2netp"}, src, tmp_path / "out", "obj.png")[0]
    with Image.open(out) as res:
        assert res.mode == "RGBA"
        assert res.getpixel((5, 5))[3] < 50  # fondo transparente


@needs("image.upscale")
def test_upscale(tmp_path):
    src = img(tmp_path / "s.png", size=(120, 80))
    out, _ = run_each("image.upscale", {"scale": 3}, src, tmp_path / "out", "s.png")[0]
    with Image.open(out) as res:
        assert res.size == (360, 240)
    assert out.name == "s_x3.png"


# --- PDF -------------------------------------------------------------------------------


def test_pdf_merge_split_rotate(tmp_path):
    a, b = pdf(tmp_path / "a.pdf", 2), pdf(tmp_path / "b.pdf", 3)
    (merged, info), = run_batch("pdf.merge", {"output_name": "todo"}, [(a, "a.pdf"), (b, "b.pdf")], tmp_path / "m")
    assert merged.name == "todo.pdf" and len(pikepdf.open(merged).pages) == 5
    with pytest.raises(ProcessingError):
        run_batch("pdf.merge", {}, [(a, "a.pdf")], tmp_path / "m2")

    parts = run_each("pdf.split", {"mode": "ranges", "ranges": "1-2,5"}, merged, tmp_path / "s", "todo.pdf")
    assert [p.name for p, _ in parts] == ["todo_p1-2.pdf", "todo_p5.pdf"]
    assert len(run_each("pdf.split", {"mode": "each_page"}, merged, tmp_path / "s2", "todo.pdf")) == 5

    out, _ = run_each("pdf.rotate", {"angle": 90, "pages": "2"}, merged, tmp_path / "r", "todo.pdf")[0]
    pages = pikepdf.open(out).pages
    assert int(pages[1].obj.get("/Rotate", 0)) == 90 and int(pages[0].obj.get("/Rotate", 0)) == 0


def test_pdf_images_roundtrip(tmp_path):
    files = [(img(tmp_path / "1.jpg", fmt="JPEG"), "1.jpg"), (img(tmp_path / "2.png", size=(600, 800)), "2.png")]
    rgba = tmp_path / "3.png"
    Image.new("RGBA", (300, 300), (255, 0, 0, 100)).save(rgba)
    files.append((rgba, "3.png"))
    (out, _), = run_batch("pdf.from_images", {"page_size": "a4", "margin_mm": 10}, files, tmp_path / "p")
    doc = pikepdf.open(out)
    assert len(doc.pages) == 3
    for page, landscape in zip(doc.pages, (True, False, False)):
        w, h = float(page.mediabox[2]), float(page.mediabox[3])
        assert abs(min(w, h) - 595.3) < 1 and abs(max(w, h) - 841.9) < 1  # A4
        assert (w > h) is landscape  # se orienta según la foto

    images = run_each("pdf.to_images", {"dpi": 72, "format": "jpeg", "pages": "1,3"}, out, tmp_path / "i", "doc.pdf")
    assert [p.name for p, _ in images] == ["doc_p1.jpg", "doc_p3.jpg"]
    with Image.open(images[1][0]) as im:
        assert abs(im.width - 595) <= 1 and abs(im.height - 842) <= 1


def test_pdf_protect_unlock(tmp_path):
    src = pdf(tmp_path / "c.pdf", 1)
    out, _ = run_each("pdf.protect", {"password": "Secreto-123", "allow_copy": False}, src, tmp_path / "p", "c.pdf")[0]
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(out)
    assert pikepdf.open(out, password="Secreto-123").is_encrypted
    with pytest.raises(ProcessingError, match="contraseña no es correcta"):
        run_each("pdf.unlock", {"password": "mala"}, out, tmp_path / "u0", "c.pdf")
    plain, _ = run_each("pdf.unlock", {"password": "Secreto-123"}, out, tmp_path / "u", "c.pdf")[0]
    assert not pikepdf.open(plain).is_encrypted


def test_pdf_watermark(tmp_path):
    src = pdf(tmp_path / "w.pdf", 2)
    out, info = run_each("pdf.watermark", {"text": "CONFIDENCIAL — Año", "opacity": 30}, src, tmp_path / "o", "w.pdf")[0]
    doc = pikepdf.open(out)
    content = b"".join(c.read_bytes() for c in doc.pages[0].obj.Contents) if isinstance(doc.pages[0].obj.Contents, pikepdf.Array) else doc.pages[0].obj.Contents.read_bytes()
    assert b"Do" in content  # el sello se dibuja como XObject superpuesto
    assert "2 página(s)" in info


@needs("pdf.ocr")
def test_pdf_ocr(tmp_path):
    src = pdf(tmp_path / "scan.pdf", 1)
    out, _ = run_each("pdf.ocr", {"language": "eng"}, src, tmp_path / "o", "scan.pdf")[0]
    assert out.exists()


# --- documentos y archivos ------------------------------------------------------------


def test_zip_and_extract_roundtrip(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hola")
    b = tmp_path / "b.txt"
    b.write_text("mundo" * 100)
    (archive, _), = run_batch("archive.zip", {"output_name": "paquete"}, [(a, "a.txt"), (b, "b.txt"), (a, "a.txt")], tmp_path / "z")
    assert archive.name == "paquete.zip"
    assert sorted(zipfile.ZipFile(archive).namelist()) == ["a (1).txt", "a.txt", "b.txt"]
    outs = run_each("archive.extract", {}, archive, tmp_path / "x", "paquete.zip")
    assert sorted(p.name for p, _ in outs) == ["a (1).txt", "a.txt", "b.txt"]


def test_7z_with_password(tmp_path):
    a = tmp_path / "secreto.txt"
    a.write_text("dato")
    (archive, info), = run_batch("archive.zip", {"format": "7z", "password": "Clave-9"}, [(a, "secreto.txt")], tmp_path / "z")
    assert "contraseña" in info
    with pytest.raises(ProcessingError):
        run_each("archive.extract", {}, archive, tmp_path / "x0", "archivos.7z")
    outs = run_each("archive.extract", {"password": "Clave-9"}, archive, tmp_path / "x", "archivos.7z")
    assert outs[0][0].read_text() == "dato"


def test_extract_blocks_traversal_and_links(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../etc/passwd", "x")
        zf.writestr("/abs.txt", "x")
        zf.writestr("fotos/2024/ok.txt", "bien")
        zf.writestr("__MACOSX/._ok.txt", "x")
        link = zipfile.ZipInfo("enlace")
        link.external_attr = (0o120777 << 16)
        zf.writestr(link, "/etc/passwd")
    outs = run_each("archive.extract", {}, evil, tmp_path / "x", "evil.zip")
    assert [p.name for p, _ in outs] == ["fotos - 2024 - ok.txt"]
    assert not (tmp_path.parent / "etc").exists()

    tgz = tmp_path / "t.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        data = b"contenido"
        info = tarfile.TarInfo("docs/x.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        sym = tarfile.TarInfo("docs/link")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "/etc/passwd"
        tf.addfile(sym)
    outs = run_each("archive.extract", {}, tgz, tmp_path / "t", "t.tar.gz")
    assert [p.name for p, _ in outs] == ["docs - x.txt"]


def test_extract_zip_bomb_stopped(tmp_path):
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("ceros.bin", b"\0" * (300 * 1024 * 1024))
    with pytest.raises(ProcessingError, match="sospechosamente grande"):
        run_each("archive.extract", {}, bomb, tmp_path / "x", "bomb.zip")
    assert not list((tmp_path / "x").glob("*"))


def test_hash(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"abc")
    (out, _), = run_batch("file.hash", {"algorithm": "sha256"}, [(a, "a.bin")], tmp_path / "h")
    assert out.read_text() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  a.bin\n"


@needs("doc.to_pdf")
def test_doc_to_pdf(tmp_path):
    src = tmp_path / "nota.txt"
    src.write_text("Hola desde Snack-Drop")
    out, _ = run_each("doc.to_pdf", {}, src, tmp_path / "o", "nota.txt")[0]
    assert out.read_bytes().startswith(b"%PDF")


# --- video y audio ----------------------------------------------------------------------

FFMPEG = ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg no disponible")


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    if FFMPEG is None:
        pytest.skip("ffmpeg no disponible")
    path = tmp_path_factory.mktemp("media") / "clip.mov"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "4", "-c:v", "libx264", "-crf", "10",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", str(path)], check=True)
    return path


@needs_ffmpeg
def test_video_compress_resize_convert(sample_video, tmp_path):
    progress = []
    ctx = Context(on_progress=progress.append)
    out, info = run_each("video.compress", {"crf": 30, "preset": "veryfast", "hardware": "off", "max_height": 480},
                         sample_video, tmp_path / "c", "clip.mov", ctx)[0]
    assert out.name == "clip.mp4" and out.stat().st_size < sample_video.stat().st_size
    assert progress and max(progress) > 0.5
    from snackdrop_worker.processors.media import probe

    assert probe(out, "x").height == 480

    out, _ = run_each("video.resize", {"height": 360, "hardware": "off"}, sample_video, tmp_path / "r", "clip.mov")[0]
    assert probe(out, "x").height == 360 and out.name == "clip_360p.mov"

    out, info = run_each("video.convert", {"container": "mp4"}, sample_video, tmp_path / "v", "clip.mov")[0]
    assert "sin recodificar" in info and out.suffix == ".mp4"
    out, info = run_each("video.convert", {"container": "mkv"}, sample_video, tmp_path / "v2", "clip.mov")[0]
    assert out.suffix == ".mkv"


@needs_ffmpeg
def test_audio_ops(sample_video, tmp_path):
    from snackdrop_worker.processors.media import probe

    mp3, _ = run_each("video.extract_audio", {"format": "mp3", "bitrate": 128}, sample_video, tmp_path / "a", "clip.mov")[0]
    assert mp3.suffix == ".mp3" and probe(mp3, "x").audio == "mp3"
    flac, _ = run_each("audio.convert", {"format": "flac", "mono": True}, mp3, tmp_path / "b", "clip.mp3")[0]
    assert probe(flac, "x").audio == "flac"
    norm, info = run_each("audio.normalize", {"target_lufs": -14}, mp3, tmp_path / "n", "clip.mp3")[0]
    assert norm.suffix == ".mp3" and "-14 LUFS" in info


@needs_ffmpeg
def test_gif_and_thumbnails(sample_video, tmp_path):
    gif, _ = run_each("video.gif", {"start": 1, "duration": 1.5, "width": 320, "fps": 10}, sample_video, tmp_path / "g", "clip.mov")[0]
    with Image.open(gif) as im:
        assert im.format == "GIF" and im.width == 320 and im.n_frames >= 10
    (sheet, _), = run_each("video.thumbnails", {"mode": "sheet", "columns": 3, "rows": 2, "width": 200}, sample_video, tmp_path / "t", "clip.mov")
    with Image.open(sheet) as im:
        assert im.width > 600
    frames = run_each("video.thumbnails", {"mode": "frames", "count": 3, "format": "png"}, sample_video, tmp_path / "f", "clip.mov")
    assert [p.name for p, _ in frames] == ["clip_01.png", "clip_02.png", "clip_03.png"]


@needs_ffmpeg
def test_video_cancel_kills_ffmpeg(sample_video, tmp_path):
    flag = threading.Event()
    ctx = Context(is_cancelled=flag.is_set, on_progress=lambda f: flag.set())
    with pytest.raises(Cancelled):
        run_each("video.compress", {"preset": "veryslow", "crf": 18, "hardware": "off", "codec": "h265"},
                 sample_video, tmp_path / "c", "clip.mov", ctx)
    assert not list((tmp_path / "c").glob("*.mp4"))


@needs_ffmpeg
def test_media_rejects_garbage(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"no es video")
    with pytest.raises(ProcessingError, match="no es un archivo de audio o video"):
        run_each("video.compress", {}, bad, tmp_path / "o", "x.mp4")


@pytest.mark.skipif(not AI or not shutil.which("say") or "audio.transcribe" not in AVAILABLE,
                    reason="define SNACKDROP_TEST_AI=1 en macOS (usa «say» y descarga Whisper tiny)")
def test_transcribe_spanish(tmp_path):
    audio = tmp_path / "voz.aiff"
    subprocess.run(["say", "-v", "Paulina", "-o", str(audio), "Hola, esta es una prueba de transcripción."], check=True)
    outs = run_each("audio.transcribe", {"model": "tiny", "language": "es", "output": "all"}, audio, tmp_path / "o", "voz.aiff")
    names = sorted(p.name for p, _ in outs)
    assert names == ["voz.srt", "voz.txt", "voz.vtt"]
    text = (tmp_path / "o" / "voz.txt").read_text().lower()
    assert "prueba" in text
