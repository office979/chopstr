# chopstr Worker

Python-Worker des Clipping-Tools chopstr: Ingest, deutsche Transkription (DE/AT/CH), Sprechererkennung,
DACH-NLP, Signal-Heatmap. Orchestriert über Temporal, Dateien im S3-kompatiblen Objektspeicher, Zustand in
Postgres (Schema: `packages/schema/migrations/0001_init.sql`). Alle Verarbeitung bleibt in der EU; der
Residency-Guard (`chopstr_worker/residency.py`) blockiert jeden anderen Aufruf, bevor er das Netz erreicht.

Phase 0 (Fundament), Phase 1 („Deutsch hören"), Phase 2 („Story-Engine": Kandidaten mit Begründung,
Gates, Story-Graph), Phase 3 („Render": Copy, Reframe, Captions, ffmpeg, Provenienz) und der Worker-Teil von
Phase 4 (Lösch-Workflow mit Nachweis, Retention-Schedule, Verbrauch nach Stunden, Marken-Fonts und Logo im
Render, Seed) sind umgesetzt, dazu der Worker-Teil von Phase 5 (Outbox und Webhooks, Publishing mit
Metrik-Fenstern, Decision Log, Lernschleife, Wochenreport). Verträge: `packages/schema/CLIPS.md`
(`clips_v1`, `render_plan_v1`), `packages/schema/PHASE4.md` (Abschnitte 5, 7, 8; Migration
`0003_auth_billing.sql`) und `packages/schema/PHASE5.md` (5a, 5b, „Interne Schnittstelle Worker ↔ Web“;
Migration `0005_phase5.sql`).

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
    outbox.py          outbox_events schreiben (source.ready, clip.rendered, ...), Hooks aus events.py
    decision_log.py    decision_log-Zeilen (candidate_proposed, candidate_scored, hook_selected, reframe_strategy, publish)
    learning.py        Ridge-Fit der Rubrik-Gewichte, hook_pattern_stats, Thompson-Reihenfolge
    internal_api.py    Client für /api/internal/publish, /metrics, /mail (X-Internal-Secret)
    prompts.py         packages/prompts/<name>_v<N>.md laden, rendern, prompt_version
    providers_llm.py   LLM.structured() über bedrock-eu | mistral-eu | selfhost-eu | local-heuristic, Redis-Cache
    heuristic_llm.py   Heuristik-Provider ohne Netz (Entwicklung, Demo; kein Ersatz für ein Sprachmodell)
    ingest.py          ffprobe, sha256, 16-kHz-WAV, 720p-Proxy (ffmpeg per subprocess)
    pipeline/          reine Funktionen (transcribe, dach_nlp, segment, signals, story_score, story_graph,
                       story_engine, fidelity, copy_engine, render_plan, reframe, captions_de, render, compliance)
    activities/        Temporal-Activities (probe_and_extract, transcribe_de, diarize, heatmap,
                       fuse_and_nlp, detect_candidates, render_pack, notify,
                       delete_entity, find_expired, enqueue_deletion,
                       dispatch_outbox, find_due_deliveries, deliver_webhook, load_publication, publish_clip,
                       fetch_metrics, cancel_publication, find_learning_profiles, learn_brand_profile,
                       find_report_workspaces, build_weekly_report)
    workflows/         ClipProjectWorkflow, DeletionWorkflow, RetentionWorkflow, OutboxWorkflow, PublishWorkflow,
                       LearningWorkflow, WeeklyReportWorkflow
    worker.py          python -m chopstr_worker.worker --queues cpu,gpu [--ensure-schedules]
    local_worker.py    python -m chopstr_worker.local_worker [--once] [--interval 3]: Polling ohne Temporal (siehe „Lokaler Testmodus“)
  fonts/               Inter-Bold (OFL) für drawtext und libass, siehe fonts/README.md
  scripts/             seed_dev.py (python -m scripts.seed_dev): Dev-Nutzer, Workspace, Markenprofil, Abo
                       local_env.sh (source scripts/local_env.sh): Umgebung für den lokalen Testmodus, ffmpeg-Symlinks in .local/bin
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
| `HF_TOKEN`, `DIARIZER_MODEL` (Worker) | pyannote-Zugang, Modell-ID (Default siehe TODO in `pipeline/transcribe.py`); ohne `HF_TOKEN` oder ohne `pyannote.audio` läuft `diarize` als Fallback mit einem Sprecher `SPEAKER_00` (Event „Sprechertrennung übersprungen: HF_TOKEN fehlt (pyannote)“, `stats.diarization = "skipped"`) |
| `GLADIA_API_KEY`, `GLADIA_BASE_URL` | ASR-Fallback, nur mit gesetzter Basis-URL und erlaubtem Host |
| `LANGUAGETOOL_URL` | Grammatikprüfung der Copy (nur wenn gesetzt; Fehler dort sind Hinweise, nie fatal) |
| `EGRESS_ALLOWLIST` | zusätzliche erlaubte Hosts, kommagetrennt |
| `GPU_EUR_PER_HOUR`, `CPU_EUR_PER_HOUR`, `STORAGE_EUR_PER_GB_MONTH`, `LLM_EUR_PER_1M_INPUT`, `LLM_EUR_PER_1M_OUTPUT`, `GLADIA_EUR_PER_HOUR` (Worker) | Preistabelle für `job_costs.estimated_eur` |
| `PROMPTS_DIR` (Worker) | überschreibt den Prompt-Ordner (Default `packages/prompts` im Monorepo) |
| `YUNET_MODEL_PATH` (Worker) | YuNet-ONNX für Reframing; fehlt die Datei oder OpenCV, läuft Reframe `neutral` |
| `RENDER_X264_PRESET`, `RENDER_FONTS_DIR` (Worker) | x264-Preset (Default `medium`, Tests `ultrafast`), Fontordner (Default `workers/fonts`) |
| `C2PA_SIGN_CERT`, `C2PA_PRIVATE_KEY` | c2patool-Signatur; ohne c2patool ist `provenance.c2pa = "skipped"` |
| `RETENTION_CRON`, `RETENTION_TIMEZONE` | Schedule `retention-daily` (Default `0 3 * * *`, `Europe/Vienna`), angelegt mit `--ensure-schedules`; die Zeitzone gilt für alle Schedules |
| `APP_INTERNAL_URL`, `INTERNAL_API_SECRET` | interne Endpunkte der Web-App (`/api/internal/*`, Header `X-Internal-Secret`); der Host steht automatisch auf der Residency-Allowlist |
| `WEBHOOK_TIMEOUT_MS` | Timeout je Webhook-Zustellung (Default 8000) |
| `OUTBOX_INTERVAL_S` | Intervall des Schedules `outbox-dispatch` (Default 30 s) |
| `WEEKLY_REPORT_CRON` | Schedule `weekly-report` (Default `0 7 * * 1`, Montag 07:00) |
| `LEARNING_CRON` (Worker) | Schedule `learning-nightly` (Default `0 4 * * *`) |

Modell-IDs haben bewusst keine Defaults im Code. Fehlt `ASR_MODEL_DE`, schlägt `transcribe_de` mit einer
klaren Meldung fehl („Kein ASR-Modell für Variante de konfiguriert (ASR_MODEL_DE setzen)"). Enthält die
Modell-ID kein „german“, trägt das `finished`-Event von `transcribe_de` den Hinweis „Standard-Whisper statt
deutschem Fine-Tune“ (`payload.hint`). Verifizierte IDs stehen unter „Lokaler Testmodus“.

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
| `chopstr-cpu` | probe_and_extract, heatmap, fuse_and_nlp, detect_candidates, render_pack, notify, delete_entity, find_expired, enqueue_deletion, dispatch_outbox, find_due_deliveries, deliver_webhook, load_publication, publish_clip, fetch_metrics, cancel_publication, find_learning_profiles, learn_brand_profile, find_report_workspaces, build_weekly_report, Workflows |
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

## Phase 5 (Worker): Outbox, Webhooks, Publishing, Decision Log, Lernschleife, Wochenreport

Vertrag `packages/schema/PHASE5.md`, Migration `0005_phase5.sql`. Der Worker besitzt Zustellung, Zeitplanung,
Retries und Metrik-Fenster; Provider-SDKs, OAuth und Mailversand bleiben in der Web-App.

### Schedules (`--ensure-schedules`, alle idempotent, Zeitzone `RETENTION_TIMEZONE`, Overlap `SKIP`)

| Schedule | Workflow | Takt |
|---|---|---|
| `retention-daily` | `RetentionWorkflow` | `RETENTION_CRON` |
| `outbox-dispatch` | `OutboxWorkflow` | alle `OUTBOX_INTERVAL_S` Sekunden |
| `learning-nightly` | `LearningWorkflow` | `LEARNING_CRON` (Default 04:00) |
| `weekly-report` | `WeeklyReportWorkflow` | `WEEKLY_REPORT_CRON` (Default Montag 07:00) |

### Outbox und Webhooks (`outbox.py`, `activities/webhooks.py`, `workflows/outbox.py`)

`outbox.emit(conn, workspace_id, event, entity, entity_id, payload)` schreibt `outbox_events`. Der Worker
schreibt automatisch: `source.ready` / `source.failed` (Hook in `events.set_source_status`), `candidates.ready`
(`detect_candidates`), `clip.rendered` / `clip.failed` (Hook in `events.step` für den Schritt `render`: das
`finished`-Payload trägt `clip_id`, bei Fehlern kommt die `clip_id` aus dem letzten `progress`-Zwischenstand),
`publication.published` / `publication.failed` (`publish_clip`). Payloads enthalten IDs, Titel, Status, Zähler
und externe URLs, nie Transkript- oder Hook-Texte. Ein Fehler im Outbox-Hook wird nur geloggt.

`OutboxWorkflow`: `dispatch_outbox(limit)` legt je aktivem Endpunkt mit passendem Ereignis (oder `*`) eine
`webhook_deliveries`-Zeile an und setzt `processed_at`; `find_due_deliveries(now)` liefert fällige Zeilen;
`deliver_webhook(delivery_id)` sendet per POST:

```
Content-Type: application/json; charset=utf-8
X-Chopstr-Event: clip.rendered
X-Chopstr-Delivery: <delivery_id>
X-Chopstr-Attempt: 1
X-Chopstr-Signature: t=<unix>,v1=<hex(hmac_sha256(secret, "<t>.<body>"))>

{"created_at":"...","data":{"clip_id":"...","status":"rendered",...},"event":"clip.rendered","id":"<delivery_id>"}
```

Der Body ist bei jedem Versuch identisch (sortierte Schlüssel), nur `t` und `X-Chopstr-Attempt` ändern sich.
Empfänger prüfen wie `webhooks.verify()`: `t` innerhalb von 300 s, HMAC über `"<t>.<body>"`. Erfolg ist 2xx;
sonst erster Versuch plus fünf Wiederholungen mit Backoff 1, 5, 30, 120, 720 Minuten über `next_attempt_at`,
danach `failed`. Ziel-Hosts: nur https, kein privates oder lokales Netz (`residency.assert_webhook_host`,
`residency.webhook_client` ohne Redirects); in `APP_ENV=development` sind http und lokale Hosts erlaubt.
Kein EU-Zwang, weil keine Transkriptinhalte übertragen werden. Deaktivierte Endpunkte und gesperrte Hosts sind
sofort `failed`.

### Publishing (`internal_api.py`, `activities/publish.py`, `workflows/publish.py`)

Die Web-App legt `publications` an und startet `PublishWorkflow(publication_id)` (Workflow-ID
`publish-<id>`). Ablauf: `load_publication` → Timer bis `scheduled_for` → `publish_clip` → Timer 6 h, 48 h,
7 d → `fetch_metrics`. Signale `cancel` (nur vor dem Publish; setzt `scheduled` auf `failed` mit Hinweis) und
`reschedule(iso)`. Gates in `publish_clip`: Clip `rendered` (oder `exported`), Kandidat `accepted`,
Gast-Freigabe `approved` falls `clips.guest_approval_required`; AVV und Plan prüft die Web-App beim Anlegen.
Gesperrt oder vom Provider abgelehnt → `status = failed`, `error` deutsch, Outbox `publication.failed`; Erfolg →
`published`, `external_id`, `external_url`, `published_at`, Outbox `publication.published`, Decision Log
`publish` (actor `system`). Ist die Web-App nicht erreichbar, wird die Zeile `failed` mit Grund und die
Ausnahme weitergereicht (Temporal wiederholt dreimal, jeder Versuch schreibt ein `publication.failed`).

Interne Endpunkte (`APP_INTERNAL_URL`, Header `X-Internal-Secret`, über `residency.guarded_client`):

| Aufruf | Body | Antwort |
|---|---|---|
| `POST /api/internal/publish` | `{ publication_id }` | `{ status: "published" \| "failed", external_id, external_url, error }` |
| `POST /api/internal/metrics` | `{ publication_id, window: "6h" \| "48h" \| "7d" }` | `{ metrics: { views, likes, comments, shares, saves, follows, avg_watch_time_s, retention_curve } }`, nicht garantierte Felder `null` |
| `POST /api/internal/mail` | `{ to: [], subject, text, html? }` | `{ ok }` |

`fetch_metrics` schreibt `performance_feedback` (Upsert je Publikation und Fenster) und ergänzt
`publications.metrics.at_<window>`. Reward (Master These 1): `follows_per_1k = follows / views * 1000`,
`saves_per_1k` analog, `account_median_views` = Median der `views` der letzten 20 7d-Zeilen desselben Accounts
(gleiche `connection_id`, sonst gleiche Plattform ohne Verbindung), `outlier_score = views / Median`.
`reward = 0,5 * follows_norm + 0,3 * saves_norm + 0,2 * outlier_norm`; jede Kennzahl wird durch den
Account-Median derselben Kennzahl geteilt und auf 3 gedeckelt, ohne Historie gilt 1,0 (neutral). Fehlende
Metriken bleiben `null`, der Reward entsteht nur aus den vorhandenen Anteilen (Gewichte neu normiert), ohne
jede Kennzahl ist er `null`.

### Decision Log (`decision_log.py`, Grundsatz A3)

`decision_log.record(conn, workspace_id, decision_type, features, alternatives, chosen, actor_type, ...)`.
Geschrieben werden: `candidate_proposed` je Vorschlag (behalten oder verworfen mit Grund) und
`candidate_scored` je Kandidat (Rubrik-Scores, Gewichte, Struktur, Länge, Plattform, Sprecherzahl, Gates,
Flags) in `detect_candidates`; `hook_variant_shown` (Reihenfolge der fünf Muster) und `hook_selected`
(gewählte Variante plus vier Alternativen) aus `copy_engine.write_copy` (liegen in `CopyResult.decisions`,
Persistenz über `decision_log.record_copy_result`); `reframe_strategy` über
`decision_log.record_reframe_strategy(conn, workspace_id, clip_id, plan, override)`; `publish` in
`publish_clip`. `copy_engine.write_copy(..., pattern_order=learning.thompson_order(stats))` sortiert die
Varianten nach der Lernschleife (`order_from_learning` im Merkmal, Exploration bleibt sichtbar).

Noch einzuhängen in `activities/render.py` (Datei gehört Welle 5c): nach `_write_hook_version(...)` der Aufruf
`decision_log.record_copy_result(conn, src["workspace_id"], clip_id, copy, brand_profile_id=src.get("brand_profile_id"), source_id=source_id, candidate_id=cand["id"], platform=destination)`
und nach `render_plan.build_plan(...)` der Aufruf
`decision_log.record_reframe_strategy(conn, src["workspace_id"], clip_id, plan, override=clip.get("reframe_override"), source_id=source_id, candidate_id=cand["id"], brand_profile_id=src.get("brand_profile_id"))`.
Optional dazu `learning.update_hook_stats(conn, brand_profile_id, pattern, shown=1)` je Variante und
`chosen=1` für die gewählte; die nächtliche Neuberechnung liefert dieselben Zahlen auch ohne diese Aufrufe.

### Lernschleife (`learning.py`, `activities/learning.py`, `workflows/learning.py`)

`fit_rubric_weights(rows) -> { weights, n, r2 }`: Ridge-Regression (numpy, λ = 1) der fünf Scores (0 bis 1
skaliert) auf das Ziel `0,6 * Urteil + 0,4 * Reward` (accepted 1, rejected 0, edited 0,5; Reward auf 3
gedeckelt; ohne Reward nur das Urteil). Gewichte auf [0,05, 0,5] begrenzt und per Water-Filling auf Summe 1
normiert; unter 20 Entscheidungen `None`. `update_brand_weights(conn, brand_profile_id)` liest Kandidaten mit
Urteil des Markenprofils plus den besten 7d-Reward ihrer Clips, schreibt `brand_profiles.learned_weights =
{ weights, n, fitted_at, r2 }` (von `story_engine.resolve_weights` gelesen) und den Audit `learning.updated`.

Hook-Muster: `update_hook_stats(conn, brand_profile_id, pattern, shown, chosen, reward)` zählt inkrementell,
`rebuild_hook_stats` rechnet nächtlich aus `decision_log` (`hook_variant_shown`, `hook_selected`) und
`performance_feedback` (7d-Reward über `clips` zur höchsten `hook_versions.pattern`) neu und ist idempotent.
`thompson_order(stats, seed)` zieht je Muster Beta(chosen + 1, shown − chosen + 1), multipliziert mit dem
Reward-Mittel (1,0 ohne Daten, auf 3 gedeckelt) und liefert die Reihenfolge der fünf Muster; ungezeigte Muster
werden erkundet. `LearningWorkflow` läuft je Markenprofil mit mindestens einem Urteil
(`find_learning_profiles` → `learn_brand_profile`).

### Wochenreport (`activities/reports.py`, `workflows/reports.py`)

`build_weekly_report(workspace_id, week_start)`: 7d-Zeilen aus `performance_feedback`, deren Fenster in der
Woche [Montag, Montag + 7 Tage) abgeschlossen wurde (`fetched_at`); drei beste und drei schwächste Clips nach
`follows_per_1k`, je Clip eine Ursache aus den Decision-Log-Merkmalen (Struktur, Hook-Muster, Länge,
Plattform, Rubrik) und eine Änderung als deutscher Textbaustein (zu lang → kürzen; Hook unter 5 → stärkerer
Einstieg als Variante B; Muster nicht unter den besten → Muster des besten Clips testen). Ohne Daten enthält der
Bericht den Hinweis „keine Publikationen mit Metriken“. Gespeichert in `weekly_reports` (Upsert je Workspace
und Woche), Mail an owner und admin (`workspace_members` plus `users.email`) über `/api/internal/mail`; ein
Mailfehler verwirft den Bericht nicht (`sent_at` bleibt leer). `WeeklyReportWorkflow` läuft für alle
Workspaces mit `weekly_report_enabled`, `week_start` ist der Montag der Vorwoche.

Offene Punkte Phase 5 (Worker):

- Kein DNS-Auflösen vor der Webhook-Zustellung: `assert_webhook_host` prüft Schema, IP-Literale und
  Hostnamen, nicht die aufgelösten Adressen (DNS-Rebinding auf private Adressen bleibt möglich). Redirects
  sind abgeschaltet.
- `usage.threshold` (80 %, 100 %) und `guest_approval.decided` schreibt die Web-App in die Outbox; der Worker
  verteilt sie nur.
- Der Wochenreport bewertet die Woche über abgeschlossene 7d-Fenster, nicht über das Veröffentlichungsdatum.
- `hook_pattern_stats` werden nur nächtlich aus dem Decision Log gefüllt, solange die Aufrufe in
  `activities/render.py` (siehe oben) fehlen.

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

## Lokaler Testmodus (ohne Docker, Temporal, MinIO, GPU)

`python -m chopstr_worker.local_worker` ersetzt Temporal durch eine Polling-Schleife über die Datenbank und
ruft dieselben Activity-Funktionen (`run_*`) auf wie der Temporal-Worker; es gibt keine zweite Pipeline.
Dateien liegen im lokalen Ordner (`S3_ENDPOINT` leer, `LOCAL_STORAGE_DIR`), die Web-App legt Uploads unter
`chopstr-sources/uploads/<uuid><ext>` ab und setzt `sources.status = 'uploaded'`.

### Schritte

```bash
cd workers
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                 # pytest, ruff, imageio-ffmpeg (statisches ffmpeg mit libass und drawtext)
pip install faster-whisper              # CPU-ASR (CTranslate2); pyannote und torch sind nicht nötig
source scripts/local_env.sh             # bash oder zsh; setzt ENV und verlinkt ffmpeg/ffprobe nach .local/bin
export DATABASE_URL=postgres://chopstr@127.0.0.1:5499/chopstr   # falls abweichend, VOR dem source setzen
python -m chopstr_worker.local_worker --once        # ein Durchlauf, Exit-Code 1 bei Fehlern (für Skripte und Tests)
python -m chopstr_worker.local_worker --interval 3  # Dauerbetrieb, Stopp mit Ctrl-C nach dem laufenden Schritt
```

`scripts/local_env.sh` setzt (bereits gesetzte Werte bleiben): `DATABASE_URL`, `S3_ENDPOINT=`,
`LOCAL_STORAGE_DIR` (Default `workers/.local/storage`), `WORKER_WORK_DIR`, `LLM_PROVIDER=local-heuristic`,
`ASR_DEVICE=cpu`, `ASR_COMPUTE=int8`, `ASR_MODEL_DE` (siehe Modellwahl), `APP_INTERNAL_URL=http://localhost:3000`,
`RENDER_X264_PRESET=veryfast` und stellt `.local/bin` mit `ffmpeg` (aus `imageio-ffmpeg`, hat `subtitles` und
`drawtext`) und `ffprobe` (Homebrew oder PATH) vorn in den `PATH`. Der Homebrew-ffmpeg hat oft kein libass;
dann liegen Untertitel nur als SRT/VTT bei.

Was die Schleife je Durchlauf abarbeitet (Reihenfolge fest, je Zeile einzeln, älteste zuerst):

| Warteschlange | Bedingung | Aufruf |
|---|---|---|
| `sources` | `status = 'uploaded'` | `probe_and_extract` → `transcribe_de` → `diarize` → `heatmap` → `fuse_and_nlp` → `detect_candidates` (Ende: `ready`) |
| `clips` | `status = 'draft'` und Kandidat `human_verdict = 'accepted'` | `render_pack(candidate_id, "<platform>:<clip_id>")` |
| `deletion_jobs` | `status = 'queued'` | `delete_entity` |
| `publications` | `status = 'scheduled'`, `scheduled_for <= now` | `publish_clip`, nur wenn `APP_INTERNAL_URL` per TCP erreichbar ist, sonst Hinweis im Log und die Zeile bleibt fällig |
| Outbox | alle 60 s (`--outbox-every`) | `dispatch_outbox`, dann fällige `deliver_webhook` |

Fehler: der erste fehlgeschlagene Schritt setzt `sources.status = 'failed'` mit deutscher `status_message`
(`events.step` macht das für die meisten Schritte selbst, der Worker ergänzt es ohne Dublette), Clips stehen
auf `failed` mit `render_error`, Lösch-Jobs auf `failed` mit `error`. Zusätzlich merkt sich der Prozess jede
fehlgeschlagene ID, damit nichts endlos wiederholt wird; ein erneuter Versuch braucht einen Neustart und
den Status `uploaded` bzw. `draft`. Eine Quelle, die beim Abbruch (Ctrl-C) mitten in der Pipeline stand,
bleibt in ihrem Zwischenstatus (`transcribing`, `analyzing`, ...) und wird nicht automatisch weitergeführt:
Status per SQL auf `uploaded` zurücksetzen, die Zwischenergebnisse im Storage werden dann übersprungen
(idempotente Keys). Logs enthalten IDs, Schritte, Dauern und Zähler, keine Transkriptinhalte.

### Modellwahl (auf Hugging Face geprüft, Stand September 2026)

| Zweck | Modell-ID | Befund |
|---|---|---|
| `ASR_MODEL_DE` (Default in `local_env.sh`) | `cstr/whisper-large-v3-turbo-german-int8_float32` | Modellkarte: „int8 quantization from primeline/whisper-large-v3-turbo-german per ctranslate2-converter“; Dateien `model.bin`, `config.json`, `tokenizer.json`, `vocabulary.json`, `preprocessor_config.json`; Apache-2.0. Direkt mit faster-whisper ladbar, kein Transformers-Format. |
| Alternative ohne deutschen Fine-Tune | `deepdml/faster-whisper-large-v3-turbo-ct2` | Konvertierung von `deepdml/whisper-large-v3-turbo` (`ct2-transformers-converter ... --quantization float16`), mehrsprachig inklusive Deutsch, MIT, sehr verbreitet. Das Event `transcribe_de` trägt dann den Hinweis „Standard-Whisper statt deutschem Fine-Tune“. |
| Nicht direkt nutzbar | `primeline/whisper-large-v3-turbo-german` | Transformers/Safetensors (BF16), kein CTranslate2. Eigene Konvertierung (nicht ausgeführt): `pip install transformers ctranslate2` und `ct2-transformers-converter --model primeline/whisper-large-v3-turbo-german --output_dir models/whisper-turbo-german-ct2 --copy_files tokenizer.json preprocessor_config.json --quantization int8`, dann `ASR_MODEL_DE=<absoluter Pfad zu models/whisper-turbo-german-ct2>`. |

Weitere CT2-Konvertierungen des primeline-Modells existieren (`TheTobyB/whisper-large-v3-turbo-german-ct2`,
`beydogan/whisper-large-v3-turbo-german-ct2`, ...), sind aber ohne Lizenzangabe oder ohne `tokenizer.json`;
deshalb der `cstr`-Stand. Der erste Lauf lädt das Modell (`model.bin` 814 MB, passt zur turbo-Größe von 809M
Parametern in int8) in den Hugging-Face-Cache (`~/.cache/huggingface`).

### Grenzen

- CPU-ASR ist langsam: large-v3-turbo mit `int8` auf Apple Silicon braucht grob ein Drittel bis die Hälfte der
  Laufzeit der Aufnahme (gemessen: 49 s Sprache aus `say -v Anna` in 18 s inklusive Modell laden, 105 Wörter
  fehlerfrei; Render 9:16 mit Captions 4 s). Eine Stunde Podcast dauert also 20 bis 30 Minuten, Geduld.
- Sprechertrennung braucht `HF_TOKEN` und `pyannote.audio` (Extra `asr`, zieht torch). Ohne beides: ein
  Sprecher `SPEAKER_00`, Hinweis im Event, `stats.diarization = "skipped"`; bei `expected_speakers > 1` steht
  ein zweiter Hinweis dabei. Reframe `two_speakers` ist damit nicht möglich.
- `LLM_PROVIDER=local-heuristic`: Kandidaten, Rubrik und Copy kommen aus der Heuristik (`heuristic-v1`,
  `risk_flags` enthält `heuristic_only`). Kein Ersatz für ein Sprachmodell, nur zum Durchspielen der Pipeline.
- Publishing braucht die laufende Web-App mit `INTERNAL_API_SECRET`; Webhooks an `http://localhost` gehen nur
  in `APP_ENV=development`.
- Kein Temporal: keine Retries, keine Heartbeats, keine Schedules (Retention, Lernschleife, Wochenreport
  laufen hier nicht).

### Tests dazu

```bash
.venv/bin/python -m pytest -q tests/test_local_worker.py tests/test_diarize_fallback.py   # Fake-DB, ohne Modelle
.venv/bin/python -m pytest -q tests/test_asr_real.py                                     # echte CPU-Transkription (Marker network, macOS say -v Anna, lädt das Modell)
```

`tests/test_asr_real.py` spricht einen Satz mit `say -v Anna`, wandelt ihn per ffmpeg in 16-kHz-WAV und prüft,
dass „vierzig Prozent“ (oder „40 Prozent“) und „Preismodell“ im Transkript stehen; ohne `faster_whisper`, `say`
oder ffmpeg wird er übersprungen, ohne Netz beim ersten Lauf schlägt er mit klarer Meldung fehl.

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
| `outbox.py`, `activities/webhooks.py`, `workflows/outbox.py` | Outbox, Signatur, Backoff, Schedule `outbox-dispatch` | verdrahtet |
| `internal_api.py`, `activities/publish.py`, `workflows/publish.py` | Publishing über die Web-App, Metrik-Fenster, Reward | verdrahtet, Web-Endpunkte müssen existieren |
| `decision_log.py` | Decision Log aus Story-Engine, Copy-Engine, Publish | verdrahtet in `detect_candidates` und `publish_clip`; Copy und Reframe warten auf den Aufruf in `render.py` |
| `learning.py`, `activities/learning.py`, `workflows/learning.py` | Ridge-Fit, Hook-Statistik, Thompson, Schedule `learning-nightly` | verdrahtet |
| `activities/reports.py`, `workflows/reports.py` | Wochenreport, Schedule `weekly-report` | verdrahtet |
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

## Phase 5c: Folien-Crop, Schweizerdeutsch-Beta, Sovereign

- **Folien-Crop** (`pipeline/reframe.py`): `detect_slide_region(video, segments)` sucht mit OpenCV (Extra
  `vision`, kein Modell nötig) das größte Rechteck aus Rasterzellen mit geringer Bewegung und hoher Kantendichte,
  stabil über mindestens 60 % der abgetasteten Frames, mindestens 25 % der Bildfläche. Strategie `slide_pip`:
  Folie oben auf volle Breite (höchstens 55 % der Höhe), Sprecher unten als Bild-im-Bild nach der
  Talking-Head-Regel, Captions und Overlays in der Sprecherfläche. Automatisch ab `confidence >= 0,6`, sonst
  Fallback mit Hinweis; `clips.reframe_override` (`talking_head`, `two_speakers`, `neutral`, `slide_pip`) erzwingt
  eine Strategie je Clip, `slide_pip` ohne erkannte Folie legt das ganze Quellbild oben ab. Render-Plan:
  `reframe.slide_region {x, y, w, h, confidence}`, `reframe.pip {x, y, w, h}`, Shots mit `layout = "pip"`;
  `pipeline/render.py` baut dafür `split`, zwei `crop`, `scale`/`pad`, `vstack`. Ohne OpenCV bleibt alles wie in
  Phase 3; `activities/render.py` liest den Override tolerant (fehlt die Spalte, steht das in `notes`).
- **Schweizerdeutsch-Beta** (`pipeline/dach_nlp.py`): `detect_dialect(words)` liefert `{variant, confidence,
  markers}` über Lexika CH und AT (mindestens 2 gewichtete Treffer und 2 % Anteil, Sicherheit 1,0 ab 10 %,
  schwache Marker wie „eh“ zählen halb). `normalize_ch(word, protected_terms)` kennt nur sichere Entsprechungen
  (nöd, isch, chli, gsi, öppis, jetz, hät, wänn) und schreibt geschützte Begriffe nie um; `annotate(...,
  dialect="de-CH")` ergänzt `text_norm`, `text` bleibt das Original (Entscheidung P2). `fuse_and_nlp` schreibt
  `stats.dialect`, `stats.text_norm_count` und den Hinweis „Schweizerdeutsch erkannt, CH-Modell empfohlen (Beta)“
  ins Event, wenn die Quelle mit dem DE-Modell lief. Captions (`build_cards`, `to_ass`, `to_srt`, `to_vtt`,
  `cards_for`) nehmen `text_field="text" | "text_norm"` (Fallback `text`); der Render liest
  `brand_profiles.caption_style.caption_text_field` (Default `text`) und trägt `captions.text_field` nur bei
  `text_norm` in den Plan ein (Hashes bestehender Pläne bleiben stabil).
- **Sovereign** (`infra/docker-compose.sovereign.yml`, `docs/SOVEREIGN.md`): Overlay mit `selfhost-eu` über
  einen vLLM-Service (Modell nur aus `SELFHOST_LLM_MODEL`), `GLADIA_BASE_URL` aus der Umgebung, kein Bedrock,
  getrennte Services `worker` (cpu) und `worker-gpu` (gpu, NVIDIA-Reservierung), Web mit `BILLING_PROVIDER=manual`
  und `DEFAULT_TIER=sovereign`. `tests/test_sovereign_overlay.py` prüft, dass keine US-Hosts vorkommen und alle
  Overlay-Hosts den Residency-Guard passieren.
- Tests: `tests/test_slide_pip.py` (Rasterauswertung, Layout, Override-Pfade, Filtergraph, Medientest mit
  `ffmpeg -f lavfi`: links Raster, rechts Bewegung; die echte Erkennung läuft nur mit OpenCV, sonst prüft der Test
  den Override-Pfad), `tests/test_dialect_ch.py`, `tests/test_sovereign_overlay.py`.
