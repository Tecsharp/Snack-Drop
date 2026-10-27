FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SNACKDROP_WORK_DIR=/work

RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY snackdrop_worker ./snackdrop_worker

RUN useradd --system --uid 10002 --home-dir /app snackworker \
    && mkdir -p /work && chown snackworker:snackworker /work
USER snackworker

CMD ["python", "-m", "snackdrop_worker"]
