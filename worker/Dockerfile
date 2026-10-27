FROM python:3.13-slim

# Extras opcionales (pesan cientos de MB): ./setup.sh --with-office --with-ai
ARG WITH_OFFICE=false
ARG WITH_AI=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SNACKDROP_WORK_DIR=/work \
    SNACKDROP_MODELS_DIR=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ghostscript ffmpeg tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng pngquant fonts-dejavu-core \
    && if [ "$WITH_OFFICE" = "true" ]; then \
        apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc libreoffice-impress fonts-liberation; \
    fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-ai.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_AI" = "true" ]; then pip install -r requirements-ai.txt; fi
COPY snackdrop_worker ./snackdrop_worker

RUN useradd --system --uid 10002 --home-dir /work snackworker \
    && mkdir -p /work /models && chown snackworker:snackworker /work /models
USER snackworker

# Los modelos se descargan al construir (con hash verificado) para que el nodo funcione sin internet.
RUN if [ "$WITH_AI" = "true" ]; then python -m snackdrop_worker.download_models --all; fi

CMD ["python", "-m", "snackdrop_worker"]
