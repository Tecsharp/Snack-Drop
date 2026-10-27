"""Operaciones de PDF."""

from __future__ import annotations

import math
import os
import secrets
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

from .common import (
    Context,
    Output,
    ProcessingError,
    choice,
    clamp_float,
    clamp_int,
    fmt_size,
    pages_from_spec,
    parse_ranges,
    run,
    safe_stem,
    unique,
    which,
)
from .registry import register

PDF_LEVELS = {"low": "/printer", "medium": "/ebook", "high": "/screen"}


def _pikepdf():
    try:
        import pikepdf

        return pikepdf
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ProcessingError("pikepdf no está instalado en este nodo") from exc


def _check_pdf(src: Path, name: str) -> None:
    with src.open("rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        raise ProcessingError(f"{name}: no es un PDF válido")


def _open_pdf(src: Path, name: str, password: str = ""):
    pikepdf = _pikepdf()
    _check_pdf(src, name)
    try:
        return pikepdf.open(src, password=password)
    except pikepdf.PasswordError as exc:
        raise ProcessingError(
            f"{name}: la contraseña no es correcta" if password else f"{name}: el PDF está protegido con contraseña"
        ) from exc
    except pikepdf.PdfError as exc:
        raise ProcessingError(f"{name}: el PDF está dañado ({exc})") from exc


def ghostscript() -> str | None:
    return which("gs", "gswin64c", "gswin32c")


# --- Comprimir -----------------------------------------------------------------


@register("pdf.compress")
def compress_pdf(src: Path, out_dir: Path, original_name: str, params: dict, ctx: Context | None = None) -> Output:
    level = params.get("level", "medium")
    if level not in PDF_LEVELS:
        raise ProcessingError(f"Nivel no soportado: {level}")
    grayscale = bool(params.get("grayscale"))
    with src.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise ProcessingError(f"{original_name} no es un PDF válido")
    ctx = ctx or Context()

    out = unique(out_dir, Path(original_name).stem or "documento", ".pdf")
    gs = ghostscript()
    engine = "ghostscript"
    if gs:
        cmd = [gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5", f"-dPDFSETTINGS={PDF_LEVELS[level]}",
               "-dSAFER", "-dNOPAUSE", "-dQUIET", "-dBATCH"]
        if grayscale:
            cmd += ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray"]
        cmd += [f"-sOutputFile={out}", str(src)]
        try:
            run(cmd, ctx, timeout=1800)
        except ProcessingError as exc:
            out.unlink(missing_ok=True)
            raise ProcessingError(f"Ghostscript falló con {original_name}: {exc}") from exc
    else:
        pikepdf = _pikepdf()
        engine = "pikepdf"
        try:
            with pikepdf.open(src) as pdf:
                pdf.remove_unreferenced_resources()
                pdf.save(out, compress_streams=True, recompress_flate=True,
                         object_stream_mode=pikepdf.ObjectStreamMode.generate)
        except pikepdf.PdfError as exc:
            out.unlink(missing_ok=True)
            raise ProcessingError(f"No se pudo procesar {original_name}: {exc}") from exc

    before, after = src.stat().st_size, out.stat().st_size
    if after >= before:
        shutil.copyfile(src, out)
        return out, f"{original_name}: ya estaba optimizado ({fmt_size(before)}), se conserva el original"
    saved = 100 - after * 100 / before
    return out, f"{original_name}: {fmt_size(before)} → {fmt_size(after)} (-{saved:.0f}%, {engine})"


# --- Unir / separar --------------------------------------------------------------


@register("pdf.merge", mode="batch")
def merge(files: list[tuple[Path, str]], out_dir: Path, params: dict, ctx: Context) -> list[Output]:
    pikepdf = _pikepdf()
    if len(files) < 2:
        raise ProcessingError("Agrega al menos dos PDFs para unirlos")
    order = choice(params.get("sort"), ("upload", "name"), "upload")
    items = sorted(files, key=lambda f: f[1].lower()) if order == "name" else list(files)
    merged = pikepdf.new()
    pages = 0
    for i, (src, name) in enumerate(items):
        ctx.check()
        with _open_pdf(src, name) as pdf:
            merged.pages.extend(pdf.pages)
            pages += len(pdf.pages)
        ctx.progress((i + 1) / len(items) * 0.9)
    out = unique(out_dir, safe_stem(str(params.get("output_name") or "combinado")), ".pdf")
    merged.save(out)
    return [(out, f"{len(items)} PDFs unidos en {out.name} ({pages} páginas, {fmt_size(out.stat().st_size)})")]


@register("pdf.split")
def split(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> list[Output]:
    pikepdf = _pikepdf()
    mode = choice(params.get("mode"), ("each_page", "ranges"), "each_page")
    stem = Path(name).stem
    outputs: list[Output] = []
    with _open_pdf(src, name) as pdf:
        total = len(pdf.pages)
        groups = [[i] for i in range(total)] if mode == "each_page" else parse_ranges(str(params.get("ranges") or ""), total)
        if len(groups) > 2000:
            raise ProcessingError(f"{name}: demasiadas partes ({len(groups)})")
        digits = len(str(total))
        for gi, group in enumerate(groups):
            ctx.check()
            part = pikepdf.new()
            part.pages.extend(pdf.pages[p] for p in group)
            first, last = group[0] + 1, group[-1] + 1
            label = f"p{str(first).zfill(digits)}" if first == last else f"p{first}-{last}"
            out = unique(out_dir, f"{stem}_{label}", ".pdf")
            part.save(out)
            outputs.append((out, f"{name} → {out.name} ({len(group)} pág.)"))
            ctx.progress((gi + 1) / len(groups))
    return outputs


# --- Imágenes <-> PDF --------------------------------------------------------------

PAGE_SIZES_MM = {"a4": (210, 297), "letter": (215.9, 279.4)}


@register("pdf.from_images", mode="batch")
def from_images(files: list[tuple[Path, str]], out_dir: Path, params: dict, ctx: Context) -> list[Output]:
    import img2pdf

    page = choice(params.get("page_size"), ("original", "a4", "letter"), "original")
    margin = clamp_int(params.get("margin_mm"), 0, 50, 0)
    order = choice(params.get("sort"), ("upload", "name"), "upload")
    items = sorted(files, key=lambda f: f[1].lower()) if order == "name" else list(files)
    prepared: list[str] = []
    tmp = ctx.tmp_dir / f"img2pdf-{secrets.token_hex(4)}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        for i, (src, name) in enumerate(items):
            ctx.check()
            try:
                with Image.open(src) as im:
                    fmt = im.format
                    needs_convert = fmt not in ("JPEG", "PNG") or "A" in im.getbands() or im.mode in ("P", "LA", "I;16")
                    if needs_convert or im.getexif().get(274, 1) not in (1, None):
                        im = ImageOps.exif_transpose(im)
                        if "A" in im.getbands() or im.mode == "P":
                            rgba = im.convert("RGBA")
                            bg = Image.new("RGB", rgba.size, (255, 255, 255))
                            bg.paste(rgba, mask=rgba.getchannel("A"))
                            im = bg
                        elif im.mode not in ("RGB", "L"):
                            im = im.convert("RGB")
                        target = tmp / f"{i:05d}.jpg"
                        im.save(target, format="JPEG", quality=92)
                        prepared.append(str(target))
                    else:
                        prepared.append(str(src))
            except Exception as exc:  # noqa: BLE001
                raise ProcessingError(f"{name}: no es una imagen válida o está dañada") from exc
            ctx.progress((i + 1) / len(items) * 0.7)
        kwargs = {}
        if page != "original":
            w, h = PAGE_SIZES_MM[page]
            mm = img2pdf.mm_to_pt
            kwargs["layout_fun"] = img2pdf.get_layout_fun(
                (mm(w), mm(h)), border=(mm(margin), mm(margin)) if margin else None, fit=img2pdf.FitMode.into,
                auto_orient=True,
            )
        out = unique(out_dir, safe_stem(str(params.get("output_name") or "imagenes")), ".pdf")
        out.write_bytes(img2pdf.convert(prepared, rotation=img2pdf.Rotation.ifvalid, **kwargs))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return [(out, f"{len(items)} imágenes → {out.name} ({fmt_size(out.stat().st_size)}, página {page})")]


@register("pdf.to_images")
def to_images(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> list[Output]:
    import pypdfium2 as pdfium

    dpi = clamp_int(params.get("dpi"), 36, 600, 150)
    fmt = choice(params.get("format"), ("png", "jpeg", "webp"), "png")
    quality = clamp_int(params.get("quality"), 1, 100, 90)
    _check_pdf(src, name)
    try:
        doc = pdfium.PdfDocument(str(src))
    except pdfium.PdfiumError as exc:
        raise ProcessingError(f"{name}: no se pudo abrir el PDF (¿protegido o dañado?)") from exc
    outputs: list[Output] = []
    try:
        pages = pages_from_spec(params.get("pages"), len(doc))
        if len(pages) > 2000:
            raise ProcessingError(f"{name}: demasiadas páginas ({len(pages)})")
        digits = len(str(len(doc)))
        ext = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[fmt]
        for i, p in enumerate(pages):
            ctx.check()
            image = doc[p].render(scale=dpi / 72).to_pil()
            out = unique(out_dir, f"{Path(name).stem}_p{str(p + 1).zfill(digits)}", ext)
            if fmt == "png":
                image.save(out, format="PNG", optimize=True)
            else:
                image.convert("RGB").save(out, format=fmt.upper(), quality=quality)
            outputs.append((out, f"{name} página {p + 1} → {out.name} ({image.width}x{image.height})"))
            ctx.progress((i + 1) / len(pages))
    finally:
        doc.close()
    return outputs


# --- Rotar / proteger / desbloquear ---------------------------------------------------


@register("pdf.rotate")
def rotate(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    angle = choice(clamp_int(params.get("angle"), 90, 270, 90), (90, 180, 270), 90)
    with _open_pdf(src, name) as pdf:
        pages = pages_from_spec(params.get("pages"), len(pdf.pages))
        for p in pages:
            pdf.pages[p].rotate(angle, relative=True)
        out = unique(out_dir, Path(name).stem, ".pdf")
        pdf.save(out)
    return out, f"{name}: {len(pages)} página(s) rotadas {angle}°"


@register("pdf.protect")
def protect(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    pikepdf = _pikepdf()
    user = str(params.get("password") or "")
    if len(user) < 4:
        raise ProcessingError("La contraseña debe tener al menos 4 caracteres")
    owner = str(params.get("owner_password") or "") or secrets.token_urlsafe(24)
    allow = pikepdf.Permissions(
        print_lowres=bool(params.get("allow_print", True)),
        print_highres=bool(params.get("allow_print", True)),
        extract=bool(params.get("allow_copy", False)),
        modify_other=bool(params.get("allow_modify", False)),
        modify_annotation=bool(params.get("allow_modify", False)),
        modify_form=bool(params.get("allow_modify", False)),
        modify_assembly=bool(params.get("allow_modify", False)),
    )
    with _open_pdf(src, name) as pdf:
        out = unique(out_dir, Path(name).stem, ".pdf")
        pdf.save(out, encryption=pikepdf.Encryption(user=user, owner=owner, R=6, allow=allow))
    return out, f"{name}: protegido con contraseña (AES-256)"


@register("pdf.unlock")
def unlock(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    password = str(params.get("password") or "")
    with _open_pdf(src, name, password) as pdf:
        if not pdf.is_encrypted and not password:
            raise ProcessingError(f"{name}: el PDF no tiene contraseña")
        out = unique(out_dir, Path(name).stem, ".pdf")
        pdf.save(out)
    return out, f"{name}: contraseña eliminada"


# --- OCR -------------------------------------------------------------------------


def _ocrmypdf_cmd() -> list[str] | None:
    if not which("tesseract") or not ghostscript():
        return None
    try:
        import ocrmypdf  # noqa: F401

        return [sys.executable, "-m", "ocrmypdf"]
    except ImportError:
        path = which("ocrmypdf")
        return [path] if path else None


@register("pdf.ocr", available=lambda: _ocrmypdf_cmd() is not None)
def ocr(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    cmd = _ocrmypdf_cmd()
    if cmd is None:
        raise ProcessingError("Este nodo no tiene Tesseract/OCRmyPDF")
    language = choice(params.get("language"), ("spa", "eng", "spa+eng"), "spa+eng")
    mode = choice(params.get("mode"), ("skip", "redo", "force"), "skip")
    _check_pdf(src, name)
    out = unique(out_dir, Path(name).stem, ".pdf")
    flags = {"skip": "--skip-text", "redo": "--redo-ocr", "force": "--force-ocr"}[mode]
    jobs = str(max(1, min(8, os.cpu_count() or 1)))
    ctx.log(f"OCR de {name} ({language})…")
    try:
        run([*cmd, "-l", language, flags, "--optimize", "1", "--jobs", jobs, "--output-type", "pdf", str(src), str(out)],
            ctx, timeout=7200)
    except ProcessingError as exc:
        out.unlink(missing_ok=True)
        if "PriorOcrFoundError" in str(exc) or "page already has text" in str(exc):
            raise ProcessingError(f"{name}: ya tiene texto; usa el modo «rehacer» o «forzar»") from exc
        raise ProcessingError(f"{name}: OCR falló ({exc})") from exc
    return out, f"{name}: OCR aplicado ({language}), ahora se puede buscar y copiar texto"


# --- Marca de agua -----------------------------------------------------------------

PDF_COLORS = {"gray": (0.5, 0.5, 0.5), "red": (0.85, 0.15, 0.15), "black": (0, 0, 0), "blue": (0.15, 0.3, 0.8)}


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


@register("pdf.watermark")
def pdf_watermark(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    pikepdf = _pikepdf()
    from pikepdf import Dictionary, Name

    text = str(params.get("text") or "").strip()[:80]
    if not text:
        raise ProcessingError("Escribe el texto de la marca de agua")
    opacity = clamp_int(params.get("opacity"), 5, 100, 25) / 100
    size = clamp_int(params.get("size"), 8, 200, 60)
    angle = clamp_float(params.get("angle"), 0, 90, 45)
    r, g, b = PDF_COLORS.get(params.get("color"), PDF_COLORS["gray"])
    position = choice(params.get("position"), ("center", "top", "bottom"), "center")
    with _open_pdf(src, name) as pdf:
        overlays: dict[tuple[float, float], object] = {}
        stamp = pikepdf.new()
        for i, page in enumerate(pdf.pages):
            ctx.check()
            box = [float(v) for v in page.mediabox]
            w, h = box[2] - box[0], box[3] - box[1]
            key = (round(w, 1), round(h, 1))
            if key not in overlays:
                stamp.add_blank_page(page_size=(w, h))
                sp = stamp.pages[-1]
                font = stamp.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                                      BaseFont=Name("/Helvetica-Bold"), Encoding=Name.WinAnsiEncoding))
                sp.Resources = Dictionary(Font=Dictionary(F1=font),
                                          ExtGState=Dictionary(GS1=Dictionary(Type=Name.ExtGState, ca=opacity, CA=opacity)))
                rad = math.radians(angle)
                cos, sin = math.cos(rad), math.sin(rad)
                tw, th = 0.58 * size * len(text), size * 0.7
                cy = {"center": h / 2, "top": h - size * 1.5, "bottom": size * 1.5}[position]
                cx = w / 2
                x = cx - cos * tw / 2 + sin * th / 2
                y = cy - sin * tw / 2 - cos * th / 2
                content = (f"q /GS1 gs {r} {g} {b} rg BT /F1 {size} Tf "
                           f"{cos:.4f} {sin:.4f} {-sin:.4f} {cos:.4f} {x:.2f} {y:.2f} Tm (").encode() + _pdf_string(text) + b") Tj ET Q"
                sp.Contents = stamp.make_stream(content)
                overlays[key] = sp
            page.add_overlay(overlays[key])
            ctx.progress((i + 1) / len(pdf.pages))
        n_pages = len(pdf.pages)
        out = unique(out_dir, Path(name).stem, ".pdf")
        pdf.save(out)
    return out, f"{name}: marca «{text}» en {n_pages} página(s)"
