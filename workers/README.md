# chopstr Worker

Python-Worker des Clipping-Tools chopstr: Ingest, deutsche Transkription (DE/AT/CH), Sprechererkennung,
DACH-NLP, Signal-Heatmap. Orchestriert über Temporal, Dateien im S3-kompatiblen Objektspeicher, Zustand in
Postgres (Schema: `packages/schema/migrations/0001_init.sql`). Alle Verarbeitung bleibt in der EU; der
Residency-Guard (`chopstr_worker/residency.py`) blockiert jeden anderen Aufruf, bevor er das Netz erreicht.

Phase 0 (Fundament), Phase 1 („Deutsch hören"), Phase 2 („Story-Engine": Kandidaten mit Begründung,
Gates, Story-Graph), Phase 3 („Render": Copy, Reframe, Captions, ffmpeg, Provenienz) und der Worker-Teil von
Phase 4 (Lösch-Workflow mit Nachweis, Retention-Schedule, Verbrauch nach Stunden, Marken-Fonts und Logo im
Render, Seed) sind umgesetzt. Verträge: `packages/schema/CLIPS.md` (`clips_v1`, `render_plan_v1`) und
`packages/schema/PHASE4.md` (Abschnitte 5, 7, 8; Migration `0003_auth_billing.sql`).

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
    usage.py           usage_periods: Quellminuten je Kalendermonat, Mehrverbrauch pro angefangener Stunde, Render- und Token-Zähler
    prompts.py         packages/prompts/<name>_v<N>.md laden, rendern, prompt_version
    providers_llm.py   LLM.structured() über bedrock-eu | mistral-eu | selfhost-eu | local-heuristic, Redis-Cache
    heuristic_llm.py   Heuristik-Provider ohne Netz (Entwicklung, Demo; kein Ersatz für ein Sprachmodell)
    ingest.py          ffprobe, sha256, 16-kHz-WAV, 720p-Proxy (ffmpeg per subprocess)
    pipeline/          reine Funktionen (transcribe, dach_nlp, segment, signals, story_score, story_graph,
                       story_engine, fidelity, copy_engine, render_plan, reframe, captions_de, render, compliance)
    activities/        Temporal-Activities (probe_and_extract, transcribe_de, diarize, heatmap,
                       fuse_and_nlp, detect_candidates, render_pack, notify,
                       delete_entity, find_expired, enqueue_deletion)
    workflows/         ClipProjectWorkflow, RetentionWorkflow
    worker.py          python -m chopstr_worker.worker --queues cpu,gpu [--ensure-schedules]
  fonts/               Inter-Bold (OFL) für drawtext und libass, siehe fonts/README.md
  scripts/             seed_dev.py (python -m scripts.seed_dev): Dev-Nutzer, Workspace, Markenprofil, Abo
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
| `LANGUAGETOOL_URL` | Grammatikprüfung der Copy (nur wenn gesetzt; Fehler dort sind Hinweise, nie fatal) |
| `EGRESS_ALLOWLIST` | zusätzliche erlaubte Hosts, kommagetrennt |
| `GPU_EUR_PER_HOUR`, `CPU_EUR_PER_HOUR`, `STORAGE_EUR_PER_GB_MONTH`, `LLM_EUR_PER_1M_INPUT`, `LLM_EUR_PER_1M_OUTPUT`, `GLADIA_EUR_PER_HOUR` (Worker) | Preistabelle für `job_costs.estimated_eur` |
| `PROMPTS_DIR` (Worker) | überschreibt den Prompt-Ordner (Default `packages/prompts` im Monorepo) |
| `YUNET_MODEL_PATH` (Worker) | YuNet-ONNX für Reframing; fehlt die Datei oder OpenCV, läuft Reframe `neutral` |
| `RENDER_X264_PRESET`, `RENDER_FONTS_DIR` (Worker) | x264-Preset (Default `medium`, Tests `ultrafast`), Fontordner (Default `workers/fonts`) |
| `C2PA_SIGN_CERT`, `C2PA_PRIVATE_KEY` | c2patool-Signatur; ohne c2patool ist `provenance.c2pa = "skipped"` |
| `RETENTION_CRON`, `RETENTION_TIMEZONE` | Schedule `retention-daily` (Default `0 3 * * *`, `Europe/Vienna`), angelegt mit `--ensure-schedules` |

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
| `chopstr-cpu` | probe_and_extract, heatmap, fuse_and_nlp, detect_candidates, render_pack, notify, delete_entity, find_expired, enqueue_deletion, Workflows |
| `chopstr-gpu` | transcribe_de, diarize |

Ablauf `ClipProjectWorkflow`:

```
probe_and_extract -> gather(transcribe_de, diarize, heatmap) -> fuse_and_nlp -> detect_candidates
  -> notify(candidates_ready) -> Freigabe-Signale approve(candidate_id, destination) / finish_review
  (bis 14 Tage) -> render_pack (Phase 3) -> notify(renders_ready)
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

## Phase 3: Render (`activities/render.py`, Activity `render_pack`)

`render_pack(candidate_id, destination)` findet die `clips`-Zeile `(candidate_id, platform = destination)` oder legt
sie an, setzt `rendering` und läuft in fünf Schritten mit `progress`-Events (`payload.phase`):

| Schritt | Modul | Was passiert |
|---|---|---|
| copy | `pipeline/copy_engine.py` | Ohne `hook_versions`-Zeile: `hooks_v1` (fünf Varianten, `copy_de.lint`, Wortlimits 12/9, `fidelity.hook_claim_check`), `post_caption_v1` je Plattform, optional LanguageTool (nur mit `LANGUAGETOOL_URL`, über den Residency-Hook). Auswahl: erste Variante ohne Claim-Issues, sonst Variante 1. Existiert eine Version (auch manuell aus dem Hook-Studio), nimmt der Render die höchste. |
| reframe | `pipeline/reframe.py` | `talking_head` (eine Position, Gesichtsmitte bei 37 % der Ausgabehöhe), `two_speakers` (Schnitt auf den aktiven Sprecher, min. 1,2 s, `speaker_positions`), `neutral` (mittig). YuNet nur mit `YUNET_MODEL_PATH` plus OpenCV, sonst `detector = "none"` und Hinweis im Event. |
| captions | `pipeline/captions_de.py` | Wortzeiten über `compose.remap_words` auf die Ausgabe-Timeline, Preset je Plattform (auf der Standardplattform des Profils dessen `caption_preset`), für 4:5/1:1/16:9 proportional skaliert (`scaled_preset`), ASS/SRT/VTT, `cps_warnings`, `fidelity.check_cut` in `fidelity_warnings`. |
| encode | `pipeline/render.py` | Ein ffmpeg-Durchgang: pro Shot ein per `-ss/-t` gesuchter Input, crop/scale, concat; Audio pro Segment mit 20-ms-Micro-Fades; `subtitles` (libass, `fontsdir`), Titelkarte 2,5 s und Hook-Overlay 3 s per `drawtext`; Loudness zweistufig (Pass 1 `loudnorm=print_format=json`, Pass 2 linear mit Messwerten, bei LRA über 7 LU `acompressor` davor); H.264 High, yuv420p, `+faststart`, AAC 192k, fps aus dem Plan. Danach `ebur128`-Messung, Poster bei 1,0 s, `regression_checks` (Dauer ±0,3 s, Auflösung, `blackdetect`, Audiospur). |
| provenance | `pipeline/compliance.py` | C2PA nur mit c2patool (`signed`/`failed` mit Grund), sonst `skipped` mit „c2patool nicht installiert"; `ai_label_required`, `source_credit` bei `third_party`, `ad_label`. Upload nach `derived` (`renders/<clip_id>/<hash>.mp4|srt|vtt|jpg|ass`). |

Der Plan (`clips.render_plan`, `render_plan_v1`, `pipeline/render_plan.py`) ist deterministisch und enthält keine
Umgebungswerte. Idempotenz: `hash = sha256(plan + hook_version + transcript_version)[:16]`; ist die MP4 unter
diesem Hash vorhanden und am Clip eingetragen, meldet der Schritt `skipped`. Eine neue Hook-Version ergibt einen
neuen Hash und damit einen neuen Render. Am Ende: `caption_versions` Version n+1 (`origin = 'auto'`), `clips`
mit `file_key`, `duration_s`, `width`, `height`, `fps`, `loudness`, `provenance`, `status = 'rendered'`;
bei Fehlern `failed` plus `render_error`. Kostenlog `job_type = 'render'` (CPU-Sekunden, Clip-Minuten,
Dateigröße, Token der Copy).

Ehrlich gegenüber der Umgebung: was fehlt, steht als Hinweis im `finished`-Payload (`notes`) und im
Render-Ergebnis, ohne den Render zu stoppen:

- ffmpeg ohne libass (`subtitles`) oder libfreetype (`drawtext`): Untertitel bzw. Overlays werden nicht
  eingebrannt, SRT/VTT liegen trotzdem bei. Der Homebrew-Build auf macOS hat beides oft nicht; das
  Docker-Image (Debian ffmpeg) hat beides. `render.capabilities()` zeigt, was der Build kann.
- Font `Inter-Bold` fehlt: Overlays entfallen (siehe `fonts/README.md`, `RENDER_FONTS_DIR`).
- YuNet-Modell oder OpenCV fehlt: `reframe.strategy = "neutral"`, `detector = "none"`.
- c2patool fehlt: `provenance.c2pa = "skipped"`.

Heuristik-Provider für die Copy (`LLM_PROVIDER=local-heuristic`): `write_hooks` baut fünf Varianten aus
Satzanfängen, erster Zahl und Kontrastmarker des Clips (Anrede aus dem Prompt, keine erfundenen Zahlen),
`write_post_caption` nur aus Sätzen des Clips. Kein Ersatz für ein Sprachmodell.

## Phase 4: Löschung, Retention, Verbrauch, Marken-Assets

### Lösch-Workflow (`activities/deletion.py`, Activity `delete_entity(job_id)`)

Die Web-App legt eine Zeile in `deletion_jobs` an (`entity` source | clip | brand_profile | workspace, `reason`
user_request | retention | workspace_deleted | gdpr_request) und startet die Activity. Sie setzt den Job auf
`running`, löscht zuerst Objektspeicher-Keys, dann Datenbankzeilen, schreibt einen Audit-Eintrag
(`<entity>.deleted`, `actor_type = system`, Payload mit Job-ID, Anzahl Keys und Zählern) und schließt mit `done`
und `finished_at`. Fehler: `failed` mit `error`, Audit `<entity>.delete_failed`, die Ausnahme geht an Temporal
(Retry nach Policy). Ein Job mit `done` wird nicht wiederholt.

| Entität | Objektspeicher | Datenbank |
|---|---|---|
| `source` | Original (`sources`), `audio_key`, `proxy_key`, alle `clips.file_key/srt_key/vtt_key/poster_key`, `caption_versions.ass_key/srt_key`, der ganze Ordner `renders/<clip_id>/` (`Storage.list`), die JSONs unter `asr/`, `diar/`, `heatmap/`, `candidates/` (aus den `key`-Feldern der `pipeline_events`-Payloads) | caption_versions, hook_versions, guest_approvals, clips, candidates, transcript_corrections, transcript_versions, pipeline_events (in dieser Reihenfolge, Zähler in `rows_deleted`); die `sources`-Zeile bleibt anonymisiert: Titel „gelöscht“, `original_filename`, `audio_key`, `proxy_key`, `sha256` null, `storage_key` leer, `brief` `{}`, Status `deleted`, `deleted_at` |
| `clip` | Render-Dateien und Caption-Keys des Clips, Ordner `renders/<clip_id>/` | caption_versions, hook_versions, guest_approvals des Clips; Keys am Clip werden genullt |
| `brand_profile` | alle `brand_assets.storage_key` des Profils | `brand_assets` |
| `workspace` | wie `source` je Quelle, dann alle Brand-Assets des Workspace | je nicht gelöschter Quelle ein eigener Job (`reason = workspace_deleted`), inline ausgeführt; Audit `workspace.deleted`; die `workspaces`-Zeile löscht die Web-App danach |

`keys_deleted` ist der Löschnachweis: eine Liste `{bucket, key, deleted_at, existed}`; Keys, die schon fehlten,
stehen mit `existed = false` drin (bereits weg). Läuft für die Quelle noch ein `ClipProjectWorkflow`
(`sources.temporal_workflow_id`), wird er vorher per `terminate` beendet; ein Fehler dabei wird nur geloggt.
Die Activity schreibt keine `pipeline_events` (die werden gerade gelöscht) und loggt nur IDs und Zähler.

### Retention (`workflows/retention.py`, Schedule `retention-daily`)

`RetentionWorkflow` läuft täglich über den Temporal-Schedule: `find_expired(now)` liefert Quellen mit
`delete_after < now` und Status nicht `deleted` ohne offenen Job sowie Workspaces mit gesetztem
`deletion_requested_at` und `deletion_scheduled_for < now` (30 Tage Karenz). Je Treffer `enqueue_deletion`
(`reason = retention`) und direkt danach `delete_entity`, sequenziell, höchstens 50 pro Lauf (`max_per_run`).
Ein fehlgeschlagener Job zählt in `failed`, die anderen laufen weiter. Der Schedule wird mit
`python -m chopstr_worker.worker --queues cpu --ensure-schedules` angelegt (`client.create_schedule` mit
`ScheduleSpec(cron_expressions=[RETENTION_CRON], time_zone_name=RETENTION_TIMEZONE)`; existiert er, wird er
übersprungen). Zum manuellen Start: `temporal schedule trigger --schedule-id retention-daily`.

### Verbrauch nach Stunden (`usage.py`)

Eine Zeile in `usage_periods` pro Workspace und Kalendermonat (`period_start` erster, `period_end` letzter Tag).
`included_minutes` kommt aus `subscriptions.plan_code` und `plans.included_hours * 60`; ohne Abo gilt Starter
(240 Minuten), ohne `plans`-Zeile feste Starter-Defaults. `book_source_minutes` addiert Quellminuten und rechnet
`overage_minutes = max(0, used - included)` und `overage_eur = ceil(overage_minutes / 60) * plans.overage_eur_per_hour`
(pro angefangener Stunde). Aufrufe: `probe_and_extract` bucht die Dauer der Quelle beim ersten Ingest (Zeile ohne
`duration_s`, damit ein Re-Run nicht doppelt zählt; der `finished`-Payload zeigt `booked_minutes`), `render_pack`
erhöht `render_count`, und der `cost_sink` von Story-Engine und Copy-Engine (`usage.llm_sink`) addiert
`llm_input_tokens` und `llm_output_tokens` je LLM-Aufruf. Die `job_costs`-Zeilen bleiben unverändert daneben.

### Marken-Fonts und Logo im Render

`render_pack` liest `brand_profiles.ci` (`fonts.primary_asset_id` oder `secondary_asset_id`, `logo_asset_id`,
`watermark.enabled`) und lädt die Assets aus `brand_assets` (Bucket `derived`) nach
`WORKER_WORK_DIR/fonts/<sha>.<ext>` (Fonts) beziehungsweise `WORKER_WORK_DIR/brand/<sha>.<ext>` (Logo), per
Hash gecacht. Der `font_family` des Assets steht als `Fontname` in der ASS (`captions_de.to_ass(font_family=...)`,
libass findet die Datei über `fontsdir`) und im Plan unter `captions.font`; die Datei geht als `fontfile` in
`drawtext` für Titelkarte und Hook-Overlay. Fehlt das Asset, der Familienname oder der Download, bleibt Inter mit
dem Hinweis „Marken-Font fehlt, Inter verwendet“ in `notes`. Das Logo wird als PNG unten rechts innerhalb der
Safe Zone per `overlay` gelegt (`watermark.opacity` Default 0,85, `width_ratio` 0,18 der Ausgabebreite); SVG wird
mit Hinweis übersprungen. `render_plan.brand = { font_asset_id, logo_asset_id, watermark }` ist Teil des Plans und
damit des Idempotenz-Hashes: ein anderer Font oder ein Wasserzeichen ergibt einen neuen Render.

### Seed für die lokale Entwicklung

```bash
DATABASE_URL=postgres://... .venv/bin/python -m scripts.seed_dev
```

Legt idempotent an: Nutzer `dev@chopstr.local` (Passwort `chopstr-dev`), Workspace „PLACEMedia“ (Slug
`placemedia`), Mitgliedschaft `owner`, Markenprofil „PLACEMedia“, Abo `starter` im Status `trialing` (14 Tage)
und die `usage_periods`-Zeile des aktuellen Monats. Der Passwort-Hash ist ein Argon2id-PHC-String
(`$argon2id$v=19$m=65536,t=3,p=4$...`, 32 Byte Hash, 16 Byte Salt) über `argon2-cffi` (Extra `dev`); das sind
die Standardparameter von `@node-rs/argon2` in der Web-App, `verify()` liest sie aus dem String.

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
.venv/bin/python -m pytest -q tests/test_render_media.py tests/test_render_activity.py   # Render mit echtem ffmpeg (12-s-Testvideo, Lautheit, Regressionschecks)
.venv/bin/python -m pytest -q tests/test_render_brand.py                                # Marken-Font (echte OTF als Asset) und Logo-Wasserzeichen
.venv/bin/python -m pytest -q tests/test_deletion.py tests/test_usage.py tests/test_seed_dev.py   # Phase 4 ohne ffmpeg
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

## Status der Module

| Modul | Zweck | Status |
|---|---|---|
| `pipeline/story_engine.py` | vier Stufen bis zur `candidates`-Zeile (Vertrag `candidates_v1`) | verdrahtet in `detect_candidates` |
| `pipeline/story_score.py` | LLM-Vorschläge und Rubrik (Prompts `propose_moments_v1`, `score_clip_v1`) | verdrahtet |
| `pipeline/story_graph.py` | spätere Relativierungen (Kontrastmarker, `story_graph_confirm_v1`) | verdrahtet |
| `pipeline/fidelity.py` | Sinntreue-Wächter nach Schnitten | Gate `fidelity` in Phase 2, `fidelity_warnings` am Clip in Phase 3 |
| `pipeline/compose.py` | Multi-Segment-Clips, Teaser-Regeln, Timeline-Remapping | verdrahtet |
| `pipeline/copy_de.py` | Linter, Werbekennzeichnung, Markenprofil | verdrahtet über `copy_engine` |
| `pipeline/copy_engine.py` | `hooks_v1` und `post_caption_v1`, Claim-Check, LanguageTool, Auswahl | verdrahtet in `render_pack` |
| `pipeline/captions_de.py` | ASS/SRT/VTT mit Presets, Safe Zones, Skalierung auf andere Formate | verdrahtet |
| `pipeline/reframe.py` | Strategien `talking_head`, `two_speakers`, `neutral`; YuNet optional | verdrahtet, Detektor optional |
| `pipeline/render_plan.py` | `render_plan_v1` deterministisch, Hash für Idempotenz | verdrahtet |
| `pipeline/render.py` | ffmpeg-Render aus dem Plan, Loudness zweistufig, Messung, Poster, Regressionschecks | verdrahtet, libass/drawtext optional |
| `pipeline/compliance.py` | C2PA via c2patool, AI-Act-Label, Quellenangabe | verdrahtet, c2patool optional |
| `activities/render.py` | `render_pack`: Copy, Reframe, Captions, Encode, Provenienz, Upload, DB, Marken-Font und Logo | verdrahtet |
| `activities/deletion.py` | `delete_entity` mit Löschnachweis, `find_expired`, `enqueue_deletion` | verdrahtet |
| `workflows/retention.py` | `RetentionWorkflow` über Schedule `retention-daily` | verdrahtet, Schedule per `--ensure-schedules` |
| `usage.py` | `usage_periods` je Kalendermonat, Mehrverbrauch pro angefangener Stunde | verdrahtet in Ingest, Render, LLM-Sink |
| `scripts/seed_dev.py` | Dev-Nutzer, Workspace, Markenprofil, Abo, Verbrauchsperiode | vorhanden |

`DeletionWorkflow` (Workflow-ID `deletion-<job_id>`, CPU-Queue) führt einen einzelnen Lösch-Job sofort aus;
die Web-App startet ihn nach einer Nutzeranfrage. Der tägliche `RetentionWorkflow` holt alle übrigen Jobs ab.

Offene Punkte Phase 4 (Worker):

- Ein Job `entity = clip` löscht Dateien und Versionen, nullt die Keys und setzt `clips.status = 'deleted'`
  mit `deleted_at` (Migration 0004). Die Clip-Zeile bleibt als Nachweis.
- Die Storage-JSONs unter `asr/`, `diar/`, `heatmap/`, `candidates/` werden über die `key`-Felder der
  `pipeline_events` gefunden; sind diese Events schon weg, bleiben verwaiste JSONs liegen (Inhalte ohne
  Bezug zur Quelle, aber Transkripttext). Eine spätere Bereinigung braucht ein Prefix pro Quelle.
- Das Wasserzeichen sitzt unten rechts in der Safe Zone und kann sich mit langen Caption-Zeilen überschneiden;
  Position und Größe kommen aus `ci.watermark`, eine Kollisionsprüfung fehlt.

## Regeln

- Schwere Imports (faster_whisper, pyannote, torch, spacy, cv2, boto3) nur innerhalb von Funktionen.
- Keine Telemetrie mit Transkriptinhalten; Logs enthalten IDs, Dauern, Zähler.
- Code-Bezeichner Englisch, Docstrings und Event-Meldungen Deutsch, keine Gedankenstriche in Nutzertexten.
- Prompts nur über `prompts.load()`; jede Änderung ist eine neue Datei mit erhöhter Version.
