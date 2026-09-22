# chopstr Sovereign: Betrieb auf Hetzner

Stand: Phase 5c (September 2026). Dieses Dokument beschreibt, wie chopstr im Tarif Sovereign ohne US-Anbieter
in der Verarbeitungskette betrieben wird: Postgres, MinIO, Temporal, Redis, LanguageTool, CPU-Worker, GPU-Worker
und ein self-hosted Sprachmodell (vLLM) auf Hetzner-Servern in Deutschland oder Finnland. Grundlage ist das
Compose-Overlay `infra/docker-compose.sovereign.yml` über der Basisdatei `infra/docker-compose.yml`.

Was der Tarif verspricht (Master, Entscheidungsregister): kein Byte verlässt die EU, kein Subprozessor mit Sitz
oder Konzernmutter außerhalb der EU, der Residency-Guard im Worker blockiert jeden anderen Aufruf, bevor er das
Netz erreicht. Was noch fehlt, steht ehrlich am Ende (Mollie, SSO, Hochverfügbarkeit).

## 1. Architektur

| Host | Rolle | Empfehlung Hetzner | Dienste |
|---|---|---|---|
| `app` | Anwendung und Zustand | Dedicated oder Cloud CCX, NVMe, 64 GB RAM | Postgres 16, Redis, Temporal + UI, MinIO, tusd, LanguageTool, Web (Next.js), CPU-Worker |
| `gpu` | Modelle | GPU-Dedicated (z. B. GEX-Reihe) mit NVIDIA-Karte, 24 GB VRAM oder mehr | GPU-Worker (ASR, Diarisierung), vLLM |
| optional `backup` | Sicherungen | Storage Box oder Object Storage in Hetzner-Rechenzentren (EU) | `pg_dump`, `mc mirror` |

Kleine Installationen dürfen beides auf einem GPU-Host betreiben; dann startet das Overlay alle Dienste auf
einer Maschine. Für getrennte Hosts läuft auf `gpu` nur `worker-gpu` und `vllm` mit `TEMPORAL_ADDRESS`,
`DATABASE_URL`, `S3_ENDPOINT` auf den `app`-Host (privates Netz von Hetzner, vSwitch oder WireGuard; nie über
öffentliche IPs ohne TLS).

Datenflüsse:

- Upload: Browser → tusd → MinIO (`chopstr-sources`), Hook an die Web-App, Workflow in Temporal.
- Verarbeitung: Worker laden Originale aus MinIO, schreiben Ableitungen nach `chopstr-derived`, Zustand nach Postgres.
- Sprachmodell: Worker → `http://vllm:8000/v1` (OpenAI-kompatibel), Provider `selfhost-eu`. Alternativ
  `LLM_PROVIDER=mistral-eu` (Mistral AI, Frankreich); beide stehen auf `residency.NON_US_CHAIN`.
- ASR: `faster-whisper` (DE) und das CH-Modell aus `ASR_MODEL_CH` auf dem GPU-Worker. Fallback `gladia-eu` nur,
  wenn `GLADIA_BASE_URL` gesetzt ist und der Workspace den Fallback freigibt; leer = kein Fallback.
- Ausgehende Aufrufe: nur Hosts aus der Konfiguration (`S3_ENDPOINT`, `LANGUAGETOOL_URL`, `TEMPORAL_ADDRESS`,
  `SELFHOST_LLM_BASE_URL`, `GLADIA_BASE_URL`, `EGRESS_ALLOWLIST`). Webhooks (Phase 5a) dürfen beliebige
  https-Ziele des Kunden erreichen, ihre Payload enthält keine Transkripte.

## 2. Voraussetzungen

- Ubuntu 22.04 oder 24.04, Docker Engine 26 oder neuer mit Compose v2, auf dem GPU-Host zusätzlich NVIDIA-Treiber
  und `nvidia-container-toolkit` (`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` muss laufen).
- DNS und TLS: ein Reverse-Proxy (Caddy oder Traefik) vor `web:3000`, `tusd:1080` und der Temporal-UI (nur intern).
  Die Compose-Dateien veröffentlichen Ports auf `localhost`; die Firewall (Hetzner Cloud Firewall oder nftables)
  lässt von außen nur 80/443 zu.
- `.env` aus `.env.example` mit echten Geheimnissen: `S3_ACCESS_KEY`/`S3_SECRET_KEY`, `SESSION_SECRET`,
  `TUS_HOOK_SECRET`, `INTERNAL_API_SECRET`, `CREDENTIALS_KEY` (`openssl rand -base64 32`), `SMTP_URL` (EU-SMTP),
  `HF_TOKEN` (pyannote und gated Modelle), `SELFHOST_LLM_MODEL`.
- Modelle: `ASR_MODEL_DE` (Standard `primeline/whisper-large-v3-turbo-german`), `ASR_MODEL_CH` (CTranslate2-Ordner
  unter `workers/models`), YuNet-ONNX unter `workers/models/face_detection_yunet_2023mar.onnx` (sonst Reframe
  neutral, Folien-Crop braucht nur OpenCV), `SELFHOST_LLM_MODEL` als Hugging-Face-ID oder lokaler Pfad unter
  `SELFHOST_LLM_MODEL_DIR` (im Container `/models`). Das Overlay codiert keine Modell-ID; die Lizenz des
  gewählten offenen Modells gilt für den Betreiber und wird vor dem Go-live geprüft.

## 3. Installation

```bash
git clone <repo> /srv/chopstr && cd /srv/chopstr
cp .env.example .env && $EDITOR .env          # Geheimnisse, Modelle, APP_BASE_URL
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.sovereign.yml build
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.sovereign.yml up -d
npm ci && npm run migrate                    # Schema 0001 bis 0005
docker compose ... logs -f vllm              # wartet, bis "Application startup complete" erscheint
```

Danach:

- `python -m scripts.seed_dev` (Ordner `workers`) ist nur für Entwicklung. Für Kunden: Workspace in der Web-App anlegen
  (Login per Magic Link über EU-SMTP), `workspaces.tier = 'sovereign'` setzen (`DEFAULT_TIER=sovereign` im Overlay
  gilt für neu angelegte Workspaces), AVV in den Einstellungen annehmen.
- Der CPU-Worker startet mit `--ensure-schedules` und legt die Temporal-Schedules `retention-daily`,
  `outbox-dispatch`, `learning-nightly` und `weekly-report` an (Phase 4 und 5b).
- Prüfung: `docker compose ... exec worker python -c "from chopstr_worker import config, residency; print(sorted(residency.allowed_hosts(config.settings())))"`
  zeigt genau die Stack-Hosts. `tests/test_sovereign_overlay.py` prüft die Datei selbst.

Host ohne GPU (Demo, Abnahme): `--scale worker-gpu=0` und `vllm` weglassen (`LLM_PROVIDER=mistral-eu` oder
`local-heuristic`; die Heuristik ist kein Produktionsprovider, Entscheidung P4). ASR läuft dann auf der CPU
(`worker --queues cpu,gpu`), deutlich langsamer.

## 4. Backups

| Was | Wie | Häufigkeit | Aufbewahrung |
|---|---|---|---|
| Postgres (`chopstr`, `temporal`, `temporal_visibility`) | `docker compose ... exec -T postgres pg_dumpall -U chopstr \| zstd > /backup/pg-$(date +%F).sql.zst` | täglich 02:30 | 14 Tage, wöchentlich 8 Wochen |
| MinIO `chopstr-sources` | `mc mirror --overwrite local/chopstr-sources storagebox/chopstr-sources` | täglich | Lifecycle 30 Tage wie im Bucket |
| MinIO `chopstr-derived` | `mc mirror` wie oben | täglich | 90 Tage wie im Bucket |
| `.env`, Zertifikate, `workers/models` | verschlüsselt (age oder gpg) auf die Storage Box | bei Änderung | 3 Versionen |
| vLLM- und HF-Cache | kein Backup nötig (Modelle lassen sich neu laden) | | |

Ziel: Hetzner Storage Box oder Object Storage in einem EU-Rechenzentrum, Zugriff nur per SSH-Key oder
S3-Schlüssel des Backup-Nutzers. Backups enthalten Transkripte und Videos: gleiche Schutzstufe wie der Stack,
Löschfristen aus Abschnitt 6 gelten auch für Backups (Lifecycle im Backup-Bucket).

Wiederherstellung (geprobt, bevor der erste Kunde live geht): Stack stoppen, Postgres-Volume leeren,
`zstd -d < pg.sql.zst | docker compose ... exec -T postgres psql -U chopstr`, `mc mirror` zurück, Stack starten,
Temporal-Schedules mit `--ensure-schedules` neu anlegen, ein Testprojekt durchlaufen lassen.

## 5. Update-Pfad

1. Release-Notes lesen: Migrationen (`packages/schema/migrations`) sind vorwärts, nie rückwärts. Vor jedem Update ein Backup nach Abschnitt 4.
2. `git fetch && git checkout <tag>`; `.env.example` mit `.env` abgleichen (neue Variablen).
3. `docker compose ... build web worker worker-gpu` (vLLM-Image nur bei Bedarf anheben; `vllm/vllm-openai` mit
   fixer Version pinnen, sobald die Kombination aus Modell und Image im Blindtest abgenommen ist).
4. `npm run migrate` (idempotent, `schema_migrations`).
5. `docker compose ... up -d` (Rolling: erst Worker, dann Web). Laufende Temporal-Workflows setzen nach dem
   Neustart fort; Activities sind idempotent über Storage-Keys und Render-Hashes.
6. Nach dem Update: ein Testprojekt (Blindtest-Episode) durchlaufen lassen, `pipeline_events` auf `failed`
   prüfen, `job_costs` und `usage_periods` stichprobenartig vergleichen.

Rollback: vorherigen Tag auschecken, Images neu bauen, Datenbank aus dem Backup vor dem Update einspielen.
Ein Rollback ohne Datenbank-Restore ist nur möglich, wenn die Migration keine neuen Pflichtspalten eingeführt hat.

## 6. Löschkonzept

- Rohmaterial: Lifecycle 30 Tage im Bucket `chopstr-sources`, Ableitungen 90 Tage in `chopstr-derived`
  (`minio-init` legt die Regeln an). Der tägliche `RetentionWorkflow` (Schedule `retention-daily`, 03:00
  Europe/Vienna) löscht Quellen nach `delete_after` inklusive Transkripten, Kandidaten, Clips, Caption- und
  Hook-Versionen; jeder Lauf schreibt einen Löschnachweis (`deletion_jobs`, `audit_log`).
- Nutzeranfrage: „Projekt löschen“ oder Workspace-Löschung startet `DeletionWorkflow` sofort; Clips behalten eine
  Zeile mit `status = 'deleted'` und `deleted_at` als Nachweis, Dateien und Versionen sind weg.
- Backups: Lifecycle im Backup-Ziel spiegelt die Bucket-Fristen; Postgres-Dumps fallen nach 14 Tagen weg
  (wöchentliche nach 8 Wochen). Damit ist eine gelöschte Quelle spätestens nach 8 Wochen auch aus Sicherungen verschwunden.
- Modelle und Caches (HF, vLLM): enthalten keine Kundendaten. LLM-Antwort-Cache in Redis: Schlüssel aus Prompt-Hash,
  TTL 30 Tage (`CACHE_TTL_S`), wird beim Löschen eines Workspaces geleert (`redis-cli --scan --pattern 'llm:*' | xargs redis-cli del`).
- Logs: IDs, Dauern, Zähler, keine Transkriptinhalte; Docker-Logs mit `max-size 50m`, `max-file 5` rotieren.
- Beweis für den Kunden: Export des `audit_log` und der `deletion_jobs` je Workspace über die Einstellungen (Phase 4).

## 7. Betrieb und Überwachung

- Temporal-UI (`localhost:8080`, nur per SSH-Tunnel) zeigt hängende Workflows; `pipeline_events` mit `status = 'failed'`
  ist die Fehlerliste je Quelle.
- Sentry und OTel nur mit EU-gehosteten Endpunkten (`SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT`), ohne Transkriptinhalte.
- vLLM: `curl http://localhost:8000/v1/models` auf dem GPU-Host; `nvidia-smi` für VRAM. `VLLM_MAX_MODEL_LEN` und
  `VLLM_GPU_MEMORY_UTILIZATION` an Modell und Karte anpassen.
- Kosten: `job_costs` (GPU- und CPU-Sekunden, Speicher, Tokens) mit Preisen aus `GPU_EUR_PER_HOUR` und Co. für die
  Nachkalkulation je Workspace.

## 8. Was der Kunde bekommt

- AVV nach Art. 28 DSGVO (`docs/rechtliches/avv-2026-09.md`) mit Anlage Subprozessoren Tarif Sovereign
  (`docs/rechtliches/subprozessoren-2026-09.md`): Hetzner (Datenbank, Speicher, Worker, DE/FI), Mistral AI oder
  self-hosted Modell (FR/EU), Gladia (OVHcloud, FR) nur bei freigeschaltetem Fallback, EU-SMTP-Anbieter, Mollie
  (NL) für die Abrechnung, sobald umgesetzt. Keine Subprozessoren mit Sitz oder Konzernmutter außerhalb der EU.
- TOMs (`docs/rechtliches/toms-2026-09.md`), Löschkonzept (Abschnitt 6) und auf Wunsch den Nachweis aus dem
  Audit-Log.
- Residency-Nachweis: `tests/test_residency.py` (Sovereign-Workspace erreicht Bedrock nicht) und
  `tests/test_sovereign_overlay.py` (Overlay ohne US-Hosts) laufen in der CI; das Ergebnis kann dem Kunden als
  Testprotokoll beigelegt werden.
- Datenexport: Transkripte, Clips, Captions und Render-Pläne über die API `/api/v1` (Phase 5a) mit eigenem Schlüssel.

## 9. Offene Punkte (ehrlich)

- **Mollie** ist nicht umgesetzt: `BILLING_PROVIDER=manual` (Rechnung von Hand, Abo-Status in `subscriptions`).
  Bis dahin keine Kartenzahlung im Sovereign-Tarif.
- **SSO** (SAML oder OIDC gegen Entra ID oder Keycloak des Kunden) fehlt; Login per Magic Link über EU-SMTP.
- **Hochverfügbarkeit**: ein Host je Rolle, kein Postgres-Replikat, kein MinIO-Cluster. Ausfall bedeutet Restore
  aus dem Backup (Abschnitt 4). Für Kunden mit SLA ist das vor Vertragsschluss zu klären.
- **Gladia-Fallback** ist im Code vorbereitet, das Antwortformat gegen die aktuelle Gladia-API noch nicht verifiziert
  (Hinweis in `pipeline/transcribe.py`); ohne `GLADIA_BASE_URL` ist der Pfad abgeschaltet.
- **C2PA-Signatur** braucht `c2patool` und ein Zertifikat des Betreibers (`C2PA_SIGN_CERT`, `C2PA_PRIVATE_KEY`); ohne
  beides steht `provenance.c2pa = skipped` im Clip.
- **Trennung der Hosts** (app und gpu) ist im Overlay vorgesehen, aber nur der Ein-Host-Betrieb ist mit den
  Compose-Dateien so getestet; für zwei Hosts sind `DATABASE_URL`, `S3_ENDPOINT`, `TEMPORAL_ADDRESS` auf dem
  GPU-Host auf das private Netz zu setzen.
- **Modellauswahl** für vLLM ist bewusst offen (keine ID im Overlay). Die Abnahme des gewählten Modells erfolgt
  über die Blindtests (`docs/BLINDTEST.md`), inklusive Schweizerdeutsch-Beta (`eval/wer_eval.py` je Dialekt).
