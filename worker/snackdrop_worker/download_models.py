"""Descarga los modelos de IA que usa el nodo (se ejecuta al construir la imagen con IA).

    python -m snackdrop_worker.download_models          # ampliación (FSRCNN)
    python -m snackdrop_worker.download_models --all    # + quitar fondo (u2net) y Whisper «base»
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request

from .processors.common import models_dir

FSRCNN_BASE = "https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/master/models"
# Hashes fijados: si el archivo remoto cambia, la descarga falla en vez de usar algo no verificado.
FSRCNN = {
    2: "366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c",
    3: "efd38655a815908c6c8954db6052f128e76a735f1de657894c477d0dc0b64481",
    4: "5c68d18db561aed8ead4ffedf1b897ea615baaf60ebf6c35f8e641f8fa4a21bf",
}


def download_fsrcnn() -> None:
    target = models_dir() / "fsrcnn"
    target.mkdir(parents=True, exist_ok=True)
    for scale, sha in FSRCNN.items():
        path = target / f"FSRCNN_x{scale}.pb"
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            continue
        with urllib.request.urlopen(f"{FSRCNN_BASE}/FSRCNN_x{scale}.pb", timeout=60) as resp:  # noqa: S310 - URL fija
            data = resp.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit(f"Hash inesperado en FSRCNN_x{scale}.pb; descarga abortada")
        path.write_bytes(data)
        print(f"FSRCNN x{scale} listo")


def download_rembg() -> None:
    os.environ.setdefault("U2NET_HOME", str(models_dir() / "rembg"))
    from rembg import new_session

    new_session("u2net")  # rembg verifica el hash del modelo
    print("u2net listo")


def download_whisper(size: str = "base") -> None:
    from faster_whisper.utils import download_model

    download_model(size, cache_dir=str(models_dir() / "whisper"))
    print(f"Whisper {size} listo")


def main(argv: list[str]) -> None:
    download_fsrcnn()
    if "--all" in argv:
        download_rembg()
        download_whisper()


if __name__ == "__main__":
    main(sys.argv[1:])
