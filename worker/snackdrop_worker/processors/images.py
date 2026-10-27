"""Operaciones de imagen."""

from __future__ import annotations

import io
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat, UnidentifiedImageError, features

from .common import Context, Output, ProcessingError, choice, clamp_int, fmt_size, models_dir, safe_stem, unique
from .registry import register

Image.MAX_IMAGE_PIXELS = 200_000_000
MAX_OUTPUT_PIXELS = 120_000_000

try:  # fotos HEIC/HEIF de iPhone
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF = True
except ImportError:  # pragma: no cover - depende del entorno
    HEIF = False

IMAGE_FORMATS = {"webp": ".webp", "jpeg": ".jpg", "png": ".png", "avif": ".avif"}
PIL_FORMAT = {"webp": "WEBP", "jpeg": "JPEG", "png": "PNG", "avif": "AVIF"}
EXT_TO_FORMAT = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp", ".avif": "avif"}
# Formatos donde «varios cuadros» significa animación. Los JPEG MPO de iPhone/Android
# traen imágenes secundarias (profundidad, HDR) de otro tamaño: se usa solo la principal.
ANIMATED_SOURCES = {"GIF", "WEBP", "PNG"}
FALLBACK_QUALITIES = (85, 80, 75, 70, 65, 60)
LOSSY = {"webp", "jpeg", "avif"}


def avif_supported() -> bool:
    return bool(features.check("avif"))


def _open(src: Path, name: str) -> Image.Image:
    try:
        im = Image.open(src)
        im.load()
        return im
    except UnidentifiedImageError as exc:
        raise ProcessingError(f"{name}: no es una imagen válida o está dañada") from exc
    except Image.DecompressionBombError as exc:
        raise ProcessingError(f"{name}: la imagen es demasiado grande para procesarla") from exc


def _wrap(name: str, exc: Exception, src: Path) -> ProcessingError:
    if isinstance(exc, ProcessingError):
        return exc
    if isinstance(exc, UnidentifiedImageError):
        return ProcessingError(f"{name}: no es una imagen válida o está dañada")
    if isinstance(exc, Image.DecompressionBombError):
        return ProcessingError(f"{name}: la imagen es demasiado grande para procesarla")
    reason = str(exc).replace(str(src), name) or type(exc).__name__
    return ProcessingError(f"{name}: {reason}")


def _prepare_mode(im: Image.Image, fmt: str) -> Image.Image:
    if fmt == "jpeg":
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            return bg
        return im if im.mode == "RGB" else im.convert("RGB")
    allowed = ("RGB", "RGBA", "L", "LA") + (("P",) if fmt == "png" else ())
    if im.mode not in allowed:
        return im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
    return im


def _encode(im: Image.Image, fmt: str, quality: int, lossless: bool = False, animated: bool = False, extra=None) -> bytes:
    kwargs = dict(extra or {})
    if fmt == "webp":
        kwargs.update(quality=quality, lossless=lossless, method=4)
        if animated:
            kwargs["save_all"] = True
    elif fmt == "jpeg":
        kwargs.update(quality=quality, optimize=True, progressive=True)
    elif fmt == "avif":
        kwargs.update(quality=quality)
    else:
        kwargs.update(optimize=True)
    buf = io.BytesIO()
    im.save(buf, format=PIL_FORMAT[fmt], **kwargs)
    return buf.getvalue()


def _output_format(requested: str, original_name: str) -> str:
    if requested == "same":
        return EXT_TO_FORMAT.get(Path(original_name).suffix.lower(), "jpeg")
    return requested if requested in IMAGE_FORMATS else "webp"


def _save(im: Image.Image, out_dir: Path, stem: str, fmt: str, quality: int, icc=None) -> Path:
    if fmt == "avif" and not avif_supported():
        raise ProcessingError("Este nodo no soporta AVIF")
    im = _prepare_mode(im, fmt)
    out = unique(out_dir, stem, IMAGE_FORMATS[fmt])
    out.write_bytes(_encode(im, fmt, quality, extra={"icc_profile": icc} if icc else None))
    return out


# --- Convertir ---------------------------------------------------------------


def _convert(src: Path, out_dir: Path, original_name: str, params: dict) -> Output:
    fmt = params.get("format", "webp")
    if fmt not in IMAGE_FORMATS:
        raise ProcessingError(f"Formato no soportado: {fmt}")
    if fmt == "avif" and not avif_supported():
        raise ProcessingError("Este nodo no soporta AVIF")
    quality = clamp_int(params.get("quality"), 1, 100, 80)
    max_w = clamp_int(params.get("max_width"), 16, 16384, None)
    max_h = clamp_int(params.get("max_height"), 16, 16384, None)
    lossless = bool(params.get("lossless")) and fmt == "webp"
    strip = params.get("strip_metadata", True) is not False
    never_larger = params.get("never_larger", True) is not False

    before = src.stat().st_size
    out = unique(out_dir, Path(original_name).stem or "imagen", IMAGE_FORMATS[fmt])
    note = ""
    try:
        with Image.open(src) as im:
            source_format = im.format or ""
            animated = fmt == "webp" and source_format in ANIMATED_SOURCES and bool(getattr(im, "is_animated", False))
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
            if not animated:
                im = _prepare_mode(im, fmt)
            extra: dict = {}
            if icc:
                extra["icc_profile"] = icc
            if exif and not strip:
                extra["exif"] = exif
            data = _encode(im, fmt, quality, lossless, animated, extra)
            new_size = im.size

            # Re-codificar un JPEG ya comprimido con calidad muy alta suele crecer el archivo.
            if never_larger and len(data) >= before and fmt in LOSSY and not lossless:
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
    except Exception as exc:  # noqa: BLE001 - Pillow lanza OSError, ValueError, RuntimeError…
        out.unlink(missing_ok=True)
        raise _wrap(original_name, exc, src) from exc

    after = out.stat().st_size
    dims = f"{orig_size[0]}x{orig_size[1]}" + (f" → {new_size[0]}x{new_size[1]}" if new_size != orig_size else "")
    return out, f"{original_name} → {out.name} ({dims}, {fmt_size(before)} → {fmt_size(after)}{note})"


@register("image.convert")
def convert_image(src: Path, out_dir: Path, original_name: str, params: dict, ctx: Context | None = None) -> Output:
    return _convert(src, out_dir, original_name, params)


@register("image.heic", available=lambda: HEIF)
def heic_to(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    return _convert(src, out_dir, name, {**params, "format": choice(params.get("format"), ("jpeg", "webp", "png"), "jpeg")})


@register("image.avif", available=avif_supported)
def to_avif(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    return _convert(src, out_dir, name, {**params, "format": "avif"})


# --- Marca de agua -----------------------------------------------------------

COLORS = {"white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128), "red": (220, 38, 38)}


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@register("image.watermark")
def watermark(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    text = str(params.get("text") or "").strip()[:100]
    if not text:
        raise ProcessingError("Escribe el texto de la marca de agua")
    position = choice(params.get("position"), ("center", "bottom-right", "bottom-left", "top-right", "top-left", "tiled"), "bottom-right")
    opacity = clamp_int(params.get("opacity"), 5, 100, 50) / 100
    size_pct = clamp_int(params.get("size"), 2, 30, 6)
    color = COLORS.get(params.get("color"), COLORS["white"])
    fmt = _output_format(params.get("format", "same"), name)
    quality = clamp_int(params.get("quality"), 1, 100, 85)
    try:
        im = _open(src, name)
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im).convert("RGBA")
        w, h = im.size
        font = _font(max(8, int(min(w, h) * size_pct / 100)))
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        fill = (*color, int(255 * opacity))
        shadow = (0, 0, 0, int(140 * opacity)) if color != COLORS["black"] else (255, 255, 255, int(140 * opacity))
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        tw, th = r - l, b - t
        margin = int(min(w, h) * 0.03)
        if position == "tiled":
            tile = Image.new("RGBA", (tw + margin * 4, th + margin * 4), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((margin * 2 - l, margin * 2 - t), text, font=font, fill=fill)
            tile = tile.rotate(30, expand=True)
            for y in range(-tile.height, h + tile.height, tile.height):
                for x in range(-tile.width, w + tile.width, tile.width):
                    layer.paste(tile, (x, y), tile)
        else:
            x = {"center": (w - tw) // 2, "bottom-right": w - tw - margin, "bottom-left": margin,
                 "top-right": w - tw - margin, "top-left": margin}[position]
            y = {"center": (h - th) // 2, "bottom-right": h - th - margin, "bottom-left": h - th - margin,
                 "top-right": margin, "top-left": margin}[position]
            off = max(1, font.size // 25) if hasattr(font, "size") else 1
            draw.text((x - l + off, y - t + off), text, font=font, fill=shadow)
            draw.text((x - l, y - t), text, font=font, fill=fill)
        im = Image.alpha_composite(im, layer)
        out = _save(im, out_dir, Path(name).stem, fmt, quality, icc)
    except Exception as exc:  # noqa: BLE001
        raise _wrap(name, exc, src) from exc
    return out, f"{name} → {out.name} (marca «{text}», {position})"


# --- Recortar ----------------------------------------------------------------

ASPECTS = {"1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4), "3:2": (3, 2), "2:3": (2, 3), "16:9": (16, 9), "9:16": (9, 16), "4:5": (4, 5), "5:4": (5, 4)}


def _smart_offset(im: Image.Image, crop_w: int, crop_h: int) -> tuple[int, int]:
    """Busca la ventana con más detalle (entropía) a lo largo del eje que sobra."""
    small = im.convert("L")
    scale = 256 / max(small.size)
    if scale < 1:
        small = small.resize((max(1, int(small.width * scale)), max(1, int(small.height * scale))))
    else:
        scale = 1
    sw, sh = max(1, int(crop_w * scale)), max(1, int(crop_h * scale))
    best, best_xy = -1.0, (0, 0)
    steps = 24
    max_x, max_y = small.width - sw, small.height - sh
    for i in range(steps + 1):
        x = round(max_x * i / steps) if max_x > 0 else 0
        y = round(max_y * i / steps) if max_y > 0 else 0
        region = small.crop((x, y, x + sw, y + sh))
        score = region.entropy() + ImageStat.Stat(region).stddev[0] / 64
        if score > best:
            best, best_xy = score, (x, y)
    return int(best_xy[0] / scale), int(best_xy[1] / scale)


@register("image.crop")
def crop(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    aw, ah = ASPECTS.get(params.get("aspect"), (1, 1))
    mode = choice(params.get("mode"), ("center", "smart"), "smart")
    fmt = _output_format(params.get("format", "same"), name)
    quality = clamp_int(params.get("quality"), 1, 100, 85)
    try:
        im = _open(src, name)
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        if w / h > aw / ah:
            cw, ch = int(h * aw / ah), h
        else:
            cw, ch = w, int(w * ah / aw)
        if mode == "smart":
            x, y = _smart_offset(im, cw, ch)
        else:
            x, y = (w - cw) // 2, (h - ch) // 2
        x, y = min(max(0, x), w - cw), min(max(0, y), h - ch)
        im = im.crop((x, y, x + cw, y + ch))
        out = _save(im, out_dir, Path(name).stem, fmt, quality, icc)
    except Exception as exc:  # noqa: BLE001
        raise _wrap(name, exc, src) from exc
    return out, f"{name} → {out.name} ({w}x{h} → {cw}x{ch}, {aw}:{ah}, {'inteligente' if mode == 'smart' else 'centrado'})"


# --- Quitar metadatos --------------------------------------------------------

_DROP_JPEG_MARKERS = {0xE1, 0xED, 0xFE}  # APP1 (EXIF/XMP), APP13 (IPTC), COM


def _strip_jpeg(data: bytes) -> bytes | None:
    """Elimina EXIF/XMP/IPTC sin recomprimir. Devuelve None si la estructura no es la esperada."""
    if data[:2] != b"\xff\xd8":
        return None
    out = bytearray(b"\xff\xd8")
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xDA:  # inicio de los datos de imagen: copiar el resto tal cual
            out += data[i:]
            return bytes(out)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i : i + 2]
            i += 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        segment = data[i : i + 2 + length]
        if marker not in _DROP_JPEG_MARKERS:
            out += segment
        i += 2 + length
    return None


@register("image.strip")
def strip_metadata(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    ext = Path(name).suffix.lower()
    try:
        im = _open(src, name)
        orientation = im.getexif().get(274, 1)
        data = src.read_bytes()
        if ext in (".jpg", ".jpeg") and orientation in (1, None):
            stripped = _strip_jpeg(data)
            if stripped is not None:
                out = unique(out_dir, Path(name).stem, ext)
                out.write_bytes(stripped)
                return out, f"{name}: metadatos eliminados sin recomprimir ({fmt_size(len(data))} → {fmt_size(len(stripped))})"
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        fmt = EXT_TO_FORMAT.get(ext, "png")
        out = unique(out_dir, Path(name).stem, IMAGE_FORMATS[fmt] if fmt != "jpeg" else ext)
        im = _prepare_mode(im, fmt)
        kwargs = {"icc_profile": icc} if icc else {}
        if fmt == "png":
            im.save(out, format="PNG", optimize=True, **kwargs)
            how = "sin pérdida"
        else:
            out.write_bytes(_encode(im, fmt, 95, lossless=fmt == "webp" and im.mode in ("RGBA", "LA"), extra=kwargs))
            how = "recomprimida a calidad 95 (la orientación venía en EXIF)" if fmt == "jpeg" else "recomprimida a calidad 95"
    except Exception as exc:  # noqa: BLE001
        raise _wrap(name, exc, src) from exc
    return out, f"{name}: metadatos eliminados, {how}"


# --- Renombrar ---------------------------------------------------------------


def _exif_datetime(src: Path) -> datetime | None:
    try:
        with Image.open(src) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


@register("image.rename", mode="batch")
def rename(files: list[tuple[Path, str]], out_dir: Path, params: dict, ctx: Context) -> list[Output]:
    pattern = str(params.get("pattern") or "{fecha}_{n}")[:120]
    if not re.search(r"\{(n|nombre|fecha|hora)\}", pattern):
        pattern += "_{n}"
    sort = choice(params.get("sort"), ("upload", "name", "date"), "date")
    start = clamp_int(params.get("start"), 0, 1_000_000, 1)
    items = [(src, name, _exif_datetime(src)) for src, name in files]
    if sort == "name":
        items.sort(key=lambda t: t[1].lower())
    elif sort == "date":
        items.sort(key=lambda t: (t[2] is None, t[2] or datetime.max, t[1].lower()))
    digits = max(3, len(str(start + len(items) - 1)))
    outputs: list[Output] = []
    for i, (src, name, dt) in enumerate(items):
        ctx.check()
        n = str(start + i).zfill(digits)
        new_stem = (
            pattern.replace("{n}", n)
            .replace("{nombre}", Path(name).stem)
            .replace("{fecha}", dt.strftime("%Y-%m-%d") if dt else "sin-fecha")
            .replace("{hora}", dt.strftime("%H%M%S") if dt else "000000")
        )
        out = unique(out_dir, safe_stem(new_stem), Path(name).suffix.lower())
        shutil.copyfile(src, out)
        outputs.append((out, f"{name} → {out.name}"))
        ctx.progress((i + 1) / len(items))
    return outputs


# --- IA: quitar fondo y ampliar ----------------------------------------------


def rembg_available() -> bool:
    try:
        import rembg  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


@lru_cache(maxsize=3)
def _rembg_session(model: str):
    import os

    os.environ.setdefault("U2NET_HOME", str(models_dir() / "rembg"))
    from rembg import new_session

    return new_session(model)


@register("image.remove_bg", available=rembg_available)
def remove_background(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    from rembg import remove

    model = choice(params.get("model"), ("u2net", "u2netp", "isnet-general-use"), "u2net")
    fmt = choice(params.get("format"), ("png", "webp"), "png")
    try:
        im = ImageOps.exif_transpose(_open(src, name)).convert("RGB")
        ctx.log(f"Quitando fondo de {name} con el modelo {model}…")
        cut = remove(im, session=_rembg_session(model))
        out = unique(out_dir, Path(name).stem, IMAGE_FORMATS[fmt])
        cut.save(out, format=PIL_FORMAT[fmt], **({"lossless": True} if fmt == "webp" else {"optimize": True}))
    except Exception as exc:  # noqa: BLE001
        raise _wrap(name, exc, src) from exc
    return out, f"{name} → {out.name} (fondo eliminado, {model})"


def _sr_model(scale: int) -> Path:
    return models_dir() / "fsrcnn" / f"FSRCNN_x{scale}.pb"


def upscale_available() -> bool:
    try:
        import cv2

        return hasattr(cv2, "dnn_superres") and _sr_model(2).exists()
    except Exception:  # noqa: BLE001
        return False


@register("image.upscale", available=upscale_available)
def upscale(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    import cv2
    import numpy as np

    scale = choice(clamp_int(params.get("scale"), 2, 4, 2), (2, 3, 4), 2)
    fmt = choice(params.get("format"), ("png", "webp", "jpeg"), "png")
    quality = clamp_int(params.get("quality"), 1, 100, 90)
    model = _sr_model(scale)
    if not model.exists():
        raise ProcessingError(f"Falta el modelo de ampliación x{scale} en este nodo")
    try:
        im = ImageOps.exif_transpose(_open(src, name))
        w, h = im.size
        if w * h * scale * scale > MAX_OUTPUT_PIXELS:
            raise ProcessingError(f"{name}: el resultado sería demasiado grande ({w * scale}x{h * scale})")
        alpha = im.getchannel("A") if "A" in im.getbands() else None
        rgb = np.array(im.convert("RGB"))[:, :, ::-1]
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(str(model))
        sr.setModel("fsrcnn", scale)
        ctx.log(f"Ampliando {name} x{scale} ({w}x{h})…")
        result = Image.fromarray(sr.upsample(rgb)[:, :, ::-1])
        if alpha is not None and fmt != "jpeg":
            result.putalpha(alpha.resize(result.size, Image.Resampling.LANCZOS))
        out = unique(out_dir, f"{Path(name).stem}_x{scale}", IMAGE_FORMATS[fmt])
        out.write_bytes(_encode(_prepare_mode(result, fmt), fmt, quality))
    except Exception as exc:  # noqa: BLE001
        raise _wrap(name, exc, src) from exc
    return out, f"{name} → {out.name} ({w}x{h} → {result.width}x{result.height})"

