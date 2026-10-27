"""Catálogo seguro de operaciones.

Solo estas operaciones existen. Ningún usuario, asistente o nodo puede pedir
comandos arbitrarios: todo trabajo se valida contra estos modelos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif"}
HEIC_EXTENSIONS = {".heic", ".heif"}
PDF_EXTENSIONS = {".pdf"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".ts", ".3gp", ".mts"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf", ".txt", ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}
ANY = frozenset({"*"})


def _plain_text(value: str) -> str:
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        raise ValueError("no puede contener caracteres de control")
    return value


def _file_stem(value: str) -> str:
    value = _plain_text(value)
    if re.search(r'[<>:"/\\|?*]', value) or value.startswith("."):
        raise ValueError("no puede contener / \\ : * ? \" < > |")
    return value


def _page_spec(value: str) -> str:
    value = value.strip().lower()
    if value in ("", "todas", "all"):
        return ""
    if not re.fullmatch(r"\d+(\s*-\s*\d*)?(\s*,\s*\d+(\s*-\s*\d*)?)*", value):
        raise ValueError("usa el formato 1-3,7,10-")
    return value


Text = Annotated[str, AfterValidator(_plain_text)]
FileStem = Annotated[str, AfterValidator(_file_stem)]
PageSpec = Annotated[str, AfterValidator(_page_spec)]


def labels(**mapping: str) -> dict:
    return {"labels": mapping}


SECRET = {"format": "password", "secret": True}


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Imágenes ------------------------------------------------------------------------

QUALITY = Field(80, ge=1, le=100, title="Calidad", description="75–85 es ideal para fotos")
MAX_W = Field(None, ge=16, le=16384, title="Ancho máximo (px)", json_schema_extra={"placeholder": "Original"})
MAX_H = Field(None, ge=16, le=16384, title="Alto máximo (px)", json_schema_extra={"placeholder": "Original"})
STRIP = Field(True, title="Quitar metadatos (EXIF/GPS)")
OUT_FORMAT = Field("same", title="Formato de salida",
                   json_schema_extra=labels(same="Igual que el original", webp="WebP", jpeg="JPEG", png="PNG"))


class ImageConvertParams(Params):
    format: Literal["webp", "jpeg", "png", "avif"] = Field(
        "webp", title="Formato", json_schema_extra=labels(webp="WebP", jpeg="JPEG", png="PNG", avif="AVIF"))
    quality: int = QUALITY
    max_width: int | None = MAX_W
    max_height: int | None = MAX_H
    lossless: bool = Field(False, title="Sin pérdida (solo WebP)")
    strip_metadata: bool = STRIP
    never_larger: bool = Field(True, title="Nunca más grande que el original")


class HeicParams(Params):
    format: Literal["jpeg", "webp", "png"] = Field("jpeg", title="Formato", json_schema_extra=labels(jpeg="JPEG", webp="WebP", png="PNG"))
    quality: int = Field(88, ge=1, le=100, title="Calidad")
    max_width: int | None = MAX_W
    max_height: int | None = MAX_H
    strip_metadata: bool = STRIP
    never_larger: bool = Field(False, title="Nunca más grande que el original",
                               description="HEIC comprime mucho; un JPEG casi siempre pesa más")


class AvifParams(Params):
    quality: int = Field(60, ge=1, le=100, title="Calidad", description="AVIF se ve bien desde 50–65")
    max_width: int | None = MAX_W
    max_height: int | None = MAX_H
    strip_metadata: bool = STRIP
    never_larger: bool = Field(True, title="Nunca más grande que el original")


class WatermarkParams(Params):
    text: Text = Field(..., min_length=1, max_length=100, title="Texto", json_schema_extra={"placeholder": "© Tu nombre 2026"})
    position: Literal["bottom-right", "bottom-left", "top-right", "top-left", "center", "tiled"] = Field(
        "bottom-right", title="Posición",
        json_schema_extra=labels(**{"bottom-right": "Abajo a la derecha", "bottom-left": "Abajo a la izquierda",
                                    "top-right": "Arriba a la derecha", "top-left": "Arriba a la izquierda",
                                    "center": "Centro", "tiled": "Mosaico (toda la imagen)"}))
    opacity: int = Field(50, ge=5, le=100, title="Opacidad (%)")
    size: int = Field(6, ge=2, le=30, title="Tamaño (% del lado menor)")
    color: Literal["white", "black", "gray", "red"] = Field(
        "white", title="Color", json_schema_extra=labels(white="Blanco", black="Negro", gray="Gris", red="Rojo"))
    format: Literal["same", "webp", "jpeg", "png"] = OUT_FORMAT
    quality: int = Field(85, ge=1, le=100, title="Calidad")


class CropParams(Params):
    aspect: Literal["1:1", "4:5", "5:4", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"] = Field(
        "1:1", title="Proporción",
        json_schema_extra=labels(**{"1:1": "1:1 cuadrado", "4:5": "4:5 Instagram vertical", "5:4": "5:4",
                                    "4:3": "4:3", "3:4": "3:4", "3:2": "3:2", "2:3": "2:3",
                                    "16:9": "16:9 panorámico", "9:16": "9:16 historias"}))
    mode: Literal["smart", "center"] = Field("smart", title="Encuadre",
                                             json_schema_extra=labels(smart="Inteligente (zona con más detalle)", center="Centrado"))
    format: Literal["same", "webp", "jpeg", "png"] = OUT_FORMAT
    quality: int = Field(85, ge=1, le=100, title="Calidad")


class NoParams(Params):
    pass


class RenameParams(Params):
    pattern: Text = Field("{fecha}_{n}", min_length=1, max_length=120, title="Patrón",
                          description="Usa {n} número, {nombre} nombre original, {fecha} y {hora} de la foto")
    sort: Literal["date", "name", "upload"] = Field(
        "date", title="Orden", json_schema_extra=labels(date="Fecha de la foto", name="Nombre", upload="Orden de subida"))
    start: int = Field(1, ge=0, le=1_000_000, title="Empezar en")


class RemoveBgParams(Params):
    model: Literal["u2net", "u2netp", "isnet-general-use"] = Field(
        "u2net", title="Modelo",
        json_schema_extra=labels(u2net="General (recomendado)", u2netp="Rápido (menos preciso)", **{"isnet-general-use": "Alta precisión"}))
    format: Literal["png", "webp"] = Field("png", title="Formato", json_schema_extra=labels(png="PNG", webp="WebP sin pérdida"))


class UpscaleParams(Params):
    scale: Literal[2, 3, 4] = Field(2, title="Aumento", json_schema_extra={"labels": {"2": "x2", "3": "x3", "4": "x4"}})
    format: Literal["png", "webp", "jpeg"] = Field("png", title="Formato", json_schema_extra=labels(png="PNG", webp="WebP", jpeg="JPEG"))
    quality: int = Field(90, ge=1, le=100, title="Calidad (WebP/JPEG)")


# --- PDF ------------------------------------------------------------------------------

PAGES = Field("", max_length=200, title="Páginas", description="Vacío = todas. Ej.: 1-3,7,10-",
              json_schema_extra={"placeholder": "Todas"})
ORDER = Field("upload", title="Orden", json_schema_extra=labels(upload="Orden de subida", name="Nombre de archivo"))


class PdfCompressParams(Params):
    level: Literal["low", "medium", "high"] = Field(
        "medium", title="Nivel de compresión",
        json_schema_extra=labels(low="Ligera (calidad de impresión)", medium="Media (lectura en pantalla)", high="Máxima (archivo más pequeño)"))
    grayscale: bool = Field(False, title="Escala de grises")


class PdfMergeParams(Params):
    sort: Literal["upload", "name"] = ORDER
    output_name: FileStem = Field("combinado", min_length=1, max_length=100, title="Nombre del PDF")


class PdfSplitParams(Params):
    mode: Literal["each_page", "ranges"] = Field(
        "each_page", title="Separar", json_schema_extra=labels(each_page="Una página por archivo", ranges="Por rangos"))
    ranges: PageSpec = Field("", max_length=200, title="Rangos", description="Cada rango es un PDF. Ej.: 1-3,4-6,7-",
                             json_schema_extra={"placeholder": "1-3,4-6"})


class PdfFromImagesParams(Params):
    page_size: Literal["original", "a4", "letter"] = Field(
        "original", title="Tamaño de página", json_schema_extra=labels(original="Tamaño de la imagen", a4="A4", letter="Carta"))
    margin_mm: int = Field(0, ge=0, le=50, title="Margen (mm)")
    sort: Literal["upload", "name"] = ORDER
    output_name: FileStem = Field("imagenes", min_length=1, max_length=100, title="Nombre del PDF")


class PdfToImagesParams(Params):
    format: Literal["png", "jpeg", "webp"] = Field("png", title="Formato", json_schema_extra=labels(png="PNG", jpeg="JPEG", webp="WebP"))
    dpi: int = Field(150, ge=36, le=600, title="Resolución (DPI)", description="150 pantalla · 300 impresión")
    quality: int = Field(90, ge=1, le=100, title="Calidad (JPEG/WebP)")
    pages: PageSpec = PAGES


class PdfRotateParams(Params):
    angle: Literal[90, 180, 270] = Field(90, title="Giro", json_schema_extra={"labels": {"90": "90° derecha", "180": "180°", "270": "90° izquierda"}})
    pages: PageSpec = PAGES


class PdfProtectParams(Params):
    password: str = Field(..., min_length=4, max_length=128, title="Contraseña para abrir", json_schema_extra=SECRET)
    owner_password: str = Field("", max_length=128, title="Contraseña de propietario (opcional)",
                                description="Si la dejas vacía se genera una aleatoria", json_schema_extra=SECRET)
    allow_print: bool = Field(True, title="Permitir imprimir")
    allow_copy: bool = Field(False, title="Permitir copiar texto")
    allow_modify: bool = Field(False, title="Permitir modificar")


class PdfUnlockParams(Params):
    password: str = Field(..., min_length=1, max_length=128, title="Contraseña actual", json_schema_extra=SECRET)


class PdfOcrParams(Params):
    language: Literal["spa+eng", "spa", "eng"] = Field(
        "spa+eng", title="Idioma", json_schema_extra=labels(**{"spa+eng": "Español + inglés", "spa": "Español", "eng": "Inglés"}))
    mode: Literal["skip", "redo", "force"] = Field(
        "skip", title="Si ya tiene texto",
        json_schema_extra=labels(skip="Saltar esas páginas", redo="Rehacer OCR", force="Forzar (rasteriza todo)"))


class PdfWatermarkParams(Params):
    text: Text = Field(..., min_length=1, max_length=80, title="Texto", json_schema_extra={"placeholder": "CONFIDENCIAL"})
    opacity: int = Field(25, ge=5, le=100, title="Opacidad (%)")
    size: int = Field(60, ge=8, le=200, title="Tamaño de letra (pt)")
    angle: int = Field(45, ge=0, le=90, title="Ángulo (°)")
    color: Literal["gray", "red", "black", "blue"] = Field(
        "gray", title="Color", json_schema_extra=labels(gray="Gris", red="Rojo", black="Negro", blue="Azul"))
    position: Literal["center", "top", "bottom"] = Field(
        "center", title="Posición", json_schema_extra=labels(center="Centro", top="Arriba", bottom="Abajo"))


# --- Video y audio --------------------------------------------------------------------

HARDWARE = Field("auto", title="Aceleración por GPU",
                 json_schema_extra=labels(auto="Usar GPU si el nodo tiene (NVENC/VideoToolbox)", off="Solo CPU"))
HEIGHT_LABELS = {"2160": "4K (2160p)", "1440": "1440p", "1080": "1080p", "720": "720p", "480": "480p", "360": "360p"}
AUDIO_FORMAT_LABELS = labels(mp3="MP3", aac="AAC (.m4a)", opus="Opus", ogg="Ogg Vorbis", flac="FLAC (sin pérdida)", wav="WAV (sin pérdida)")


class VideoCompressParams(Params):
    codec: Literal["h264", "h265"] = Field("h264", title="Códec",
                                           json_schema_extra=labels(h264="H.264 (compatible)", h265="H.265/HEVC (≈40% más ligero)"))
    crf: int = Field(26, ge=16, le=40, title="Compresión (CRF)", description="Menor = mejor calidad. 23–28 recomendado")
    preset: Literal["veryfast", "fast", "medium", "slow", "veryslow"] = Field(
        "medium", title="Velocidad",
        json_schema_extra=labels(veryfast="Muy rápida", fast="Rápida", medium="Normal", slow="Lenta (más ligero)", veryslow="Muy lenta"))
    max_height: Literal[2160, 1440, 1080, 720, 480, 360] | None = Field(
        None, title="Resolución máxima", json_schema_extra={"labels": HEIGHT_LABELS, "placeholder": "Original"})
    audio_bitrate: int = Field(128, ge=32, le=512, title="Audio (kbps)")
    hardware: Literal["auto", "off"] = HARDWARE
    never_larger: bool = Field(True, title="Nunca más grande que el original")


class VideoConvertParams(Params):
    container: Literal["mp4", "mkv", "webm", "mov"] = Field(
        "mp4", title="Formato", json_schema_extra=labels(mp4="MP4 (compatible)", mkv="MKV", webm="WebM (web)", mov="MOV"))
    mode: Literal["auto", "reencode"] = Field(
        "auto", title="Modo", json_schema_extra=labels(auto="Sin recodificar si se puede (rápido)", reencode="Siempre recodificar"))
    hardware: Literal["auto", "off"] = HARDWARE


class VideoResizeParams(Params):
    height: Literal[2160, 1440, 1080, 720, 480, 360] = Field(1080, title="Resolución", json_schema_extra={"labels": HEIGHT_LABELS})
    crf: int = Field(23, ge=16, le=40, title="Calidad (CRF)", description="Menor = mejor calidad")
    hardware: Literal["auto", "off"] = HARDWARE


class ExtractAudioParams(Params):
    format: Literal["mp3", "aac", "opus", "ogg", "flac", "wav"] = Field("mp3", title="Formato", json_schema_extra=AUDIO_FORMAT_LABELS)
    bitrate: int = Field(192, ge=32, le=512, title="Calidad (kbps)")


class GifParams(Params):
    start: float = Field(0, ge=0, le=86_400, title="Inicio (segundos)")
    duration: float = Field(5, ge=0.5, le=60, title="Duración (segundos)")
    fps: int = Field(12, ge=5, le=30, title="Cuadros por segundo")
    width: int = Field(480, ge=120, le=1280, title="Ancho (px)")
    format: Literal["gif", "webp"] = Field("gif", title="Formato", json_schema_extra=labels(gif="GIF", webp="WebP animado (más ligero)"))


class ThumbnailsParams(Params):
    mode: Literal["sheet", "frames"] = Field(
        "sheet", title="Tipo", json_schema_extra=labels(sheet="Hoja de miniaturas", frames="Imágenes sueltas"))
    columns: int = Field(4, ge=2, le=10, title="Columnas (hoja)")
    rows: int = Field(4, ge=2, le=10, title="Filas (hoja)")
    count: int = Field(6, ge=1, le=50, title="Cantidad (sueltas)")
    width: int = Field(320, ge=120, le=1920, title="Ancho de cada imagen (px)")
    format: Literal["jpg", "png", "webp"] = Field("jpg", title="Formato", json_schema_extra=labels(jpg="JPEG", png="PNG", webp="WebP"))


class AudioConvertParams(Params):
    format: Literal["mp3", "aac", "opus", "ogg", "flac", "wav"] = Field("mp3", title="Formato", json_schema_extra=AUDIO_FORMAT_LABELS)
    bitrate: int = Field(192, ge=32, le=512, title="Calidad (kbps)", description="No aplica a FLAC/WAV")
    sample_rate: Literal["keep", "48000", "44100", "22050", "16000"] = Field(
        "keep", title="Frecuencia de muestreo",
        json_schema_extra=labels(keep="Original", **{"48000": "48 kHz", "44100": "44.1 kHz", "22050": "22 kHz", "16000": "16 kHz (voz)"}))
    mono: bool = Field(False, title="Convertir a mono")


class NormalizeParams(Params):
    target_lufs: int = Field(-16, ge=-30, le=-9, title="Volumen objetivo (LUFS)",
                             description="-16 podcasts/streaming · -14 Spotify/YouTube · -23 TV")
    bitrate: int = Field(192, ge=32, le=512, title="Calidad (kbps)")


class TranscribeParams(Params):
    model: Literal["tiny", "base", "small", "medium"] = Field(
        "base", title="Modelo",
        json_schema_extra=labels(tiny="Tiny (muy rápido)", base="Base (recomendado)", small="Small (más preciso)", medium="Medium (lento, mejor)"))
    language: Literal["auto", "es", "en", "pt", "fr", "de", "it"] = Field(
        "auto", title="Idioma",
        json_schema_extra=labels(auto="Detectar", es="Español", en="Inglés", pt="Portugués", fr="Francés", de="Alemán", it="Italiano"))
    output: Literal["srt", "vtt", "txt", "all"] = Field(
        "srt", title="Salida", json_schema_extra=labels(srt="Subtítulos SRT", vtt="Subtítulos VTT", txt="Texto plano", all="Los tres"))


# --- Documentos y archivos ---------------------------------------------------------------


class ArchiveParams(Params):
    format: Literal["zip", "7z"] = Field("zip", title="Formato", json_schema_extra=labels(zip="ZIP (compatible)", **{"7z": "7z (más ligero, permite contraseña)"}))
    level: Literal["normal", "max", "store"] = Field(
        "normal", title="Compresión", json_schema_extra=labels(normal="Normal", max="Máxima", store="Sin comprimir"))
    password: str = Field("", max_length=128, title="Contraseña (solo 7z)", json_schema_extra=SECRET)
    output_name: FileStem = Field("archivos", min_length=1, max_length=100, title="Nombre del archivo")


class ExtractParams(Params):
    password: str = Field("", max_length=128, title="Contraseña (si tiene)", json_schema_extra=SECRET)


class HashParams(Params):
    algorithm: Literal["sha256", "sha512", "sha1", "md5"] = Field(
        "sha256", title="Algoritmo", json_schema_extra=labels(sha256="SHA-256", sha512="SHA-512", sha1="SHA-1", md5="MD5"))
    output_name: FileStem = Field("checksums", min_length=1, max_length=100, title="Nombre del archivo")


# --- Registro ------------------------------------------------------------------------


@dataclass(frozen=True)
class Operation:
    id: str
    title: str
    description: str
    category: str
    params_model: type[BaseModel]
    extensions: frozenset[str]
    mode: str = "each"  # each | batch
    min_files: int = 1
    requires: str = ""
    gpu: bool = False

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "mode": self.mode,
            "min_files": self.min_files,
            "requires": self.requires,
            "gpu": self.gpu,
            "extensions": sorted(self.extensions),
            "schema": self.params_model.model_json_schema(),
            "defaults": _defaults(self.params_model),
        }


def _defaults(model: type[BaseModel]) -> dict:
    out = {}
    for name, field in model.model_fields.items():
        if not field.is_required():
            out[name] = field.get_default(call_default_factory=True)
    return out


IMG, PDF, VID, AUD, DOC = "Imágenes", "PDF", "Video", "Audio", "Documentos y archivos"
AI = "Requiere nodo con extras de IA"
FF = "Requiere nodo con ffmpeg"


def _op(id, title, description, category, model, extensions, **kw) -> Operation:
    return Operation(id, title, description, category, model, frozenset(extensions), **kw)


OPERATIONS: dict[str, Operation] = {
    op.id: op
    for op in [
        _op("image.convert", "Convertir imágenes", "Convierte y redimensiona a WebP, JPEG, PNG o AVIF.", IMG, ImageConvertParams, IMAGE_EXTENSIONS),
        _op("image.heic", "HEIC de iPhone → JPEG/WebP", "Convierte fotos HEIC/HEIF a formatos compatibles.", IMG, HeicParams, HEIC_EXTENSIONS),
        _op("image.avif", "Convertir a AVIF", "Formato moderno, más ligero que WebP.", IMG, AvifParams, IMAGE_EXTENSIONS),
        _op("image.watermark", "Marca de agua en imágenes", "Agrega un texto con posición y opacidad.", IMG, WatermarkParams, IMAGE_EXTENSIONS),
        _op("image.crop", "Recortar a proporción", "Recorta a 1:1, 16:9, 4:5… con encuadre inteligente.", IMG, CropParams, IMAGE_EXTENSIONS),
        _op("image.strip", "Quitar metadatos (EXIF/GPS)", "Elimina ubicación y datos de cámara sin recomprimir JPEG.", IMG, NoParams, IMAGE_EXTENSIONS),
        _op("image.rename", "Renombrar fotos", "Renombra el lote por fecha de la foto o un patrón.", IMG, RenameParams, IMAGE_EXTENSIONS, mode="batch"),
        _op("image.remove_bg", "Quitar fondo (IA)", "Deja el sujeto con fondo transparente.", IMG, RemoveBgParams, IMAGE_EXTENSIONS, requires=AI, gpu=True),
        _op("image.upscale", "Ampliar resolución (IA)", "Aumenta x2, x3 o x4 con superresolución.", IMG, UpscaleParams, IMAGE_EXTENSIONS, requires=AI),
        _op("pdf.compress", "Comprimir PDFs", "Reduce el tamaño de documentos PDF.", PDF, PdfCompressParams, PDF_EXTENSIONS),
        _op("pdf.merge", "Unir PDFs", "Combina varios PDFs en uno.", PDF, PdfMergeParams, PDF_EXTENSIONS, mode="batch", min_files=2),
        _op("pdf.split", "Separar PDF", "Divide por páginas o rangos.", PDF, PdfSplitParams, PDF_EXTENSIONS),
        _op("pdf.from_images", "Imágenes → PDF", "Junta imágenes (escaneos, recibos) en un PDF.", PDF, PdfFromImagesParams, IMAGE_EXTENSIONS, mode="batch"),
        _op("pdf.to_images", "PDF → imágenes", "Convierte páginas a PNG, JPEG o WebP.", PDF, PdfToImagesParams, PDF_EXTENSIONS),
        _op("pdf.rotate", "Rotar páginas", "Gira páginas 90°, 180° o 270°.", PDF, PdfRotateParams, PDF_EXTENSIONS),
        _op("pdf.protect", "Proteger con contraseña", "Cifra el PDF con AES-256 y permisos.", PDF, PdfProtectParams, PDF_EXTENSIONS),
        _op("pdf.unlock", "Quitar contraseña", "Elimina la contraseña de un PDF (necesitas conocerla).", PDF, PdfUnlockParams, PDF_EXTENSIONS),
        _op("pdf.ocr", "OCR: hacer buscable", "Reconoce texto en PDFs escaneados.", PDF, PdfOcrParams, PDF_EXTENSIONS, requires="Requiere nodo con Tesseract"),
        _op("pdf.watermark", "Marca de agua en PDF", "Sello de texto en todas las páginas.", PDF, PdfWatermarkParams, PDF_EXTENSIONS),
        _op("video.compress", "Comprimir video", "Recomprime a H.264/H.265 con calidad objetivo.", VID, VideoCompressParams, VIDEO_EXTENSIONS, requires=FF, gpu=True),
        _op("video.convert", "Convertir video", "MKV/AVI/MOV → MP4, WebM…", VID, VideoConvertParams, VIDEO_EXTENSIONS, requires=FF, gpu=True),
        _op("video.resize", "Cambiar resolución", "Baja a 1080p, 720p, 480p…", VID, VideoResizeParams, VIDEO_EXTENSIONS, requires=FF, gpu=True),
        _op("video.extract_audio", "Extraer audio", "Saca la pista de audio del video.", VID, ExtractAudioParams, VIDEO_EXTENSIONS, requires=FF),
        _op("video.gif", "Video → GIF", "Fragmento a GIF o WebP animado.", VID, GifParams, VIDEO_EXTENSIONS, requires=FF),
        _op("video.thumbnails", "Miniaturas", "Hoja de miniaturas o capturas sueltas.", VID, ThumbnailsParams, VIDEO_EXTENSIONS, requires=FF),
        _op("audio.convert", "Convertir audio", "WAV/FLAC/… → MP3, AAC, Opus…", AUD, AudioConvertParams, AUDIO_EXTENSIONS | VIDEO_EXTENSIONS, requires=FF),
        _op("audio.normalize", "Normalizar volumen", "Iguala el volumen (EBU R128).", AUD, NormalizeParams, AUDIO_EXTENSIONS, requires=FF),
        _op("audio.transcribe", "Transcribir (IA)", "Voz a texto o subtítulos con Whisper.", AUD, TranscribeParams, AUDIO_EXTENSIONS | VIDEO_EXTENSIONS, requires=AI, gpu=True),
        _op("doc.to_pdf", "Office → PDF", "Word, Excel, PowerPoint, ODT… a PDF.", DOC, NoParams, OFFICE_EXTENSIONS, requires="Requiere nodo con LibreOffice"),
        _op("archive.zip", "Comprimir en ZIP/7z", "Empaqueta el lote en un solo archivo.", DOC, ArchiveParams, ANY, mode="batch"),
        _op("archive.extract", "Descomprimir", "Extrae ZIP, 7z o TAR.", DOC, ExtractParams, ARCHIVE_EXTENSIONS),
        _op("file.hash", "Calcular hash", "SHA-256/MD5 para verificar integridad.", DOC, HashParams, ANY, mode="batch"),
    ]
}


class CatalogError(ValueError):
    pass


def validate_job(operation: str, params: dict | None) -> dict:
    op = OPERATIONS.get(operation)
    if op is None:
        raise CatalogError(f"Operación desconocida: {operation!r}")
    try:
        return op.params_model.model_validate(params or {}).model_dump()
    except ValidationError as exc:
        details = "; ".join(f"{_title(op, e['loc'])}: {e['msg']}" for e in exc.errors())
        raise CatalogError(f"Parámetros inválidos: {details}") from exc


def _title(op: Operation, loc) -> str:
    if not loc:
        return "params"
    field = op.params_model.model_fields.get(str(loc[0]))
    return (field.title if field and field.title else str(loc[0])) if field else ".".join(map(str, loc))


def secret_fields(operation: str) -> set[str]:
    op = OPERATIONS.get(operation)
    if op is None:
        return set()
    return {
        name for name, f in op.params_model.model_fields.items()
        if isinstance(f.json_schema_extra, dict) and f.json_schema_extra.get("secret")
    }


def redact(operation: str, params: dict) -> dict:
    secrets = secret_fields(operation)
    return {k: ("••••" if k in secrets and v else v) for k, v in (params or {}).items()}


def scrub(operation: str, params: dict) -> dict:
    secrets = secret_fields(operation)
    return {k: ("" if k in secrets else v) for k, v in (params or {}).items()}


def accepts_file(operation: str, filename: str) -> bool:
    op = OPERATIONS.get(operation)
    if op is None:
        return False
    if op.extensions == ANY:
        return True
    name = filename.lower()
    return any(name.endswith(ext) for ext in op.extensions)


def public_catalog() -> list[dict]:
    return [op.public() for op in OPERATIONS.values()]
