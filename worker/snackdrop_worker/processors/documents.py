"""Documentos de oficina, archivos comprimidos y verificación de integridad."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from .common import Cancelled, Context, Output, ProcessingError, choice, clamp_int, fmt_size, run, safe_stem, unique, which
from .registry import register

MAX_EXTRACT_FILES = 10_000
MAX_EXTRACT_BYTES = 20 * 1024**3
MAX_RATIO = 200  # protección contra «zip bombs»
CHUNK = 1024 * 1024


# --- Office -> PDF -------------------------------------------------------------------


def soffice() -> str | None:
    return which("soffice", "libreoffice")


@register("doc.to_pdf", available=lambda: soffice() is not None)
def doc_to_pdf(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    exe = soffice()
    if not exe:
        raise ProcessingError("Este nodo no tiene LibreOffice")
    work = ctx.tmp_dir / f"office-{secrets.token_hex(4)}"
    (work / "profile").mkdir(parents=True, exist_ok=True)
    # LibreOffice decide el filtro por la extensión: se respeta la original.
    staged = work / f"documento{Path(name).suffix.lower()}"
    shutil.copyfile(src, staged)
    env = {**os.environ, "HOME": str(work)}
    try:
        run([exe, f"-env:UserInstallation=file://{(work / 'profile').as_posix()}", "--headless", "--norestore",
             "--nolockcheck", "--convert-to", "pdf", "--outdir", str(work), str(staged)], ctx, timeout=600, env=env)
        produced = work / "documento.pdf"
        if not produced.exists():
            raise ProcessingError(f"{name}: LibreOffice no pudo convertir el documento")
        out = unique(out_dir, Path(name).stem, ".pdf")
        shutil.move(produced, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out, f"{name} → {out.name} ({fmt_size(out.stat().st_size)})"


# --- Comprimir ---------------------------------------------------------------------


@register("archive.zip", mode="batch")
def make_archive(files: list[tuple[Path, str]], out_dir: Path, params: dict, ctx: Context) -> list[Output]:
    fmt = choice(params.get("format"), ("zip", "7z"), "zip")
    level = choice(params.get("level"), ("store", "normal", "max"), "normal")
    password = str(params.get("password") or "")
    stem = safe_stem(str(params.get("output_name") or "archivos"))
    out = unique(out_dir, stem, f".{fmt}")
    used: set[str] = set()

    def arcname(name: str) -> str:
        base, n = name, 1
        while name in used:
            p = PurePosixPath(base)
            name = f"{p.stem} ({n}){p.suffix}"
            n += 1
        used.add(name)
        return name

    total = len(files)
    if fmt == "zip":
        if password:
            raise ProcessingError("Las contraseñas solo están disponibles en formato 7z")
        compression = zipfile.ZIP_STORED if level == "store" else zipfile.ZIP_DEFLATED
        complevel = {"store": None, "normal": 6, "max": 9}[level]
        with zipfile.ZipFile(out, "w", compression=compression, compresslevel=complevel, allowZip64=True) as zf:
            for i, (src, name) in enumerate(files):
                ctx.check()
                zf.write(src, arcname=arcname(name))
                ctx.progress((i + 1) / total)
    else:
        import py7zr

        filters = None if level != "store" else [{"id": py7zr.FILTER_COPY}]
        if level == "max":
            filters = [{"id": py7zr.FILTER_LZMA2, "preset": 9}]
        with py7zr.SevenZipFile(out, "w", password=password or None, filters=filters,
                                header_encryption=bool(password)) as zf:
            for i, (src, name) in enumerate(files):
                ctx.check()
                zf.write(src, arcname=arcname(name))
                ctx.progress((i + 1) / total)
    before = sum(src.stat().st_size for src, _ in files)
    extra = ", con contraseña" if password else ""
    return [(out, f"{total} archivo(s) → {out.name} ({fmt_size(before)} → {fmt_size(out.stat().st_size)}{extra})")]


# --- Descomprimir ------------------------------------------------------------------


def _flat_name(member: str) -> str | None:
    """«fotos/2024/a.jpg» → «fotos - 2024 - a.jpg». Descarta rutas absolutas, «..» y entradas vacías."""
    parts = [p for p in PurePosixPath(member.replace("\\", "/")).parts if p not in ("", ".", "/")]
    if not parts or any(p == ".." for p in parts) or member.startswith("/"):
        return None
    if parts[0].startswith("__MACOSX") or parts[-1] in (".DS_Store", "Thumbs.db"):
        return None
    return " - ".join(safe_stem(p, "x") for p in parts)


class _Budget:
    def __init__(self, archive_size: int):
        self.limit = min(MAX_EXTRACT_BYTES, max(archive_size, 1) * MAX_RATIO + 50 * 1024**2)
        self.used = 0
        self.files = 0

    def add_file(self):
        self.files += 1
        if self.files > MAX_EXTRACT_FILES:
            raise ProcessingError(f"El archivo comprimido tiene más de {MAX_EXTRACT_FILES} archivos")

    def add_bytes(self, n: int):
        self.used += n
        if self.used > self.limit:
            raise ProcessingError("El contenido descomprimido es sospechosamente grande; se detuvo la extracción")


def _copy_stream(fh, out: Path, budget: _Budget, ctx: Context) -> None:
    try:
        with out.open("wb") as dst:
            while chunk := fh.read(CHUNK):
                budget.add_bytes(len(chunk))
                dst.write(chunk)
                ctx.check()
    except BaseException:
        out.unlink(missing_ok=True)  # no dejar archivos a medias
        raise


@register("archive.extract")
def extract(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> list[Output]:
    lower = name.lower()
    password = str(params.get("password") or "")
    budget = _Budget(src.stat().st_size)
    outputs: list[Output] = []

    def emit(member_name: str) -> Path | None:
        flat = _flat_name(member_name)
        if flat is None:
            return None
        budget.add_file()
        p = PurePosixPath(flat)
        return unique(out_dir, p.stem if p.suffix else flat, p.suffix.lower() if p.suffix else "")

    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(src) as zf:
                if password:
                    zf.setpassword(password.encode())
                infos = [i for i in zf.infolist() if not i.is_dir()]
                for n, info in enumerate(infos):
                    ctx.check()
                    is_link = (info.external_attr >> 16) & 0o170000 == 0o120000
                    out = None if is_link else emit(info.filename)
                    if out is None:
                        continue
                    try:
                        with zf.open(info) as fh:
                            _copy_stream(fh, out, budget, ctx)
                    except RuntimeError as exc:
                        out.unlink(missing_ok=True)
                        raise ProcessingError(f"{name}: está protegido; indica la contraseña correcta") from exc
                    outputs.append((out, f"{info.filename} → {out.name}"))
                    ctx.progress((n + 1) / len(infos))
        elif lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
            with tarfile.open(src) as tf:
                members = [m for m in tf.getmembers() if m.isfile()]  # sin enlaces ni dispositivos
                for n, member in enumerate(members):
                    ctx.check()
                    out = emit(member.name)
                    if out is None:
                        continue
                    fh = tf.extractfile(member)
                    if fh is None:
                        continue
                    _copy_stream(fh, out, budget, ctx)
                    outputs.append((out, f"{member.name} → {out.name}"))
                    ctx.progress((n + 1) / len(members))
        elif lower.endswith(".7z"):
            import py7zr

            work = ctx.tmp_dir / f"7z-{secrets.token_hex(4)}"
            try:
                with py7zr.SevenZipFile(src, "r", password=password or None) as zf:
                    entries = [e for e in zf.list() if not e.is_directory]
                    if len(entries) > MAX_EXTRACT_FILES:
                        raise ProcessingError(f"El archivo comprimido tiene más de {MAX_EXTRACT_FILES} archivos")
                    declared = sum(e.uncompressed or 0 for e in entries)
                    budget.add_bytes(declared)
                    safe = [e.filename for e in entries if _flat_name(e.filename)]
                    zf.extract(path=work, targets=safe)
                for n, path in enumerate(sorted(p for p in work.rglob("*") if p.is_file() and not p.is_symlink())):
                    ctx.check()
                    rel = path.relative_to(work).as_posix()
                    out = emit(rel)
                    if out is None:
                        continue
                    shutil.move(path, out)
                    outputs.append((out, f"{rel} → {out.name}"))
                    ctx.progress((n + 1) / max(1, len(safe)))
            except py7zr.exceptions.PasswordRequired as exc:
                raise ProcessingError(f"{name}: está protegido; indica la contraseña") from exc
            finally:
                shutil.rmtree(work, ignore_errors=True)
        else:
            raise ProcessingError(f"{name}: formato no soportado (usa .zip, .7z o .tar)")
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise ProcessingError(f"{name}: el archivo comprimido está dañado") from exc
    except (ProcessingError, Cancelled):
        for out, _ in outputs:
            out.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - p. ej. contraseña incorrecta en 7z
        raise ProcessingError(f"{name}: no se pudo descomprimir ({exc})") from exc
    if not outputs:
        raise ProcessingError(f"{name}: no contiene archivos")
    return outputs


# --- Hash ---------------------------------------------------------------------------


@register("file.hash", mode="batch")
def hash_files(files: list[tuple[Path, str]], out_dir: Path, params: dict, ctx: Context) -> list[Output]:
    algorithm = choice(params.get("algorithm"), ("sha256", "sha512", "sha1", "md5"), "sha256")
    lines = []
    for i, (src, name) in enumerate(files):
        h = hashlib.new(algorithm)
        with src.open("rb") as fh:
            while chunk := fh.read(CHUNK):
                h.update(chunk)
                ctx.check()
        lines.append(f"{h.hexdigest()}  {name}")
        ctx.log(f"{algorithm} {name}: {h.hexdigest()}")
        ctx.progress((i + 1) / len(files))
    out = unique(out_dir, safe_stem(str(params.get("output_name") or "checksums")), f".{algorithm}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [(out, f"{len(files)} hash(es) {algorithm} → {out.name}")]
