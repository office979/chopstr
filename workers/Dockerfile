# chopstr Worker, CPU-Variante. Build-Kontext: Monorepo-Root
#   docker build -f workers/Dockerfile -t chopstr-worker-cpu .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-inter ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Prompts liegen im Monorepo unter packages/prompts; prompts.py findet sie relativ zum Paket
COPY packages/prompts /app/packages/prompts
COPY workers/pyproject.toml workers/README.md /app/workers/
COPY workers/chopstr_worker /app/workers/chopstr_worker
COPY workers/eval /app/workers/eval
COPY workers/fonts /app/workers/fonts

RUN pip install --no-cache-dir "/app/workers[nlp]"

# c2patool (Phase 3): Release-Binary von github.com/contentauth/c2pa-rs nach /usr/local/bin kopieren
# YuNet-Modell (Phase 3): nach /app/workers/models/face_detection_yunet_2023mar.onnx

WORKDIR /app/workers
RUN useradd -m worker && chown -R worker /app
USER worker

ENTRYPOINT ["python", "-m", "chopstr_worker.worker"]
CMD ["--queues", "cpu"]
