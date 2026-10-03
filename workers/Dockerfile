# chopstr Worker, CPU-Variante. Build-Kontext: Monorepo-Root
#   docker build -f workers/Dockerfile -t chopstr-worker-cpu .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-inter ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Gemeinsame Dateien aus dem Monorepo: Prompts, redaktionelle Grundlage, Schriftenliste, Ausgaberegeln.
# Die Pfade setzt docker-compose zusätzlich explizit (PROMPTS_DIR, EDITORIAL_DIR, CHOPSTR_CAPTION_FONTS,
# CHOPSTR_AUSGABE_REGELN); fehlt eine Datei, bricht der Worker beim Start ab (worker.check_assets).
COPY packages/prompts /app/packages/prompts
COPY packages/editorial /app/packages/editorial
COPY packages/design /app/packages/design
COPY packages/schema /app/packages/schema
COPY workers/pyproject.toml workers/README.md /app/workers/
COPY workers/chopstr_worker /app/workers/chopstr_worker
COPY workers/eval /app/workers/eval
COPY workers/fonts /app/workers/fonts

# spaCy-Sprachmodell für die Verbklammer (P28): Release-Wheel aus explosion/spacy-models, im Build installiert,
# nie zur Laufzeit geladen. Im selben pip-Aufruf wie das Extra nlp, damit pip eine zum Modell passende
# spaCy-Version wählt (de_core_news_md 3.8.0 verlangt spaCy 3.8; pyproject verlangt spacy>=3.7).
ARG SPACY_MODEL_VERSION=3.8.0
RUN pip install --no-cache-dir "/app/workers[nlp]" "de_core_news_md @ https://github.com/explosion/spacy-models/releases/download/de_core_news_md-${SPACY_MODEL_VERSION}/de_core_news_md-${SPACY_MODEL_VERSION}-py3-none-any.whl"

# c2patool (Phase 3): Release-Binary von github.com/contentauth/c2pa-rs nach /usr/local/bin kopieren
# YuNet-Modell (Phase 3): nach /app/workers/models/face_detection_yunet_2023mar.onnx

WORKDIR /app/workers
RUN useradd -m worker && chown -R worker /app
USER worker

ENTRYPOINT ["python", "-m", "chopstr_worker.worker"]
CMD ["--queues", "cpu"]
