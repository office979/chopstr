<p align="center">
  <img src="apps/web/public/brand/chopstr-wordmark-on-dark.svg" alt="chopstr" width="420">
</p>

# chopstr

Clipping-Tool für den DACH-Raum. Aus deutschsprachigen Langvideos (Podcasts, Interviews, Debatten,
Keynotes) entstehen priorisierte Short-Form-Clips, die **sinntreu geschnitten**, **erklärt**,
**ohne KI-Deutsch getextet**, **rechtlich für DE/AT/CH vorbereitet** und **in der EU verarbeitet** sind.
Die KI erzeugt Vorschläge, Scores, Belege und Render-Pläne. Ein Mensch gibt frei. Ein deterministischer
Renderer baut das Video.

Stand: **Phase 0 (Fundament) und Phase 1 (Deutsch hören)** sind gebaut. Kandidaten, Reframing,
Captions, Copy und Rendering (Phase 2 und 3) liegen als Module im Worker, hängen aber noch nicht in der
Workflow-Kette.

## Architektur

```
apps/web (Next.js, Lichtbruch-Design)           Upload (TUS) · Projektstatus (SSE) · Transkript-Editor · Markenprofil
        │
Postgres (RLS, Supabase eu-central-1 │ Hetzner)  +  S3-kompatibler Objektspeicher (EU, Lifecycle)  +  Redis
        │
Temporal (self-hosted, EU) ── ClipProjectWorkflow
   ├─ GPU-Queue  chopstr-gpu : transcribe_de ∥ diarize
   ├─ CPU-Queue  chopstr-cpu : probe_and_extract → heatmap → fuse_and_nlp → detect_candidates (Phase 2)
   ├─ ⏸  menschliche Freigabe (Signal, bis 14 Tage)
   └─ render_pack (Phase 3)
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
├─ workers/                  Python: Temporal-Worker, Pipeline (ASR, Diarisierung, dach_nlp, …), Eval, Tests
├─ packages/
│  ├─ schema/migrations/     Postgres-Schema mit RLS, Versionierung, Kostenlog, Audit-Log
│  ├─ prompts/               versionierte LLM-Prompts (name_vN.md)
│  └─ design/                Lichtbruch-Tokens (CSS + JSON)
├─ infra/                    docker-compose (Postgres, Redis, Temporal + UI, MinIO, tusd, LanguageTool, Worker, Web)
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
| Unit-Tests für Phase-0/1-Module grün | 101 Tests grün, `ruff` sauber (`workers/tests`, 22.09.2026). |
| Kein Aufruf außerhalb der EU (Test grün) | `workers/tests/test_residency.py` grün: Sovereign blockt Bedrock, Nicht-EU-Hosts werden vor dem Verbindungsaufbau abgewiesen. |
| UI erfüllt WCAG AA, Fallback ohne `backdrop-filter` | Umgesetzt in `apps/web/app/globals.css` und Komponenten. |
| README mit Setup, Env-Variablen, Architektur | Diese Datei. |

Migration und Row Level Security wurden gegen ein lokales Postgres 15 geprüft: Workspace A sieht nur eigene
Zeilen, ohne gesetzten Workspace-Kontext sieht die App-Rolle nichts. Die Web-App wurde zusätzlich im
Postgres-Modus durchgespielt: tusd-Hook (Secret, Rechte-Prüfung, Anlage der Quelle mit Audit-Einträgen),
SSE-Events, Transkript-Version 1 aus der Pipeline, Korrektur als Version 2 mit Sprechername und Übernahme
ins Marken-Wörterbuch. `npm run build` und `npm run lint` laufen fehlerfrei.

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
| 2 | Heatmap, LLM-Vorschlag, Rubrik, Story-Graph, Compose, Review-UI | Blindtest: Precision@10 > 0,5 |
| 3 | Reframing, Caption-Presets, Copy-Engine + Linter, LinkedIn-Paket, C2PA | Ein Klick → postbares Paket |
| 4 | Organisationen, Rollen, Freigaben, Gast-Links, Abrechnung nach Stunden, AVV, Lösch-Workflow | Pilot in der eigenen Agentur |
| 5 | Sovereign-Tarif, API + MCP-Server, Publishing, Lernschleife, Schweizerdeutsch-Beta | Erste zahlende Kunden |
