# chopstr Worker

Python-Worker des Clipping-Tools chopstr: Ingest, deutsche Transkription (DE/AT/CH), Sprechererkennung,
DACH-NLP, Signal-Heatmap. Orchestriert über Temporal, Dateien im S3-kompatiblen Objektspeicher, Zustand in
Postgres (Schema: `packages/schema/migrations/0001_init.sql`). Alle Verarbeitung bleibt in der EU; der
Residency-Guard (`chopstr_worker/residency.py`) blockiert jeden anderen Aufruf, bevor er das Netz erreicht.

Phase 0 (Fundament), Phase 1 („Deutsch hören") und Phase 2 („Story-Engine": Kandidaten mit Begründung,
Gates, Story-Graph) sind umgesetzt und im Workflow verdrahtet. Die Module der Phase 3 (Render) liegen unter
`pipeline/`, hängen aber noch nicht in der Kette (siehe unten).

## Struktur

```
workers/
  chopstr_worker/
    config.py          Settings aus ENV, Tier standard|sovereign
    db.py              psycopg-Verbindung (autocommit), load_source, insert/update
    events.py          pipeline_events (started|progress|finished|failed|skipped), sources.status
    storage.py         S3 (boto3, path-style) oder lokaler Ordner; derived_key() für Idempotenz
    residency.py       Provider- und Host-Allowlist, Deny-Liste, guarded_client()
    costlog.py         job_costs-Zeilen, Preistabelle per ENV, estimate_eur()
    prompts.py         packages/prompts/<name>_v<N>.md laden, rendern, prompt_version
    providers_llm.py   LLM.structured() über bedrock-eu | mistral-eu | selfhost-eu | local-heuristic, Redis-Cache
    heuristic_llm.py   Heuristik-Provider ohne Netz (Entwicklung, Demo; kein Ersatz für ein Sprachmodell)
    ingest.py          ffprobe, sha256, 16-kHz-WAV, 720p-Proxy (ffmpeg per subprocess)
    pipeline/          reine Funktionen (transcribe, dach_nlp, segment, signals, story_score, story_graph,
                       story_engine, fidelity, ...)
    activities/        Temporal-Activities (probe_and_extract, transcribe_de, diarize, heatmap,
                       fuse_and_nlp, detect_candidates, render_pack, notify)
    workflows/         ClipProjectWorkflow
    worker.py          python -m chopstr_worker.worker --queues cpu,gpu
  eval/                wer_eval.py, eval_harness.py, export_predictions.py, README.md
  tests/               pytest, läuft ohne GPU, ohne Modelle, ohne Postgres, ohne S3
  Dockerfile           CPU-Image (python:3.12-slim + ffmpeg + fonts-inter)
  Dockerfile.gpu       GPU-Image (nvidia/cuda + ffmpeg)
```

## Setup

Voraussetzungen: Python 3.11 oder neuer, ffmpeg und ffprobe im PATH.

Mit uv:

```bash
cd workers
uv sync --extra dev            # Kernpakete plus pytest/ruff
uv sync --all-extras           # zusätzlich asr (faster-whisper, pyannote, torch), nlp (spaCy), vision (OpenCV)
uv run pytest -q
```

Mit venv und pip:

```bash
cd workers
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"            # ohne schwere Extras
.venv/bin/pip install -e ".[dev,asr,nlp]"    # für echte Transkription
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

spaCy-Modell für den Verbklammer-Schutz (optional): `python -m spacy download de_core_news_lg`.
Fehlt spaCy, liefert `dach_nlp.forbidden_cut_ranges()` eine leere Liste und setzt
`verb_bracket_available = False` (die Transkriptstatistik enthält das Flag).

## Umgebungsvariablen

Quelle: `.env.example` im Monorepo-Root. Der Worker liest zusätzlich die mit „Worker" markierten Werte.

| Variable | Bedeutung |
|---|---|
| `APP_ENV`, `APP_VERSION` | Umgebung, Version (landet in C2PA-Manifesten) |
| `DATABASE_URL` | Postgres, Rolle `chopstr_worker` (BYPASSRLS) |
| `REDIS_URL` | optionaler LLM-Cache |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE` | Temporal-Server (self-hosted, EU) |
| `TEMPORAL_TASK_QUEUE_CPU`, `TEMPORAL_TASK_QUEUE_GPU` | Queue-Namen (Default `chopstr-cpu`, `chopstr-gpu`) |
| `S3_ENDPOINT`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Objektspeicher; leerer `S3_ENDPOINT` = lokaler Ordner |
| `S3_BUCKET_SOURCES`, `S3_BUCKET_DERIVED`, `S3_FORCE_PATH_STYLE` | Buckets, path-style für MinIO |
| `LOCAL_STORAGE_DIR` (Worker) | lokaler Storage-Fallback ohne S3 |
| `WORKER_WORK_DIR` (Worker) | Arbeitsordner für Downloads und Zwischenergebnisse |
| `LLM_PROVIDER` | `bedrock-eu` (Standard-Tier), `mistral-eu` oder `selfhost-eu` (Sovereign); `local-heuristic` nur für Entwicklung und Demo ohne Netz |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | Bedrock EU-Region und Inference-Profil (keine Defaults) |
| `MISTRAL_BASE_URL`, `MISTRAL_API_KEY`, `MISTRAL_MODEL` | Mistral EU |
| `SELFHOST_LLM_BASE_URL`, `SELFHOST_LLM_MODEL`, `SELFHOST_LLM_API_KEY` (Worker) | OpenAI-kompatibler Endpoint (vLLM, TGI) |
| `ASR_MODEL_DE`, `ASR_MODEL_CH` | faster-whisper-Modelle (CTranslate2); CH ist Beta |
| `ASR_DEVICE`, `ASR_COMPUTE` | `auto|cpu|cuda`, `int8|int8_float16|float16` |
| `ASR_WINDOW_S`, `ASR_OVERLAP_S` (Worker) | Fensterlänge und Überlappung (Default 600 s / 20 s) |
| `HF_TOKEN`, `DIARIZER_MODEL` (Worker) | pyannote-Zugang, Modell-ID (Default siehe TODO in `pipeline/transcribe.py`) |
| `GLADIA_API_KEY`, `GLADIA_BASE_URL` | ASR-Fallback, nur mit gesetzter Basis-URL und erlaubtem Host |
| `LANGUAGETOOL_URL` | Grammatikprüfung (Phase 3) |
| `EGRESS_ALLOWLIST` | zusätzliche erlaubte Hosts, kommagetrennt |
| `GPU_EUR_PER_HOUR`, `CPU_EUR_PER_HOUR`, `STORAGE_EUR_PER_GB_MONTH`, `LLM_EUR_PER_1M_INPUT`, `LLM_EUR_PER_1M_OUTPUT`, `GLADIA_EUR_PER_HOUR` (Worker) | Preistabelle für `job_costs.estimated_eur` |
| `PROMPTS_DIR` (Worker) | überschreibt den Prompt-Ordner (Default `packages/prompts` im Monorepo) |
| `YUNET_MODEL_PATH` (Worker) | YuNet-ONNX für Reframing (Phase 3) |
| `C2PA_SIGN_CERT`, `C2PA_PRIVATE_KEY` | c2patool-Signatur (Phase 3) |

Modell-IDs haben bewusst keine Defaults im Code. Fehlt `ASR_MODEL_DE`, schlägt `transcribe_de` mit einer
klaren Meldung fehl („Kein ASR-Modell für Variante de konfiguriert (ASR_MODEL_DE setzen)").

## Residency-Guard

- Provider: `bedrock-eu`, `mistral-eu`, `selfhost-eu`, `gladia-eu` sind EU-fähig. Sovereign-Workspaces
  dürfen nur `mistral-eu`, `selfhost-eu`, `gladia-eu` (kein US-Anbieter in der Kette). `local-heuristic`
  steht in beiden Listen, weil er die Maschine nie verlässt (kein Netz, kein Modell).
- Hosts: erlaubt sind nur die konfigurierten Endpunkte (S3, LanguageTool, Temporal, Mistral, Selfhost,
  Gladia), `bedrock-runtime.eu-*.amazonaws.com`, localhost und `EGRESS_ALLOWLIST`. Bekannte Nicht-EU-Hosts
  (openai.com, anthropic.com, googleapis.com, AWS-Regionen außerhalb der EU) sind immer gesperrt, auch wenn sie
  versehentlich konfiguriert werden.
- `guarded_client()` hängt die Prüfung als httpx-Request-Hook ein: ein verbotener Host wirft
  `ResidencyError`, bevor eine Verbindung aufgebaut wird. `ResidencyError` ist im Workflow non-retryable.
- `npm run residency:check` im Monorepo-Root führt `tests/test_residency.py` aus.

## Queues und Workflow

| Queue | Activities |
|---|---|
| `chopstr-cpu` | probe_and_extract, heatmap, fuse_and_nlp, detect_candidates, render_pack, notify, Workflow |
| `chopstr-gpu` | transcribe_de, diarize |

Ablauf `ClipProjectWorkflow`:

```
probe_and_extract -> gather(transcribe_de, diarize, heatmap) -> fuse_and_nlp -> detect_candidates
  -> notify(candidates_ready) -> Freigabe-Signale approve(candidate_id, destination) / finish_review
  (bis 14 Tage) -> render_pack (Phase 3, Stub) -> notify(renders_ready)
```

Start über den Client (Beispiel):

```python
from temporalio.client import Client
from chopstr_worker.workflows import ClipProjectWorkflow, ClipProjectParams

client = await Client.connect("localhost:7233")
await client.start_workflow(
    ClipProjectWorkflow.run,
    ClipProjectParams(source_id="<uuid>", workspace_id="<uuid>"),
    id=f"project-{source_id}", task_queue="chopstr-cpu",  # gleiche ID-Konvention wie apps/web/lib/temporal.ts
)
```

Jede Activity schreibt `pipeline_events` (started, progress, finished, failed, skipped) mit deutschen
Meldungen und `job_costs`. Output-Keys sind `sha256(asset_key + Parameter + Version)`; vorhandene
Ableitungen werden übersprungen (Events zeigen `skipped: true` im Payload). `fuse_and_nlp` schreibt
`transcript_versions` (origin `asr`, `version = max + 1`); der Status bleibt `analyzing`.
`detect_candidates` setzt `scoring`, lässt die Story-Engine laufen und setzt am Ende `ready`.

## Phase 2: Story-Engine (`pipeline/story_engine.py`, Activity `detect_candidates`)

Aus dem aktuellen Transkript (`transcript_versions`, höchste Version), dem Briefing (`sources.brief`:
audience, wanted, exclude, platform), dem Markenprofil (`learned_weights`) und der Heatmap entstehen
Zeilen in `candidates` nach dem Vertrag `packages/schema/CANDIDATES.md` (`candidates_v1`).

| Stufe | Was passiert | Prompt |
|---|---|---|
| 1 Seeds | Kapitel (ca. 4 Minuten) mit Heatmap-Seeds zuerst, alle Kapitel werden bewertet | |
| 2 Vorschlag | 0 bis 4 Satz-Spannen pro Kapitel, gesamt maximal 20 Kandidaten (beste nach Rubrik) | `propose_moments_v1` |
| 3 Rubrik | Scores mit Belegzitaten, bis zu 2 Reparaturrunden (erst nach vorn, dann nach hinten); deterministische Gates: Satzgrenzen, Verbklammer (spaCy, sonst `available=false`), Open-Loop-Ende, Sinntreue (`ends_before_contrast`) | `score_clip_v1` |
| 4 Story-Graph | Relativierungen im 60-Sekunden-Folgefenster, jeder Treffer per LLM bestätigt; ohne Urteil bleibt `confirmed = null` | `story_graph_confirm_v1` |

Regeln: Länge 12 bis 90 Sekunden hart (Verworfenes steht mit Grund im `finished`-Payload unter
`discarded`, nicht in der Tabelle), Gewichte aus dem Frontmatter von `score_clip_v1`, überschreibbar durch
`brand_profiles.learned_weights` (nur wenn alle fünf Schlüssel vorhanden sind und die Summe etwa 1 ist).
`why` ist ein deutscher Satz aus Rubrik, Gates und Story-Graph; `risk_flags` enthält `humor`,
`sensitive_topic`, `claim` (Zahlen oder Superlative im Clip) und `heuristic_only`.

Events: `progress` pro Kapitel („Kapitel 3 von 15 bewertet, 4 Kandidaten"), `finished` mit
`candidates`, `gate_passed`, `chapters`, `provider`, `model_id`, `prompt_versions`, `discarded`, `cached`.
Kostenlog `job_type = 'llm_candidates'` mit den Token-Summen aller LLM-Aufrufe.

Re-Run: Kandidaten derselben Quelle ohne `human_verdict` werden gelöscht, Zeilen mit Urteil bleiben.
Idempotenz: das Ergebnis liegt unter `candidates/<sha256(Transkriptversion + Briefing + Prompt-Versionen +
Provider/Modell + Gewichte)>.json` im Derived-Bucket; existiert der Key, werden die Zeilen daraus
geschrieben, ohne LLM-Aufrufe. Bei `ResidencyError` oder fehlendem Modell: Event `failed` mit deutscher
Meldung, `sources.status = 'failed'`.

### Heuristik-Provider ohne Netz

`LLM_PROVIDER=local-heuristic` bedient die drei Tool-Schemata deterministisch aus dem gerenderten Prompt
(`chopstr_worker/heuristic_llm.py`): Vorschläge um Diskursmarker, Zahlen und Fragen (Länge aus der
Wortzahl geschätzt), Rubrik-Scores aus einfachen Merkmalen mit wörtlichen Satzanfängen als Belegen,
Story-Graph-Bestätigung ohne Urteil (`confirmed = null`). Ergebnisse tragen `model_id = "heuristic-v1"`
und `risk_flags` enthält `heuristic_only`; `prompt_version` bleibt gesetzt, weil die Prompts gerendert
wurden. Das ist kein Ersatz für ein Sprachmodell und nur für Entwicklung, Tests und Demos gedacht.
Produktion braucht einen echten EU-Provider (`bedrock-eu`, `mistral-eu`, `selfhost-eu`).

## Lokal gegen Temporal und MinIO

```bash
# Temporal (Dev-Server) und MinIO, jeweils in eigenem Terminal
temporal server start-dev --port 7233
minio server ./infra/data/minio --console-address :9001     # Buckets chopstr-sources, chopstr-derived anlegen

# Postgres mit Migration (Monorepo-Root)
npm run migrate

# Worker, in der Entwicklung beide Queues auf einer Maschine
cd workers
cp ../.env.example ../.env    # Werte anpassen; die Shell muss sie exportieren (z. B. set -a; source ../.env; set +a)
.venv/bin/python -m chopstr_worker.worker --queues cpu,gpu
```

Ohne MinIO: `S3_ENDPOINT` leer lassen und `LOCAL_STORAGE_DIR=/pfad/zum/ordner` setzen. Der Worker legt dann
Bucket-Unterordner an. Ohne GPU laufen `transcribe_de` und `diarize` auf der CPU (`ASR_DEVICE=cpu`,
`ASR_COMPUTE=int8`), was für Tests mit kurzen Dateien reicht.

## Tests und Eval

```bash
.venv/bin/python -m pytest -q                       # alle Tests (Workflow-Test lädt einmalig ein Temporal-Testbinary)
.venv/bin/python -m pytest -q -m "not network"      # ohne Netz
.venv/bin/ruff check .
.venv/bin/python -m eval.wer_eval gold/ hyp/ --lexicon names.txt
.venv/bin/python -m eval.eval_harness gold_clips/ preds/ --k 10
```

Blindtest der Story-Engine (Precision@10): Kandidaten einer Quelle als Vorhersage-Datei exportieren,
dann gegen die Gold-Clips der Redaktion auswerten.

```bash
# aus Postgres (DATABASE_URL oder --db)
.venv/bin/python -m eval.export_predictions --source-id <uuid> --episode ep01.mp4 --out preds/ep01.json
# oder aus dem Ergebnis-JSON der Engine im Storage (Key steht im finished-Payload unter "key")
.venv/bin/python -m eval.export_predictions --json storage/chopstr-derived/candidates/<hash>.json --episode ep01.mp4 --out preds/ep01.json
.venv/bin/python -m eval.eval_harness gold_clips/ preds/ --k 10
```

Optionen: `--only-gate-passed`, `--include-rejected`. Details zu Gold-Formaten und Zielwerten: `eval/README.md`.

## Docker

```bash
# Build-Kontext ist das Monorepo-Root (Prompts werden mitkopiert)
docker build -f workers/Dockerfile -t chopstr-worker-cpu .
docker build -f workers/Dockerfile.gpu -t chopstr-worker-gpu .
docker run --env-file .env chopstr-worker-cpu
docker run --gpus all --env-file .env chopstr-worker-gpu --queues gpu
```

## Phase 2 und 3: Status der Module

| Modul | Zweck | Status |
|---|---|---|
| `pipeline/story_engine.py` | vier Stufen bis zur `candidates`-Zeile (Vertrag `candidates_v1`) | verdrahtet in `detect_candidates` |
| `pipeline/story_score.py` | LLM-Vorschläge und Rubrik (Prompts `propose_moments_v1`, `score_clip_v1`) | verdrahtet |
| `pipeline/story_graph.py` | spätere Relativierungen (Kontrastmarker, `story_graph_confirm_v1`) | verdrahtet |
| `pipeline/fidelity.py` | Sinntreue-Wächter nach Schnitten | Gate `fidelity` in Phase 2, UI-Anbindung für Trims fehlt |
| `pipeline/compose.py` | Multi-Segment-Clips, Teaser-Regeln, Timeline-Remapping | fertig |
| `pipeline/copy_de.py` | Hooks (`hooks_v1`), Linter, Werbekennzeichnung | fertig |
| `pipeline/captions_de.py` | ASS/SRT mit Presets und Safe Zones | fertig |
| `pipeline/reframe.py` | YuNet-Gesichtsdetektion, Shot-Plan (braucht OpenCV und Modell) | fertig, untestbar ohne Modell |
| `pipeline/render.py` | ffmpeg-Render, Loudness `master` (-16 LUFS / -1,5 dBTP) oder `legacy_social` (-14 / -1) | fertig |
| `pipeline/compliance.py` | C2PA via c2patool, AI-Act-Label, Quellenangabe | fertig, braucht c2patool |
| `activities/analyze.render_pack` | compose, reframe, captions, render, C2PA | Stub (NotImplementedError) |

## Regeln

- Schwere Imports (faster_whisper, pyannote, torch, spacy, cv2, boto3) nur innerhalb von Funktionen.
- Keine Telemetrie mit Transkriptinhalten; Logs enthalten IDs, Dauern, Zähler.
- Code-Bezeichner Englisch, Docstrings und Event-Meldungen Deutsch, keine Gedankenstriche in Nutzertexten.
- Prompts nur über `prompts.load()`; jede Änderung ist eine neue Datei mit erhöhter Version.
