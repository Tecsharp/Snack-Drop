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


def _quoted(instruction: str) -> str | None:
    m = re.search(r"[«\"“']([^»\"”']{1,100})[»\"”']", instruction)
    return m.group(1).strip() if m else None


def _num(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _image_convert(text: str) -> tuple[str, dict, str] | None:
    fmt = None
    if "webp" in text:
        fmt = "webp"
    elif "avif" in text:
        fmt = "avif"
    elif re.search(r"\bjpe?g\b", text):
        fmt = "jpeg"
    elif re.search(r"\bpng\b", text):
        fmt = "png"
    image_words = re.search(r"imagen|imagenes|foto|fotos|fotografia|image|picture|photo|convert|redimension|resize", text)
    if fmt is None and not image_words:
        return None
    params: dict = {"format": fmt or "webp"}
    q = re.search(r"(?:calidad|quality)\s*(?:de|=|:)?\s*(\d{1,3})", text) or re.search(r"\b(\d{1,3})\s*%", text)
    if q:
        params["quality"] = max(1, min(100, int(q.group(1))))
    w = re.search(r"(?:ancho|width|max(?:imo)?\s*ancho)\s*(?:de|=|:)?\s*(\d{2,5})", text) or re.search(r"\b(\d{3,5})\s*px\b", text)
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
    return "image.convert", params, ", ".join(parts) + "."


def _rules(text: str, instruction: str) -> tuple[str, dict, str] | None:
    quoted = _quoted(instruction)
    has_pdf = "pdf" in text
    video = re.search(r"\bvideos?\b|\bmp4\b|\bmkv\b|\bmov\b|\bavi\b|pelicula|clip", text)
    audio = re.search(r"\baudios?\b|\bmp3\b|\bflac\b|\bwav\b|\bopus\b|podcast|cancion|musica", text)

    if re.search(r"\b(word|excel|powerpoint|docx?|xlsx?|pptx?|odt|office)\b", text) and has_pdf:
        return "doc.to_pdf", {}, "Convertir documentos de Office a PDF."
    if re.search(r"descomprim|extrae(r)? (el|los|del) (zip|7z|rar|comprimido)|abre el zip", text):
        return "archive.extract", {}, "Descomprimir el archivo."
    if re.search(r"\bhash\b|sha-?256|checksum|\bmd5\b|verificar integridad", text):
        algo = "md5" if "md5" in text else "sha512" if "512" in text else "sha256"
        return "file.hash", {"algorithm": algo}, f"Calcular {algo.upper()} de cada archivo."
    if re.search(r"\b(zip|7z)\b|empaquet|comprim\w* en un (solo )?archivo", text) and not has_pdf:
        fmt = "7z" if "7z" in text else "zip"
        return "archive.zip", {"format": fmt}, f"Empaquetar todo en un {fmt.upper()}."
    if re.search(r"transcrib|subtitul|\bsrt\b|\bvtt\b|voz a texto", text):
        out = "txt" if re.search(r"\btexto\b|\btxt\b", text) and "subtitul" not in text else "srt"
        lang = "es" if "espanol" in text else "en" if "ingles" in text else "auto"
        return "audio.transcribe", {"output": out, "language": lang}, "Transcribir el audio con Whisper."

    if has_pdf:
        if re.search(r"\b(une|unir|junta|juntar|combina|combinar|merge|fusiona)", text) and not re.search(r"imagen|foto", text):
            return "pdf.merge", {}, "Unir los PDFs en uno."
        if re.search(r"(imagen|imagenes|foto|fotos|escaneo|recibos?)\s+(a|en)\s+(un\s+)?pdf|crea(r)? un pdf", text):
            size = "a4" if "a4" in text else "letter" if "carta" in text else "original"
            return "pdf.from_images", {"page_size": size}, "Juntar las imágenes en un PDF."
        if re.search(r"pdf\s+a\s+(imagen|imagenes|png|jpe?g|webp)|paginas? (a|como) (imagen|png|jpg)", text):
            fmt = "jpeg" if re.search(r"jpe?g", text) else "webp" if "webp" in text else "png"
            return "pdf.to_images", {"format": fmt, "dpi": _num(r"(\d{2,3})\s*dpi", text) or 150}, "Convertir páginas a imágenes."
        if re.search(r"separa|divide|dividir|split|extrae (las )?paginas", text):
            m = re.search(r"\d+\s*-\s*\d*(?:\s*,\s*\d+(?:\s*-\s*\d*)?)*", text)
            if m:
                return "pdf.split", {"mode": "ranges", "ranges": m.group(0).replace(" ", "")}, f"Separar por rangos {m.group(0)}."
            return "pdf.split", {"mode": "each_page"}, "Separar una página por archivo."
        if re.search(r"\b(rota|rotar|gira|girar)", text):
            angle = 180 if "180" in text else 270 if re.search(r"270|izquierda", text) else 90
            return "pdf.rotate", {"angle": angle}, f"Rotar páginas {angle}°."
        if re.search(r"quita(r)? (la )?contrasena|desbloquea|sin contrasena|elimina(r)? (la )?contrasena", text):
            return "pdf.unlock", {"password": quoted or ""}, "Quitar la contraseña (indícala en el formulario)."
        if re.search(r"protege|contrasena|cifra|encripta", text):
            return "pdf.protect", {"password": quoted or "", "allow_copy": "copiar" in text and "no copiar" not in text}, "Proteger con contraseña."
        if re.search(r"\bocr\b|buscable|reconoc\w* (el )?texto|escaneado", text):
            lang = "eng" if "ingles" in text else "spa+eng"
            return "pdf.ocr", {"language": lang}, "Aplicar OCR para hacer el PDF buscable."
        if re.search(r"marca de agua|watermark|sello", text):
            return "pdf.watermark", {"text": quoted or "CONFIDENCIAL"}, f"Agregar marca «{quoted or 'CONFIDENCIAL'}»."
        level = "medium"
        if re.search(r"\b(maxim|alta|alto|fuerte|agresiv|mucho|high|max)", text):
            level = "high"
        elif re.search(r"\b(baja|bajo|liger|poco|suave|low|minim)", text):
            level = "low"
        params = {"level": level, "grayscale": bool(re.search(r"gris|grayscale|blanco y negro", text))}
        return "pdf.compress", params, f"Comprimir PDFs con nivel {level}."

    if video:
        if re.search(r"\bgif\b|animad", text):
            return "video.gif", {"format": "webp" if "webp" in text else "gif"}, "Crear un GIF del video."
        if re.search(r"miniatura|thumbnail|capturas?|fotogramas", text):
            return "video.thumbnails", {"mode": "frames" if re.search(r"sueltas|capturas", text) else "sheet"}, "Generar miniaturas."
        if re.search(r"(extrae|saca|sacar|extraer)\w* (el |solo el )?audio|audio del video|mp3 del", text):
            fmt = "aac" if re.search(r"aac|m4a", text) else "flac" if "flac" in text else "wav" if "wav" in text else "mp3"
            return "video.extract_audio", {"format": fmt}, f"Extraer el audio a {fmt.upper()}."
        res = _num(r"\b(2160|1440|1080|720|480|360)p?\b", text) or (2160 if re.search(r"\b4k\b", text) else None)
        if res and re.search(r"redimension|resolucion|baja|reduce|pasa|cambia|a\s+\d{3,4}p", text) and "comprim" not in text:
            return "video.resize", {"height": res}, f"Cambiar resolución a {res}p."
        m = re.search(r"\b(?:a|en)\s+(mp4|mkv|webm|mov)\b", text)
        if m and "comprim" not in text:
            return "video.convert", {"container": m.group(1)}, f"Convertir a {m.group(1).upper()}."
        params = {"codec": "h265" if re.search(r"h\.?265|hevc", text) else "h264"}
        if res:
            params["max_height"] = res
        if re.search(r"\b(maxim|mucho|fuerte)", text):
            params["crf"] = 30
        return "video.compress", params, "Comprimir video" + (f" a máx. {res}p" if res else "") + "."

    if audio:
        if re.search(r"normaliz|volumen|loudness", text):
            return "audio.normalize", {}, "Normalizar el volumen."
        m = re.search(r"\b(mp3|aac|m4a|opus|ogg|flac|wav)\b(?!.*\b(mp3|aac|m4a|opus|ogg|flac|wav)\b)", text)
        fmt = {"m4a": "aac"}.get(m.group(1), m.group(1)) if m else "mp3"
        return "audio.convert", {"format": fmt}, f"Convertir audio a {fmt.upper()}."

    if "heic" in text:
        fmt = "webp" if "webp" in text else "png" if re.search(r"\bpng\b", text) else "jpeg"
        return "image.heic", {"format": fmt}, f"Convertir HEIC a {fmt.upper()}."
    if re.search(r"(quita|elimina|borra|sin)\w*\s+(el |los )?fondo|remove (the )?background", text):
        return "image.remove_bg", {}, "Quitar el fondo de las imágenes."
    if re.search(r"(quita|elimina|borra|limpia)\w*\s+(los |el )?(metadatos|exif|gps|ubicacion)", text):
        return "image.strip", {}, "Quitar metadatos EXIF/GPS."
    if re.search(r"marca de agua|watermark", text):
        return "image.watermark", {"text": quoted or "©"}, f"Agregar marca de agua «{quoted or '©'}»."
    if re.search(r"amplia|aumenta (la )?resolucion|upscale|super ?resolucion|agranda", text):
        scale = _num(r"x\s*([234])\b", text) or _num(r"\b([234])\s*x\b", text) or 2
        return "image.upscale", {"scale": scale}, f"Ampliar x{scale}."
    m = re.search(r"\b(1:1|4:5|5:4|4:3|3:4|3:2|2:3|16:9|9:16)\b", text)
    if re.search(r"recort|crop|cuadrad", text) or m:
        aspect = m.group(1) if m else "1:1"
        return "image.crop", {"aspect": aspect}, f"Recortar a {aspect}."
    if re.search(r"renombr|rename|cambia(r)? (el )?nombre", text):
        return "image.rename", {"sort": "date"}, "Renombrar por fecha de la foto."
    return _image_convert(text)


def plan_locally(instruction: str, node_names: dict[int, str] | None = None) -> dict:
    text = _strip_accents(instruction.lower())
    node_id = _match_node(instruction, node_names or {})
    found = _rules(text, instruction)
    if found is None:
        return {
            "operation": None,
            "params": {},
            "node_id": node_id,
            "explanation": "No encontré una operación del catálogo para esa instrucción.",
        }
    operation, params, explanation = found
    try:
        clean = validate_job(operation, params)
    except CatalogError:
        # Faltan datos obligatorios (p. ej. la contraseña): se rellenan en el formulario.
        defaults = OPERATIONS[operation].public()["defaults"]
        clean = {**defaults, **{k: v for k, v in params.items() if v not in ("", None)}}
        explanation += " Completa los campos que faltan."
    return {"operation": operation, "params": clean, "node_id": node_id, "explanation": explanation}


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
