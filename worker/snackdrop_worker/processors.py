"""Implementación local de las operaciones del catálogo.

El agente solo ejecuta estas funciones; nunca comandos recibidos por red.
Los parámetros se vuelven a validar aquí aunque el servidor ya lo haya hecho.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 200_000_000

IMAGE_FORMATS = {"webp": ".webp", "jpeg": ".jpg", "png": ".png"}
PDF_LEVELS = {"low": "/printer", "medium": "/ebook", "high": "/screen"}


class ProcessingError(Exception):
    pass


def _unique(out_dir: Path, stem: str, ext: str) -> Path:
    candidate = out_dir / f"{stem}{ext}"
    n = 1
    while candidate.exists():
        candidate = out_dir / f"{stem} ({n}){ext}"
        n += 1
    return candidate


def _clamp_int(value, lo: int, hi: int, default: int | None) -> int | None:
    if value is None:
        return default
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


# Formatos donde «varios cuadros» significa animación. Los JPEG MPO de iPhone/Android
# traen imágenes secundarias (profundidad, HDR) de otro tamaño: se usa solo la principal.
ANIMATED_SOURCES = {"GIF", "WEBP", "PNG"}
FALLBACK_QUALITIES = (85, 80, 75, 70, 65, 60)


def _encode(im: Image.Image, fmt: str, quality: int, lossless: bool, animated: bool, extra: dict) -> bytes:
    kwargs = dict(extra)
    if fmt == "webp":
        kwargs.update(quality=quality, lossless=lossless, method=4)
        if animated:
            kwargs["save_all"] = True
    elif fmt == "jpeg":
        kwargs.update(quality=quality, optimize=True, progressive=True)
    else:
        kwargs.update(optimize=True)
    buf = io.BytesIO()
    im.save(buf, format=fmt.upper(), **kwargs)
    return buf.getvalue()


def convert_image(src: Path, out_dir: Path, original_name: str, params: dict) -> tuple[Path, str]:
    fmt = params.get("format", "webp")
    if fmt not in IMAGE_FORMATS:
        raise ProcessingError(f"Formato no soportado: {fmt}")
    quality = _clamp_int(params.get("quality"), 1, 100, 80)
    max_w = _clamp_int(params.get("max_width"), 16, 16384, None)
    max_h = _clamp_int(params.get("max_height"), 16, 16384, None)
    lossless = bool(params.get("lossless")) and fmt == "webp"
    strip = params.get("strip_metadata", True) is not False
    never_larger = params.get("never_larger", True) is not False

    before = src.stat().st_size
    out = _unique(out_dir, Path(original_name).stem or "imagen", IMAGE_FORMATS[fmt])
    note = ""
    try:
        with Image.open(src) as im:
            source_format = im.format or ""
            animated = (
                fmt == "webp" and source_format in ANIMATED_SOURCES and bool(getattr(im, "is_animated", False))
            )
            if not animated:
                im.seek(0)
            im.load()
            exif = im.info.get("exif")
            icc = im.info.get("icc_profile")
            orig_size = im.size
            if not animated:
                im = ImageOps.exif_transpose(im)
                if max_w or max_h:
                    im.thumbnail((max_w or 1_000_000, max_h or 1_000_000), Image.Resampling.LANCZOS)
            if fmt == "jpeg":
                if im.mode in ("RGBA", "LA", "P"):
                    rgba = im.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.getchannel("A"))
                    im = bg
                elif im.mode != "RGB":
                    im = im.convert("RGB")
            elif not animated and im.mode not in ("RGB", "RGBA", "L", "LA") + (("P",) if fmt == "png" else ()):
                im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")

            extra: dict = {}
            if icc:
                extra["icc_profile"] = icc
            if exif and not strip:
                extra["exif"] = exif
            data = _encode(im, fmt, quality, lossless, animated, extra)
            new_size = im.size

            # Re-codificar un JPEG ya comprimido con calidad muy alta suele crecer el archivo.
            if never_larger and len(data) >= before and fmt in ("webp", "jpeg") and not lossless:
                for q in (q for q in FALLBACK_QUALITIES if q < quality):
                    data = _encode(im, fmt, q, lossless, animated, extra)
                    if len(data) < before:
                        note = f", calidad ajustada {quality}→{q} para no crecer"
                        break
        src_ext = Path(original_name).suffix.lower()
        same_format = src_ext in ({".jpg", ".jpeg"} if fmt == "jpeg" else {IMAGE_FORMATS[fmt]})
        if never_larger and len(data) >= before and same_format and new_size == orig_size and not (strip and exif):
            shutil.copyfile(src, out)
            note = ", ya estaba optimizada: se conserva el original"
        else:
            if never_larger and len(data) >= before:
                note = ", no se pudo reducir más"
            out.write_bytes(data)
    except ProcessingError:
        raise
    except UnidentifiedImageError as exc:
        out.unlink(missing_ok=True)
        raise ProcessingError(f"{original_name}: no es una imagen válida o está dañada") from exc
    except Image.DecompressionBombError as exc:
        out.unlink(missing_ok=True)
        raise ProcessingError(f"{original_name}: la imagen es demasiado grande para procesarla") from exc
    except Exception as exc:  # noqa: BLE001 - Pillow lanza OSError, ValueError, RuntimeError…
        out.unlink(missing_ok=True)
        reason = str(exc).replace(str(src), original_name) or type(exc).__name__
        raise ProcessingError(f"{original_name}: {reason}") from exc

    after = out.stat().st_size
    dims = f"{orig_size[0]}x{orig_size[1]}" + (f" → {new_size[0]}x{new_size[1]}" if new_size != orig_size else "")
    return out, f"{original_name} → {out.name} ({dims}, {_fmt(before)} → {_fmt(after)}{note})"


def _ghostscript() -> str | None:
    for name in ("gs", "gswin64c", "gswin32c"):
        path = shutil.which(name)
        if path:
            return path
    return None


def compress_pdf(src: Path, out_dir: Path, original_name: str, params: dict) -> tuple[Path, str]:
    level = params.get("level", "medium")
    if level not in PDF_LEVELS:
        raise ProcessingError(f"Nivel no soportado: {level}")
    grayscale = bool(params.get("grayscale"))
    with src.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise ProcessingError(f"{original_name} no es un PDF válido")

    out = _unique(out_dir, Path(original_name).stem or "documento", ".pdf")
    gs = _ghostscript()
    engine = "ghostscript"
    if gs:
        cmd = [
            gs,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.5",
            f"-dPDFSETTINGS={PDF_LEVELS[level]}",
            "-dSAFER",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
        ]
        if grayscale:
            cmd += ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray"]
        cmd += [f"-sOutputFile={out}", str(src)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=900, check=False)
        except subprocess.TimeoutExpired as exc:
            out.unlink(missing_ok=True)
            raise ProcessingError(f"Tiempo agotado comprimiendo {original_name}") from exc
        if proc.returncode != 0 or not out.exists():
            out.unlink(missing_ok=True)
            err = proc.stderr.decode(errors="replace")[-500:]
            raise ProcessingError(f"Ghostscript falló con {original_name}: {err}")
    else:
        try:
            import pikepdf
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ProcessingError("No hay Ghostscript ni pikepdf instalados en este nodo") from exc
        engine = "pikepdf"
        try:
            with pikepdf.open(src) as pdf:
                pdf.remove_unreferenced_resources()
                pdf.save(
                    out,
                    compress_streams=True,
                    recompress_flate=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                )
        except pikepdf.PdfError as exc:
            out.unlink(missing_ok=True)
            raise ProcessingError(f"No se pudo procesar {original_name}: {exc}") from exc

    before, after = src.stat().st_size, out.stat().st_size
    if after >= before:
        shutil.copyfile(src, out)
        return out, f"{original_name}: ya estaba optimizado ({_fmt(before)}), se conserva el original"
    saved = 100 - after * 100 / before
    return out, f"{original_name}: {_fmt(before)} → {_fmt(after)} (-{saved:.0f}%, {engine})"


PROCESSORS = {
    "image.convert": convert_image,
    "pdf.compress": compress_pdf,
}


def process(operation: str, params: dict, src: Path, out_dir: Path, original_name: str) -> tuple[Path, str]:
    fn = PROCESSORS.get(operation)
    if fn is None:
        raise ProcessingError(f"Operación no soportada por este nodo: {operation}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return fn(src, out_dir, original_name, params if isinstance(params, dict) else {})


def _fmt(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # pragma: no cover
