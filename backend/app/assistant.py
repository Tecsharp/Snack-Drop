"""Convierte instrucciones en lenguaje natural en trabajos del catálogo.

Usa DeepSeek si hay API key; si no (o si falla) usa un intérprete local por reglas.
La respuesta del modelo NUNCA se ejecuta directamente: siempre se valida contra
el catálogo seguro (``catalog.validate_job``).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata

import httpx

from .catalog import OPERATIONS, CatalogError, public_catalog, validate_job
from .config import Settings

log = logging.getLogger("snackdrop.assistant")

MAX_INSTRUCTION = 1000


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _match_node(text: str, node_names: dict[int, str]) -> int | None:
    norm = _strip_accents(text.lower())
    best: tuple[int, int] | None = None
    for node_id, name in node_names.items():
        n = _strip_accents(name.lower())
        if n and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", norm):
            if best is None or len(n) > best[1]:
                best = (node_id, len(n))
    return best[0] if best else None


def plan_locally(instruction: str, node_names: dict[int, str] | None = None) -> dict:
    text = _strip_accents(instruction.lower())
    node_id = _match_node(instruction, node_names or {})

    if "pdf" in text:
        level = "medium"
        if re.search(r"\b(maxim|alta|alto|fuerte|agresiv|mucho|high|max)", text):
            level = "high"
        elif re.search(r"\b(baja|bajo|liger|poco|suave|low|minim)", text):
            level = "low"
        params = {"level": level, "grayscale": bool(re.search(r"gris|grayscale|blanco y negro", text))}
        return {
            "operation": "pdf.compress",
            "params": validate_job("pdf.compress", params),
            "node_id": node_id,
            "explanation": f"Comprimir PDFs con nivel {level}.",
        }

    fmt = None
    if "webp" in text:
        fmt = "webp"
    elif re.search(r"\bjpe?g\b", text):
        fmt = "jpeg"
    elif re.search(r"\bpng\b", text):
        fmt = "png"
    image_words = re.search(r"imagen|imagenes|foto|fotos|fotografia|image|picture|photo|convert|redimension|resize", text)
    if fmt is None and not image_words:
        return {
            "operation": None,
            "params": {},
            "node_id": node_id,
            "explanation": "No encontré una operación del catálogo para esa instrucción.",
        }

    params: dict = {"format": fmt or "webp"}
    q = re.search(r"(?:calidad|quality)\s*(?:de|=|:)?\s*(\d{1,3})", text) or re.search(r"\b(\d{1,3})\s*%", text)
    if q:
        params["quality"] = max(1, min(100, int(q.group(1))))
    w = re.search(r"(?:ancho|width|max(?:imo)?\s*ancho)\s*(?:de|=|:)?\s*(\d{2,5})", text) or re.search(
        r"\b(\d{3,5})\s*px\b", text
    )
    if w:
        params["max_width"] = max(16, min(16384, int(w.group(1))))
    h = re.search(r"(?:alto|height)\s*(?:de|=|:)?\s*(\d{2,5})", text)
    if h:
        params["max_height"] = max(16, min(16384, int(h.group(1))))
    if re.search(r"sin perdida|lossless", text) and params["format"] == "webp":
        params["lossless"] = True

    parts = [f"Convertir imágenes a {params['format'].upper()}"]
    if "quality" in params:
        parts.append(f"calidad {params['quality']}")
    if "max_width" in params:
        parts.append(f"ancho máx. {params['max_width']}px")
    return {
        "operation": "image.convert",
        "params": validate_job("image.convert", params),
        "node_id": node_id,
        "explanation": ", ".join(parts) + ".",
    }


def _system_prompt(node_names: dict[int, str]) -> str:
    catalog = [
        {"id": op["id"], "description": op["description"], "params_schema": op["schema"]}
        for op in public_catalog()
    ]
    nodes = [{"id": nid, "name": name} for nid, name in node_names.items()]
    return (
        "Eres el planificador de Snack-Drop. Conviertes la instrucción del usuario en UN trabajo "
        "del catálogo seguro. No puedes ejecutar comandos ni inventar operaciones o parámetros. "
        "Responde SOLO un objeto JSON con la forma "
        '{"operation": "<id del catálogo>" | null, "params": {...}, "node_id": <id de nodo> | null, '
        '"explanation": "<frase breve en español>"}. '
        "Si la instrucción no corresponde a ninguna operación, usa operation null. "
        "Usa node_id solo si el usuario nombra claramente uno de los nodos disponibles.\n"
        f"Catálogo: {json.dumps(catalog, ensure_ascii=False)}\n"
        f"Nodos disponibles: {json.dumps(nodes, ensure_ascii=False)}"
    )


async def plan_with_deepseek(instruction: str, settings: Settings, node_names: dict[int, str]) -> dict:
    payload = {
        "model": settings.deepseek_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _system_prompt(node_names)},
            {"role": "user", "content": instruction},
        ],
    }
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            f"{settings.deepseek_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    if not isinstance(data, dict):
        raise CatalogError("Respuesta del modelo con formato inválido")
    operation = data.get("operation")
    node_id = data.get("node_id")
    if not isinstance(node_id, int) or node_id not in node_names:
        node_id = None
    explanation = str(data.get("explanation") or "")[:300]
    if operation is None:
        return {"operation": None, "params": {}, "node_id": node_id, "explanation": explanation}
    if operation not in OPERATIONS:
        raise CatalogError(f"El modelo propuso una operación fuera del catálogo: {operation!r}")
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    return {
        "operation": operation,
        "params": validate_job(operation, params),
        "node_id": node_id,
        "explanation": explanation,
    }


async def plan(instruction: str, settings: Settings, node_names: dict[int, str]) -> dict:
    instruction = instruction.strip()[:MAX_INSTRUCTION]
    if settings.deepseek_api_key:
        try:
            result = await plan_with_deepseek(instruction, settings, node_names)
            result["source"] = "deepseek"
            return result
        except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            log.warning("DeepSeek no disponible, uso intérprete local: %s", exc)
            result = plan_locally(instruction, node_names)
            result["source"] = "local"
            result["warning"] = "DeepSeek no respondió correctamente; se usó el intérprete local."
            return result
    result = plan_locally(instruction, node_names)
    result["source"] = "local"
    return result
