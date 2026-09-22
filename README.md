<p align="center">
  <img src="apps/web/public/brand/chopstr-wordmark-on-dark.svg" alt="chopstr" width="420">
</p>

# chopstr

Clipping-Tool für den DACH-Raum. Aus deutschsprachigen Langvideos (Podcasts, Interviews, Debatten,
Keynotes) entstehen priorisierte Short-Form-Clips, die **sinntreu geschnitten**, **erklärt**,
**ohne KI-Deutsch getextet**, **rechtlich für DE/AT/CH vorbereitet** und **in der EU verarbeitet** sind.
Die KI erzeugt Vorschläge, Scores, Belege und Render-Pläne. Ein Mensch gibt frei. Ein deterministischer
Renderer baut das Video.

Stand: **Phase 0 bis 4 sind gebaut** (Fundament, Deutsch hören, Story-Engine und Review, Copy/Reframing/
Captions/Render/Provenienz, Auth/Rollen/Gast-Freigabe/Abrechnung/AVV/Löschung/CI-Manager). **Phase 5** (API + MCP,
Publishing, Lernschleife, Serien, Hook-A/B, Folien-Crop, Schweizerdeutsch-Beta, Sovereign) ist ebenfalls gebaut.
Alle sechs Phasen des Build-Prompts sind damit umgesetzt; was fehlt, ist Betrieb und Abnahme (siehe
`docs/RISIKEN-UND-RUECKFRAGEN.md`).

## Architektur

```
apps/web (Next.js, Lichtbruch-Design)           Upload · Projektstatus · Transkript-Editor · Kandidaten-Review · Clips + Hook-Studio · Markenprofil
        │
Postgres (RLS, Supabase eu-central-1 │ Hetzner)  +  S3-kompatibler Objektspeicher (EU, Lifecycle)  +  Redis
        │
Temporal (self-hosted, EU) ── ClipProjectWorkflow
   ├─ GPU-Queue  chopstr-gpu : transcribe_de ∥ diarize
   ├─ CPU-Queue  chopstr-cpu : probe_and_extract → heatmap → fuse_and_nlp → detect_candidates (Story-Engine)
   ├─ ⏸  menschliche Freigabe (Signal, bis 14 Tage)
   └─ render_pack : Copy (hooks_v1, post_caption_v1, Linter) → Reframe → Captions → ffmpeg → C2PA → Clip-Paket
        │
LLM über providers_llm (Residency-Guard, Cache, Kostenlog): Bedrock EU │ Mistral EU │ self-hosted
```

Verbindliche Entscheidungen (Kurzfassung, Details in `docs/ENTSCHEIDUNGEN.md`):

| Nr. | Entscheidung |
|---|---|
| E1 | Ein Code, zwei Tarife: `standard` (Claude über Bedrock EU, Supabase eu-central-1) und `sovereign` (nur EU-Anbieter). Residency-Guard blockt alles andere. |
| E2 | Temporal ab Phase 0 (kein RQ). Workflow-Historie enthält Transkripte, deshalb self-hosted in der EU. |
| E3 | Keine dritte Backend-Sprache: Produktschicht TypeScript (Next.js), Python nur in Temporal-Workern. |
| E4 | Hybride Clip-Erkennung: Heatmap → LLM-Vorschlag → Rubrik mit Reparatur → Story-Graph. |
| E6 | Clips sind Kompositionen (Segmentlisten), Teaser nur mit Trust-Regeln. |
| E7 | Eigenes deutsches NLP-Paket `dach_nlp` (Verbklammer, Modalpartikeln, Negationen, Open-Loop-Enden). |
| E8 | Lizenz-Hygiene: keine AGPL-Gewichte (YOLO). YuNet/MediaPipe. |
| E9 | Abrechnung nach Stunden Quellmaterial, keine Credits. |
| A1 | Audio-Default -16 LUFS / -1,5 dBTP (Master-Edition), -14 / -1 nur als Legacy-Preset. |

## Ordnerstruktur

```
chopstr/
├─ apps/web/                 Next.js App Router, TypeScript, Tailwind v4, Design „Lichtbruch“, Logo
├─ workers/                  Python: Temporal-Worker, Pipeline (ASR, Diarisierung, dach_nlp, Story-Engine, Render, Publishing, Lernschleife), Eval, Tests
├─ packages/
│  ├─ mcp-server/            MCP-Server für Claude, Claude Code und andere Agenten (15 Tools, Bestätigungspflicht)
│  ├─ schema/migrations/     Postgres-Schema mit RLS, Versionierung, Kostenlog, Audit-Log, Auth, Abrechnung, Publishing
│  ├─ prompts/               versionierte LLM-Prompts (name_vN.md)
│  └─ design/                Lichtbruch-Tokens (CSS + JSON)
├─ infra/                    docker-compose (Postgres, Redis, Temporal + UI, MinIO, tusd, LanguageTool, Worker, Web) + Sovereign-Overlay
├─ scripts/                  migrate.mjs
└─ docs/brand/               Logo-Originale und Markenassets
```

## Schnellstart (lokal)

Voraussetzungen: Docker, Node 20+, Python 3.11+ (für Tests ohne Docker), ffmpeg.

```bash
cp .env.example .env
docker compose --env-file .env -f infra/docker-compose.yml up -d
npm install
DATABASE_URL=postgres://chopstr:chopstr@localhost:5432/chopstr npm run migrate
npm run dev            # http://localhost:3000
```

Temporal-UI: http://localhost:8080 · MinIO-Konsole: http://localhost:9001 · tusd: http://localhost:1080/files/

**Ohne Docker** läuft die Web-App im Demo-Modus (kein `DATABASE_URL`): Seed-Projekte, ein deutsches
Beispieltranskript, simulierter Upload. So lässt sich die Oberfläche prüfen, bevor Infrastruktur steht.

```bash
cd apps/web && npm run dev
```

Worker-Tests ohne GPU und ohne Modelle:

```bash
cd workers && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pytest -q
```

## Lokaler Testmodus (ohne Docker, auf dem Mac)

Echter Durchlauf mit Upload, Transkription auf CPU, Kandidaten (Heuristik statt Sprachmodell), Review und Render:

```bash
scripts/local-stack.sh start            # Postgres unter .local/pgdata, Migrationen, Testnutzer dev@chopstr.local / chopstr-dev
cp scripts/local-env.example apps/web/.env.local   # LOCAL_STORAGE_DIR auf den absoluten Pfad zu .local/storage setzen
npm run dev                             # Web-App auf http://localhost:3000
```

Zweites Terminal, der Worker holt Uploads, Renders und Löschjobs ab:

```bash
cd workers && source scripts/local_env.sh && python -m chopstr_worker.local_worker
```

Beim ersten Lauf lädt der Worker das deutsche Whisper-Modell (rund 800 MB). Grenzen: Transkription auf CPU
dauert etwa so lange wie das Video, Sprechertrennung braucht `HF_TOKEN` plus `pyannote.audio` (sonst ein
Sprecher mit Hinweis), Kandidaten kommen aus dem Heuristik-Provider (kein Sprachmodell), Reframe neutral ohne
YuNet, kein C2PA ohne c2patool. Stoppen: `scripts/local-stack.sh stop`.

## Umgebungsvariablen

Alle Variablen mit Erklärung stehen in [`.env.example`](.env.example). Die wichtigsten:

| Variable | Zweck |
|---|---|
| `DATABASE_URL` | Postgres. Fehlt sie, läuft die Web-App im Demo-Modus. |
| `TEMPORAL_ADDRESS`, `TEMPORAL_TASK_QUEUE_CPU/GPU` | Temporal-Server und Queues. |
| `S3_ENDPOINT`, `S3_BUCKET_SOURCES`, `S3_BUCKET_DERIVED` | Objektspeicher (EU). Lokal MinIO. |
| `TUS_HOOK_SECRET`, `UPLOAD_MAX_BYTES` | Upload-Hooks und Größenlimit (5 GB). |
| `LLM_PROVIDER`, `BEDROCK_MODEL_ID`, `MISTRAL_*` | LLM-Provider hinter dem Residency-Guard. Keine Modell-IDs im Code. |
| `ASR_MODEL_DE`, `ASR_MODEL_CH`, `HF_TOKEN` | ASR-Modelle (faster-whisper) und pyannote-Zugang. |
| `EGRESS_ALLOWLIST` | zusätzliche erlaubte Hosts für ausgehende Worker-Aufrufe. |

## Definition of Done (Phase 0 + 1) und Status

| Kriterium | Status |
|---|---|
| `docker compose up` startet alles; Upload erscheint als Workflow in der Temporal-UI | Compose-Datei vorhanden. Auf dieser Entwicklungsmaschine ist kein Docker installiert, deshalb noch nicht als Ganzes gestartet. |
| 60-Min-Podcast wird transkribiert und diarisiert, Ergebnis im Editor korrigierbar | Pipeline und Editor gebaut. Echtlauf braucht GPU-Worker und Modelle (siehe `workers/README.md`). |
| WER auf Referenz-Set (Ziel Studio-Audio < 5 %) | `workers/eval/wer_eval.py` vorhanden; Referenzdaten fehlen noch. |
| Unit-Tests für Phase-0/1-Module grün | 264 Worker-Tests grün (Phase 0 bis 5, Medien-Regression mit ffmpeg), 53 MCP-Tests grün, `ruff` sauber (22.09.2026). |
| Kein Aufruf außerhalb der EU (Test grün) | `workers/tests/test_residency.py` grün: Sovereign blockt Bedrock, Nicht-EU-Hosts werden vor dem Verbindungsaufbau abgewiesen. |
| UI erfüllt WCAG AA, Fallback ohne `backdrop-filter` | Umgesetzt in `apps/web/app/globals.css` und Komponenten. |
| README mit Setup, Env-Variablen, Architektur | Diese Datei. |

Migration und Row Level Security wurden gegen ein lokales Postgres 15 geprüft: Workspace A sieht nur eigene
Zeilen, ohne gesetzten Workspace-Kontext sieht die App-Rolle nichts. Die Web-App wurde zusätzlich im
Postgres-Modus durchgespielt: tusd-Hook (Secret, Rechte-Prüfung, Anlage der Quelle mit Audit-Einträgen),
SSE-Events, Transkript-Version 1 aus der Pipeline, Korrektur als Version 2 mit Sprechername und Übernahme
ins Marken-Wörterbuch. `npm run build` und `npm run lint` laufen fehlerfrei.

**Phase 2 (Story-Engine)**: `detect_candidates` läuft real (Heatmap-Seeds → LLM-Vorschlag → Rubrik mit
Reparatur → deterministische Gates → Story-Graph mit Bestätigung), Datenvertrag in
`packages/schema/CANDIDATES.md`. Für Entwicklung und Demo gibt es den netzfreien Provider
`LLM_PROVIDER=local-heuristic` (kein Ersatz für ein Sprachmodell, Kandidaten tragen `heuristic_only`).
Die Review-Seite `/projekte/<id>/review` zeigt Rubrik mit Belegzitaten, Pflichtkriterien, Story-Graph und
bietet Annehmen, Ablehnen mit Grund, Verlängern, Kürzen und Titelkarte (Tastatur J/K/A/R). End-to-end
gegen Postgres geprüft: Engine mit Heuristik-Provider → 2 Kandidaten → Urteil und Revision über die API →
Audit-Log. Blindtest-Protokoll: `docs/BLINDTEST.md`.

**Phase 3 (Paket rendern)**: Annehmen im Review legt pro Zielplattform einen Clip an und sendet das
Freigabe-Signal; `render_pack` schreibt Hook-Version 1 (fünf Varianten, Linter, Claim-Check, Post-Texte
je Plattform), plant Reframe und Captions (Preset je Plattform, Safe Zones, Lesetempo), rendert mit ffmpeg
(Titelkarte, Hook-Overlay, eingebrannte Captions, zweistufiges Loudnorm -16 LUFS / -1,5 dBTP, Micro-Fades)
und schreibt Provenienz, Lautheit, Poster, SRT/VTT und den deterministischen `render_plan_v1`
(`packages/schema/CLIPS.md`). Web: Clip-Übersicht mit Export, Hook-Studio mit stummer Vorschau, CI im
Markenprofil. End-to-end gegen Postgres geprüft: Kandidat mit TikTok und LinkedIn angenommen, beide Clips
gerendert (1080×1920 und 1080×1350, je 17,6 s, -16,0 LUFS), manuelle Hook-Version 2 im Studio gespeichert,
Re-Render übernimmt sie. Frames zeigen Titelkarte, Overlay und Captions. Dabei behoben: Render-Geometrie kommt
jetzt immer aus ffprobe der echten Datei, nicht aus DB-Metadaten.

**Phase 4 (Pilot in der Agentur)**: eigene Auth (Argon2id, Sitzungen, Magic-Link), Registrierung mit Workspace,
Einladungen mit Rollen und Marken-Scope, signierte Upload-Token, Gast-Freigabe mit öffentlicher Seite und
Export-Sperre, Abrechnung nach Stunden (manual, Stripe-Webhook idempotent, Mollie vorgesehen), AVV/TOMs/
Subprozessoren mit Annahme, Lösch-Workflow mit Nachweis und Retention-Schedule, Datenexport als ZIP, CI-Manager
mit Font- und Logo-Upload, Markenprofil-Historie. Gegen Postgres durchgespielt (Registrierung, Einladung,
Rollen 403, Upload-Token, Gast-Entscheidung, Webhook-Signatur, AVV, Löschjob, Export, Font-Upload).

**Phase 5 (erste Kunden außerhalb des Netzwerks)**: API-Schlüssel mit Scopes, `/api/v1` (21 Pfade, OpenAPI 3.1),
Webhooks mit Outbox, HMAC-Signatur und Backoff, MCP-Server (`packages/mcp-server`, gegen die echte API geprüft),
Publishing-Verbindungen mit Capability-Flags (manual, TikTok, Instagram, YouTube, LinkedIn nach Doku),
PublishWorkflow mit Metrik-Fenstern, Decision Log, Reward je Account, Ridge-Lernschleife für Rubrik-Gewichte,
Thompson-Sampling für Hook-Muster, Hook-A/B-Experimente mit Posterior-Konfidenz, Content-Serien mit
Variations-Prüfung, Wochenreport, Folien-Crop als Bild-im-Bild, Schweizerdeutsch-Erkennung mit Original/Standard-
Umschalter, Sovereign-Compose-Overlay mit vLLM (`docs/SOVEREIGN.md`).

**ffmpeg-Hinweis**: Einbrennen von Captions, Titelkarte und Hook braucht ffmpeg mit `libass` und
`libfreetype`. Das Homebrew-ffmpeg auf der Entwicklungsmaschine hat beides nicht; der Worker erkennt das,
rendert ohne Overlays und meldet es im Event (`captions_burned = false`). Für Tests und lokale Renders liefert
das PyPI-Paket `imageio-ffmpeg` ein statisches ffmpeg mit libass (`pip install imageio-ffmpeg`, Binary in den
`PATH` verlinken). Das Docker-Image (`python:3.12-slim` + Debian-ffmpeg) bringt libass mit.

## Arbeitsregeln

- Kleine, überprüfbare Schritte. Nach jedem Schritt: was gebaut, wie getestet, was offen.
- Keine erfundenen APIs, Modell-IDs, Bibliotheksfunktionen oder Rechtsnormen. Unsicheres ist als TODO markiert.
- Keine Telemetrie mit Transkriptinhalten. Keine Kundendaten ins Training.
- Code-Bezeichner Englisch, Kommentare und UI-Texte Deutsch. Keine Gedankenstriche, keine Emojis, keine KI-Floskeln in UI-Texten.
- Prompts sind versioniert; jede Änderung läuft gegen den Testdatensatz, getrennt nach Dialekt.

## Roadmap

| Phase | Inhalt | Abnahme |
|---|---|---|
| 0 | Monorepo, Schema, Upload, Ingest, Temporal, Residency-Guard, Design-System | Workflow sichtbar |
| 1 | ASR, Diarisierung, dach_nlp, Transkript-Editor, Markenprofil, WER-Evaluation | < 5 % WER Studio-Audio |
| 2 | Heatmap, LLM-Vorschlag, Rubrik, Story-Graph, Review-UI (gebaut; Blindtest offen) | Blindtest: Precision@10 > 0,5 |
| 3 | Reframing, Caption-Presets, Copy-Engine + Linter, LinkedIn-Paket, C2PA (gebaut; YuNet und c2patool im Produktions-Image nachrüsten) | Ein Klick → postbares Paket |
| 4 | Organisationen, Rollen, Freigaben, Gast-Links, Abrechnung nach Stunden, AVV, Lösch-Workflow, CI-Manager (gebaut; Stripe Checkout ohne Konto ungetestet) | Pilot in der eigenen Agentur |
| 5 | Sovereign-Tarif, API + MCP-Server, Publishing, Lernschleife, Serien, Hook-A/B, Folien-Crop, Schweizerdeutsch-Beta (gebaut; Plattform-APIs ohne registrierte Apps ungetestet, vor Release gegen Originaldoku prüfen) | Erste zahlende Kunden |
