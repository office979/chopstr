# Datenvertrag Phase 5: Sovereign, API + MCP, Publishing, Lernschleife, Serien, Hook-A/B, Folien-Crop, Schweizerdeutsch-Beta

Migration 0005. Abnahme: erste zahlende Kunden außerhalb des Netzwerks. Drei Wellen:

| Welle | Inhalt |
|---|---|
| 5a | API-Schlüssel, öffentliche API `/api/v1`, Webhooks mit Zustellung, MCP-Server (`packages/mcp-server`) |
| 5b | Publishing-Connectoren mit Capability-Flags, Zeitplanung, Metrik-Abruf, Decision Log, Lernschleife, Wochenreport, Hook-A/B, Content-Serien |
| 5c | Folien-Crop (Bild-im-Bild), Schweizerdeutsch-Beta (Dialekterkennung, getrennte Ausgabe), Sovereign-Overlay für Compose, Dokumentation |

Grundsätze bleiben: kein Autopublishing ohne Freigabe, Residency-Guard, kein Lernen ohne Decision Log
(A3), Metriken nur so weit, wie ein Connector sie garantiert (Capability Flags, Master 8.2).

## 5a · API und MCP

### API-Schlüssel

`api_keys`: `id`, `workspace_id`, `name`, `key_prefix` (8 Zeichen sichtbar), `key_hash` (SHA-256 des
vollständigen Schlüssels `chp_live_<32 Bytes base64url>`), `scopes` (`read`, `write`, `publish`, `admin`),
`created_by`, `last_used_at`, `expires_at`, `revoked_at`. Anzeige des Klartexts nur einmal beim Anlegen.
Auth: Header `Authorization: Bearer chp_live_…`; `lib/api/auth.ts` löst den Workspace auf und setzt den
RLS-Kontext (Rolle `editor` für `write`, `admin` für `admin`, `reviewer` für `read`).

### Endpunkte `/api/v1` (JSON, Fehler `{ error: { code, message } }` auf Deutsch, Rate-Limit 600/min je Schlüssel)

| Methode | Pfad | Scope |
|---|---|---|
| GET | `/sources`, `/sources/{id}` | read |
| POST | `/sources` (`{ title, brand_profile_id, rights_status, rights_confirmed: true, brief, upload: "tus" \| "url" }`; bei `url` nur mit `rights_confirmed` und `source_owner`/`source_url`; Antwort enthält `upload_token` und `tus_endpoint`) | write |
| DELETE | `/sources/{id}` | write |
| GET | `/sources/{id}/transcript`, `/sources/{id}/candidates`, `/sources/{id}/clips`, `/sources/{id}/events` (SSE) | read |
| POST | `/candidates/{id}/verdict` (`{ verdict, reason, platforms }`), `/candidates/{id}/revise` | write |
| GET | `/clips/{id}` (mit Medien-URLs, Hook, Captions), `/clips/{id}/download` (302 auf signierte URL, 409 ohne Gast-Freigabe) | read |
| POST | `/clips/{id}/render`, `/clips/{id}/hooks` | write |
| POST | `/clips/{id}/guest-approval` (`{ guest_name, guest_email?, message? }` → `{ approval, link }`) | write |
| GET | `/candidates/{id}` (Kandidat mit Rubrik, Gates, Flags) | read |
| GET/POST | `/brand-profiles` | read/write |
| POST | `/clips/{id}/publish` (`{ connection_id, scheduled_for?, caption?, title? }`), GET `/publications/{id}` | publish |
| GET/POST/DELETE | `/webhooks` | admin |
| GET | `/usage` (aktueller Monat), `/me` (Workspace, Scopes) | read |

OpenAPI 3.1 unter `/api/v1/openapi.json` (aus einer zentralen Definition `lib/api/openapi.ts` erzeugt),
Docs-Seite `/entwickler` mit Schlüsselverwaltung (`api.manage` = admin) und Beispielen (curl, Python, MCP).
Antwortformen (der MCP-Client erwartet sie so): Listen als `{ sources: [...] }`, `{ candidates: [...] }`,
`{ clips: [...] }`, `{ publications: [...] }`; Einzelobjekte als `{ source }`, `{ candidate }`, `{ clip }`,
`{ hook }`, `{ publication }`, `{ approval, link }`; Medien-URLs am Clip unter `media: { video_url, poster_url, srt_url, vtt_url }`.

### Webhooks

`webhook_endpoints`: `id`, `workspace_id`, `url` (nur https, Host darf nicht privat sein), `secret`
(HMAC-SHA256, Header `X-Chopstr-Signature: t=…,v1=…`), `events` (Liste), `active`, `created_by`.
`webhook_deliveries`: `id`, `endpoint_id`, `event`, `payload`, `attempt`, `status` (`pending`, `delivered`,
`failed`), `response_code`, `next_attempt_at`, `delivered_at`. Ereignisse: `source.ready`,
`candidates.ready`, `clip.rendered`, `clip.failed`, `guest_approval.decided`, `publication.published`,
`publication.failed`, `usage.threshold` (80 %, 100 %). Zustellung im Worker: Activity `deliver_webhook`
(Residency: Ziel-Host muss nicht EU sein, aber Payload enthält keine Transkripte, nur IDs, Titel, Status,
URLs); Retry 5× mit Backoff (1 min, 5, 30, 120, 720). Ereignisquelle: Tabelle `outbox_events`
(`id`, `workspace_id`, `event`, `entity`, `entity_id`, `payload`, `created_at`, `processed_at`), die Web
und Worker beim Statuswechsel schreiben; `OutboxWorkflow` (Schedule alle 30 s) verteilt an Endpunkte.

### MCP-Server `packages/mcp-server`

Node-Paket (`@modelcontextprotocol/sdk`, stdio-Transport, optional Streamable HTTP), konfiguriert über
`CHOPSTR_API_URL` und `CHOPSTR_API_KEY`. Tools (Namen englisch, Beschreibungen deutsch):
`list_sources`, `get_source`, `create_source_from_url`, `get_transcript`, `list_candidates`,
`accept_candidate`, `reject_candidate`, `revise_candidate`, `list_clips`, `get_clip`, `render_clip`,
`write_hooks` (liefert Varianten, speichert manuelle Version), `request_guest_approval`, `publish_clip`,
`get_usage`. Resources: `chopstr://sources/{id}/transcript`, `chopstr://clips/{id}/render-plan`.
Jede schreibende Tool-Ausführung braucht `confirm: true` im Aufruf (keine stillen Aktionen). README mit
Claude-Desktop- und Claude-Code-Konfiguration. Tests mit einem gemockten API-Server.

## 5b · Publishing, Lernschleife, Serien, Hook-A/B

### Verbindungen und Capability Flags

`platform_connections`: `id`, `workspace_id`, `brand_profile_id`, `platform` (`tiktok`, `instagram`,
`youtube`, `linkedin`, `manual`), `account_label`, `external_account_id`, `credentials` (verschlüsselt mit
`CREDENTIALS_KEY`, AES-256-GCM, nie im Klartext in Logs), `capabilities` (JSON nach Master 8.2:
`views, likes, comments, shares, saves, avg_watch_time, retention_curve, follow_attribution, publish,
schedule`, Werte `true | false | "conditional" | "unknown"`), `status` (`connected`, `expired`, `revoked`),
`connected_by`, `expires_at`. OAuth-Flows je Plattform als Provider-Module (`lib/publishing/providers/*`)
mit `authorizeUrl`, `exchangeCode`, `refresh`, `publish`, `fetchMetrics`, `capabilities()`; App-Zugangsdaten
aus Env (`TIKTOK_CLIENT_KEY/SECRET`, `META_APP_ID/SECRET`, `YOUTUBE_CLIENT_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET`).
Ohne Zugangsdaten ist der Provider „nicht konfiguriert“ (UI-Hinweis); `manual` ist immer verfügbar:
Export herunterladen, selbst posten, Post-URL und Metriken von Hand eintragen. Plattform-API-Felder und
Limits sind vor Release gegen die aktuelle Originaldokumentation zu prüfen (Entscheidungsregister CON-007).

### Publikationen

`publications` erweitert: `connection_id`, `status` (`scheduled`, `publishing`, `published`, `failed`,
`manual`), `scheduled_for`, `caption`, `title`, `external_url`, `error`, `metrics_fetched_at`, `metrics`
(`{ at_6h: {...}, at_48h: {...}, at_7d: {...} }`, fehlende Metriken `null`). Gate: Clip `rendered`, Kandidat
`accepted`, Gast-Freigabe `approved` falls verlangt, AVV angenommen, Plan `features.publishing`. Worker:
`PublishWorkflow(publication_id)`: wartet bis `scheduled_for`, ruft `publish_clip` (Provider), dann
Timer 6 h / 48 h / 7 d → `fetch_metrics` → `performance_feedback`. Kein Autopublishing: jede Publikation
entsteht aus einer Nutzeraktion oder einem API-Aufruf mit Scope `publish`.

### Decision Log und Lernschleife (A3)

`decision_log`: `id`, `workspace_id`, `brand_profile_id`, `source_id`, `candidate_id`, `clip_id`,
`decision_type` (`candidate_proposed`, `candidate_scored`, `candidate_verdict`, `hook_selected`,
`hook_variant_shown`, `caption_preset`, `reframe_strategy`, `publish`), `features` (JSON: Rubrik-Scores,
Struktur, Länge, Plattform, Hook-Muster, Sprecherzahl, Gates, Flags), `alternatives` (JSON, verworfene
Optionen), `chosen` (JSON), `actor_type` (`ai`, `user`, `system`), `model_id`, `prompt_version`,
`created_at`. Web und Worker schreiben bei jeder dieser Entscheidungen.
`performance_feedback`: `id`, `workspace_id`, `clip_id`, `publication_id`, `platform`, `metric_window` (`6h`,
`48h`, `7d`, `manual`; Spalte heißt `metric_window`, weil `window` in Postgres reserviert ist), `views`, `likes`, `comments`, `shares`, `saves`, `follows`, `avg_watch_time_s`,
`retention_curve` (JSON), `follows_per_1k` (berechnet), `saves_per_1k`, `account_median_views` (Median
der letzten 20 Publikationen des Accounts), `outlier_score` (views / median), `fetched_at`.
Reward (Master These 1): `reward = 0.5 * follows_per_1k_norm + 0.3 * saves_per_1k_norm + 0.2 * outlier_norm`,
je Account normalisiert; Funnel-Gewichte per Plattform-Preset.
Lernen: `learning.py` (Worker) berechnet pro Markenprofil aus `candidates.human_verdict` (accepted = 1,
rejected = 0, edited = 0,5) und `performance_feedback` (reward) neue Rubrik-Gewichte: Ridge-Regression der
fünf Scores auf das Ziel, auf 0,05 bis 0,5 begrenzt, normalisiert auf Summe 1, nur ab 20 Entscheidungen,
Ergebnis in `brand_profiles.learned_weights` mit `{ weights, n, fitted_at, r2 }` und Audit `learning.updated`.
Hook-Muster: `hook_pattern_stats` (`brand_profile_id`, `pattern`, `shown`, `chosen`, `reward_sum`,
`reward_n`) für Thompson Sampling (Beta-Verteilung über Auswahlquote, plus Reward-Mittel) bei der
Reihenfolge der fünf Varianten im Hook-Studio; Exploration bleibt sichtbar („Vorschlag der Lernschleife“).
Wochenreport: `WeeklyReportWorkflow` (Schedule Montag 07:00 Europe/Vienna) je Workspace: 3 beste und 3
schwächste Clips nach Folgequote, je eine Ursache (aus Decision-Log-Features: Struktur, Hook-Muster, Länge)
und eine Änderung; gespeichert in `weekly_reports` (`id`, `workspace_id`, `week_start`, `report` JSON,
`sent_at`), Seite `/berichte`, E-Mail an owner/admin (opt-out in den Einstellungen).

### Hook-A/B

Aus dem Hook-Studio „Variante B anlegen“: zweiter Clip (`clips.experiment_id`, `variant` `A`/`B`) mit anderem
Hook (Overlay und Post-Text), gleiche Komposition. `experiments`: `id`, `workspace_id`, `candidate_id`,
`hypothesis`, `status` (`draft`, `running`, `decided`), `winner_clip_id`, `decided_at`, `min_exposure`
(Default 1.000 Views je Variante), `confidence` (posterior P(A > B) aus Beta-Verteilungen über Folgequote).
Entscheidung frühestens nach 48 h und Mindestexposure (Master 1.0: „nur mit Mindestexposure + Konfidenz“).
Seite `/experimente`.

### Content-Serien

`series`: `id`, `workspace_id`, `brand_profile_id`, `name`, `description`, `cadence` (`weekly`, `biweekly`,
`monthly`, `none`), `rules` (JSON: `structure`, `platforms`, `caption_preset`, `hook_patterns`,
`cover_template`), `active`. `clips.series_id`, `clips.series_index`. Variations-Prüfung (Whitepaper 3.4):
beim Zuordnen vergleicht die Web-App den Clip mit den letzten 9 Clips der Serie (Caption-Preset, Hook-Muster,
Struktur, Länge ±15 %); drei oder mehr gleiche Merkmale → Warnung „zu ähnlich, Variante ziehen“ (Orange).
Seite `/serien` mit Kalender nach `cadence` und Lücken.

## 5c · Folien-Crop, Schweizerdeutsch-Beta, Sovereign

### Folien-Crop

Reframe-Strategie `slide_pip`: `reframe.detect_slide_region(video, segments)` (OpenCV, optional) sucht ein
Rechteck mit geringer Bewegung und hoher Kantendichte über ≥ 60 % der Segmentdauer (Folie, Bildschirm);
Ergebnis `{ x, y, w, h, confidence }`. Layout: Folie oben (skaliert auf volle Breite), Sprecher-Crop als
Bild-im-Bild unten (Talking-Head-Regel), Captions in der Safe Zone unter der Folie. Ohne OpenCV oder
`confidence < 0,6` → Fallback `talking_head`/`neutral` mit Hinweis. Render-Plan `reframe.strategy = slide_pip`,
`slide_region`, `pip` `{ x, y, w, h }`. Nutzer kann die Strategie je Clip in der UI überschreiben
(`clips.reframe_override`).

### Schweizerdeutsch-Beta

`dach_nlp.detect_dialect(words) -> { variant: "de" | "de-AT" | "de-CH", confidence, markers }` über ein
Lexikon (CH: nöd, isch, chli, gsi, öppis, hoi, merci, velo; AT: heuer, Jänner, leiwand, eh, Sackerl,
Paradeiser). Bei CH-Erkennung ohne `asr_variant = de-CH`: Hinweis im Editor („Schweizerdeutsch erkannt,
CH-Modell empfohlen, Beta“). Getrennte Ausgabe (P2): `transcript_versions.words[].text_norm` (normalisierte
Hochdeutsch-Form nur, wenn das CH-Modell sie liefert oder das Lexikon eine sichere Entsprechung hat), Editor
mit Umschalter „Original / Standard“, Captions nutzen die gewählte Form; regionale Wörter in
`protected_terms` werden nie normalisiert. Eval `wer_eval` je Dialekt ist die Abnahme (`docs/BLINDTEST.md`).

### Sovereign

`infra/docker-compose.sovereign.yml` (Overlay): `LLM_PROVIDER=mistral-eu` oder `selfhost-eu` (vLLM-Service
mit offenem Modell, Modell-ID aus Env), `GLADIA_BASE_URL` für den ASR-Fallback, kein Bedrock, `BILLING_PROVIDER`
Mollie-Platzhalter (`manual` bis Mollie umgesetzt ist), Postgres und MinIO lokal (Hetzner). Residency-Test:
Sovereign-Workspace darf Bedrock nicht erreichen (existiert), plus Test, dass die Compose-Overlay-Env keine
US-Hosts enthält. `docs/SOVEREIGN.md` beschreibt Betrieb auf Hetzner (Postgres, MinIO, Temporal, GPU-Worker).

## Umgebungsvariablen (neu)

`CREDENTIALS_KEY` (32 Bytes base64), `API_RATE_LIMIT_PER_MIN=600`, `WEBHOOK_TIMEOUT_MS=8000`,
`TIKTOK_CLIENT_KEY/SECRET`, `META_APP_ID/SECRET`, `YOUTUBE_CLIENT_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET`,
`PUBLISH_REDIRECT_BASE` (= `APP_BASE_URL`), `WEEKLY_REPORT_CRON=0 7 * * 1`, `OUTBOX_INTERVAL_S=30`,
`CHOPSTR_API_URL`, `CHOPSTR_API_KEY` (MCP-Server).

## Interne Schnittstelle Worker ↔ Web (Publishing)

Die Provider-SDKs und OAuth-Flows leben in der Web-App (Node). Der Worker besitzt Zeitplanung, Retries und
Metrik-Fenster. Deshalb ruft der Worker interne Endpunkte der Web-App auf, authentifiziert über
`INTERNAL_API_SECRET` (Header `X-Internal-Secret`), Host aus `APP_INTERNAL_URL` (Compose: `http://web:3000`):

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| POST | `/api/internal/publish` | `{ publication_id }` | `{ status: "published" \| "failed", external_id, external_url, error }` |
| POST | `/api/internal/metrics` | `{ publication_id, window: "6h" \| "48h" \| "7d" }` | `{ metrics: { views, likes, comments, shares, saves, follows, avg_watch_time_s, retention_curve } }` mit `null` für nicht garantierte Felder (Capability Flags) |
| POST | `/api/internal/mail` | `{ to: [], subject, text, html? }` | `{ ok }` (Wochenreport, Löschbenachrichtigung) |

Der Worker schreibt `publications.status`, `performance_feedback` und den Reward; die Web-App schreibt
`publications` beim Anlegen und startet `PublishWorkflow(publication_id)` (Workflow-ID `publish-<id>`).
Residency: `APP_INTERNAL_URL` steht auf der Allowlist des Residency-Guards.

`OutboxWorkflow` (Schedule `outbox-dispatch`, alle `OUTBOX_INTERVAL_S` Sekunden): liest unverarbeitete
`outbox_events`, legt pro aktivem Endpunkt mit passendem Event eine `webhook_deliveries`-Zeile an und ruft
`deliver_webhook(delivery_id)`; Zustellung über `residency.guarded_client` mit ausdrücklicher Freigabe
beliebiger https-Hosts für Webhooks (Payload enthält keine Transkriptinhalte). Backoff 1, 5, 30, 120, 720 Minuten.

`WeeklyReportWorkflow` (Schedule `weekly-report`, Cron `WEEKLY_REPORT_CRON`): je Workspace mit
`weekly_report_enabled` Bericht bauen, in `weekly_reports` speichern, Mail über `/api/internal/mail`.
