"""Operaciones del catálogo que este nodo puede ejecutar.

El agente solo ejecuta estas funciones; nunca comandos recibidos por red.
Los parámetros se vuelven a validar aquí aunque el servidor ya lo haya hecho.
"""

from __future__ import annotations

from pathlib import Path

from . import documents, images, media, pdfs  # noqa: F401 - registran sus operaciones
from .common import Cancelled, Context, ProcessingError
from .registry import OPS, available_operations, get, run_batch, run_each

PROCESSORS = OPS


def process(operation: str, params: dict, src: Path, out_dir: Path, original_name: str) -> tuple[Path, str]:
    """Atajo para operaciones de un archivo → un resultado (usado en pruebas)."""
    outputs = run_each(operation, params, src, out_dir, original_name)
    return outputs[0]


__all__ = [
    "Cancelled",
    "Context",
    "OPS",
    "PROCESSORS",
    "ProcessingError",
    "available_operations",
    "get",
    "process",
    "run_batch",
    "run_each",
]
