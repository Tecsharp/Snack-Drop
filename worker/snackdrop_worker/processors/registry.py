"""Registro de operaciones que este nodo sabe ejecutar.

Cada operación declara su modo:
- ``each``: se aplica a cada archivo por separado (un archivo dañado se omite y el lote continúa).
- ``batch``: recibe todos los archivos a la vez (unir PDFs, crear un ZIP…).

``available`` indica si las herramientas necesarias están instaladas; el nodo solo
anuncia al servidor las operaciones disponibles.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .common import Context, Output, ProcessingError


@dataclass(frozen=True)
class Op:
    id: str
    mode: str
    fn: Callable
    available: Callable[[], bool]


OPS: dict[str, Op] = {}


def register(op_id: str, mode: str = "each", available: Callable[[], bool] = lambda: True):
    def deco(fn):
        OPS[op_id] = Op(op_id, mode, fn, available)
        return fn

    return deco


def available_operations() -> list[str]:
    result = []
    for op in OPS.values():
        try:
            if op.available():
                result.append(op.id)
        except Exception:  # noqa: BLE001 - una herramienta rota no debe tumbar el agente
            pass
    return result


def get(op_id: str) -> Op:
    op = OPS.get(op_id)
    if op is None:
        raise ProcessingError(f"Operación no soportada por este nodo: {op_id}")
    return op


def run_each(op_id: str, params: dict, src: Path, out_dir: Path, name: str, ctx: Context | None = None) -> list[Output]:
    op = get(op_id)
    if op.mode != "each":
        raise ProcessingError(f"{op_id} procesa el lote completo")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = op.fn(src, out_dir, name, params if isinstance(params, dict) else {}, ctx or Context())
    return result if isinstance(result, list) else [result]


def run_batch(op_id: str, params: dict, files: list[tuple[Path, str]], out_dir: Path, ctx: Context | None = None) -> list[Output]:
    op = get(op_id)
    if op.mode != "batch":
        raise ProcessingError(f"{op_id} procesa archivo por archivo")
    out_dir.mkdir(parents=True, exist_ok=True)
    return op.fn(files, out_dir, params if isinstance(params, dict) else {}, ctx or Context())
