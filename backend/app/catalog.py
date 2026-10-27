"""Catálogo seguro de operaciones.

Solo estas operaciones existen. Ningún usuario, asistente o nodo puede pedir
comandos arbitrarios: todo trabajo se valida contra estos modelos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
PDF_EXTENSIONS = {".pdf"}


class ImageConvertParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["webp", "jpeg", "png"] = Field("webp", description="Formato de salida")
    quality: int = Field(80, ge=1, le=100, description="Calidad (1-100)")
    max_width: int | None = Field(None, ge=16, le=16384, description="Ancho máximo en px")
    max_height: int | None = Field(None, ge=16, le=16384, description="Alto máximo en px")
    lossless: bool = Field(False, description="Sin pérdida (solo WebP)")
    strip_metadata: bool = Field(True, description="Eliminar metadatos EXIF")


class PdfCompressParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["low", "medium", "high"] = Field("medium", description="Nivel de compresión")
    grayscale: bool = Field(False, description="Convertir a escala de grises")


@dataclass(frozen=True)
class Operation:
    id: str
    title: str
    description: str
    params_model: type[BaseModel]
    extensions: frozenset[str]

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "extensions": sorted(self.extensions),
            "schema": self.params_model.model_json_schema(),
            "defaults": self.params_model().model_dump(),
        }


OPERATIONS: dict[str, Operation] = {
    "image.convert": Operation(
        id="image.convert",
        title="Convertir imágenes",
        description="Convierte y redimensiona imágenes a WebP, JPEG o PNG.",
        params_model=ImageConvertParams,
        extensions=frozenset(IMAGE_EXTENSIONS),
    ),
    "pdf.compress": Operation(
        id="pdf.compress",
        title="Comprimir PDFs",
        description="Reduce el tamaño de documentos PDF.",
        params_model=PdfCompressParams,
        extensions=frozenset(PDF_EXTENSIONS),
    ),
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
        details = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'params'}: {e['msg']}" for e in exc.errors())
        raise CatalogError(f"Parámetros inválidos: {details}") from exc


def accepts_file(operation: str, filename: str) -> bool:
    op = OPERATIONS.get(operation)
    if op is None:
        return False
    name = filename.lower()
    return any(name.endswith(ext) for ext in op.extensions)


def public_catalog() -> list[dict]:
    return [op.public() for op in OPERATIONS.values()]
