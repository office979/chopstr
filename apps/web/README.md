# @chopstr/web

Web-App von chopstr (Phase 0 bis 4B: Fundament, „Deutsch hören“, Kandidaten-Review, Clips mit Hook-Studio, Auth und Rollen,
Gast-Freigabe, Abrechnung, AVV, Löschung und CI-Manager).
Next.js 16 App Router, Tailwind v4, Design-System „Lichtbruch“ aus `packages/design`.

## Start

```bash
# vom Monorepo-Root
npm install
npm run dev        # http://localhost:3000, Demo-Modus ohne DATABASE_URL
npm run build      # Produktions-Build
npm run lint       # ESLint
```

Node 20 oder neuer. Fonts (Geist, Geist Mono) kommen self-hosted aus dem npm-Paket `geist`, keine externen CDNs.

## Umgebungsvariablen

Alle Variablen stehen in `.env.example` im Monorepo-Root. Für die Web-App relevant:

| Variable | Wirkung |
|---|---|
| `DATABASE_URL` | Postgres-Verbindung der App-Rolle. **Nicht gesetzt = Demo-Modus** (In-Memory-Repository mit Seed-Daten, fester Demo-Nutzer, kein Login). |
| `DATABASE_AUTH_URL` | Optional: Verbindung der Auth-Rolle `chopstr_auth` (BYPASSRLS) für users, sessions, login_tokens, Einladungs-Annahme und Registrierung. Fehlt sie, wird `DATABASE_URL` genutzt (Entwicklung). |
| `APP_ENV` | `development` (Default) oder `production`. Steuert `secure` am Sitzungs-Cookie und ob Mail-Links ohne SMTP in der Konsole landen. |
| `APP_BASE_URL` | Basis-URL für Links in E-Mails (Magic-Link, Reset, Einladung). Fehlt sie, wird sie aus den Request-Headern gebildet. |
| `SMTP_URL`, `MAIL_FROM` | SMTP-Versand über nodemailer (EU-Anbieter). Ohne `SMTP_URL` werden Nachricht und Link in der Serverkonsole ausgegeben, die UI zeigt „Link wurde in der Serverkonsole ausgegeben“. |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE_CPU` | Startet `ClipProjectWorkflow` nach dem Upload. Ohne Adresse oder im Demo-Modus wird nur geloggt. |
| `NEXT_PUBLIC_TUS_ENDPOINT` (Fallback `TUS_ENDPOINT`) | tusd-Endpoint für den Browser-Upload, Default `http://localhost:1080/files/`. |
| `TUS_HOOK_SECRET` | Secret für `/api/tus/hooks` (Header `Hook-Secret` oder Query `?secret=`). Nicht gesetzt: Hook wird mit Warnung angenommen (nur Entwicklung). |
| `UPLOAD_MAX_BYTES` | Upload-Limit, Default 5 GB. |
| `NEXT_PUBLIC_DEMO_UPLOAD=true` | Erzwingt den simulierten Upload auch mit Datenbank. |
| `NEXT_PUBLIC_MEDIA_BASE_URL` | Basis-URL für Medien aus dem `derived`-Bucket: 720p-Proxy im Editor sowie MP4, SRT, VTT und Poster auf der Clip-Seite (lokal MinIO `http://localhost:9000/chopstr-derived`). Ohne sie: simulierter Player und deaktivierte Export-Links. |
| `UPLOAD_MODE`, `NEXT_PUBLIC_UPLOAD_MODE` | `tus` (Default) oder `direct`: direkter Upload über `POST /api/uploads/direct` in `LOCAL_STORAGE_DIR` statt tusd (siehe „Lokaler Testmodus“). |
| `MEDIA_MODE`, `LOCAL_STORAGE_DIR` | `MEDIA_MODE=local` schaltet `GET /api/media/[...key]` frei, das Dateien aus `LOCAL_STORAGE_DIR/<bucket-name>/<key>` liefert; dazu `NEXT_PUBLIC_MEDIA_BASE_URL=/api/media`. `LOCAL_STORAGE_DIR` ohne S3 macht auch `lib/storage.ts` (CI-Assets) zum Dateispeicher. |
| `APP_VERSION` | Wird im Footer angezeigt. |
| `BILLING_PROVIDER` | `manual` (Default) oder `stripe`. Stripe braucht zusätzlich `STRIPE_SECRET_KEY`; ohne Schlüssel fällt die App auf `manual` zurück. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STARTER|PRO|AGENCY|SOVEREIGN` | Checkout-Session, Customer-Portal und Webhook-Signaturprüfung (`POST /api/billing/webhook`); Preis-IDs je Tarif. |
| `DPA_VERSION` | Version der Rechtstexte (Default `2026-09`), bestimmt die Dateien `docs/rechtliches/<name>-<version>.md` und `dpa_acceptances.dpa_version`. |
| `S3_ENDPOINT`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_DERIVED`, `S3_FORCE_PATH_STYLE` | Objektspeicher für CI-Assets (`derived`-Bucket, path-style, `@aws-sdk/client-s3`). Ohne S3-Konfiguration oder im Demo-Modus liegen Assets nur im Speicher des Serverprozesses. |
| `API_RATE_LIMIT_PER_MIN` | Rate-Limit der öffentlichen API je Schlüssel und Minute (Default 600, in-memory je Prozess; Header `X-RateLimit-Remaining`, `Retry-After`). |
| `INTERNAL_API_SECRET` | Secret für die internen Worker-Endpunkte `/api/internal/{publish,metrics,mail}` (Header `X-Internal-Secret`). Nicht gesetzt: nur in der Entwicklung erreichbar (Warnung), in Produktion 503. |
| `NEXT_PUBLIC_TUS_ENDPOINT` | Wird auch als `tus_endpoint` in `POST /api/v1/sources` (`upload: "tus"`) ausgegeben. |
| `CREDENTIALS_KEY` | 32 Bytes base64 (`openssl rand -base64 32`) für AES-256-GCM der Plattform-Zugangsdaten (`platform_connections.credentials`, Format `v1:<iv>:<tag>:<ciphertext>`). Nicht gesetzt: in der Entwicklung Klartext mit Präfix `plain:` und Warnung, in Produktion Fehler beim Speichern. |
| `TIKTOK_CLIENT_KEY/SECRET`, `META_APP_ID/SECRET`, `YOUTUBE_CLIENT_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET` | App-Zugangsdaten der Publishing-Provider. Fehlen sie, ist der Provider „nicht konfiguriert“ (Hinweis auf `/einstellungen/verbindungen`); `manual` ist immer verfügbar. Optional `META_GRAPH_VERSION`, `LINKEDIN_VERSION`, `TIKTOK_PRIVACY_LEVEL` (Default `SELF_ONLY`, bis die App den TikTok-Audit bestanden hat), `TIKTOK_PULL_FROM_URL=true` (verifizierte Domain), `YOUTUBE_PRIVACY_STATUS`, `PUBLISH_HTTP_TIMEOUT_MS`. |
| `PUBLISH_REDIRECT_BASE` | Basis der OAuth-Redirect-URIs `/api/publishing/oauth/<platform>/callback` (Default `APP_BASE_URL`, sonst die aufrufende Origin). |

Die Sitzung wird pro Transaktion als `app.workspace_id`, `app.actor_id` und (nur Rolle `client`) `app.brand_scope` gesetzt (`lib/db.ts`, via `set_config(..., true)` = `SET LOCAL`), damit die Row-Level-Security aus `packages/schema/migrations/0001_init.sql` und `0003_auth_billing.sql` greift. Zusätzlich filtern die Repository-Abfragen explizit nach `workspace_id` und Brand-Scope, weil die Entwicklungsverbindung Tabellen-Owner ist und RLS dort nicht greift.

## Lokaler Testmodus

Echtes Video hochladen und die Pipeline durchlaufen lassen, ohne Docker, tusd, MinIO und Temporal. Du brauchst nur Postgres (mit den Migrationen aus `packages/schema`), ffmpeg und die Python-Umgebung des Workers.

```bash
# Web-App (vom Monorepo-Root)
DATABASE_URL=postgres://chopstr@127.0.0.1:5432/chopstr \
UPLOAD_MODE=direct NEXT_PUBLIC_UPLOAD_MODE=direct \
MEDIA_MODE=local NEXT_PUBLIC_MEDIA_BASE_URL=/api/media \
LOCAL_STORAGE_DIR=$HOME/chopstr-store \
npm run dev --workspace apps/web

# Worker (in workers/, gleiche DATABASE_URL und LOCAL_STORAGE_DIR, kein S3_ENDPOINT, kein TEMPORAL_ADDRESS)
python -m chopstr_worker.local_worker
```

Was dabei passiert:

- **Upload**: Das Formular unter `/upload` schickt die Datei per `XMLHttpRequest` als `multipart/form-data` an `POST /api/uploads/direct` (Fortschritt über das Upload-Progress-Ereignis). Die Route prüft Rolle `source.upload`, Kontingent und Rechte-Checkbox wie `POST /api/uploads/token`, streamt die Datei nach `LOCAL_STORAGE_DIR/chopstr-sources/uploads/<uuid><ext>` (`lib/uploads/multipart.ts`, nichts liegt komplett im Speicher), berechnet nebenbei SHA-256 und legt die Quelle über `lib/uploads/finalize.ts` an (dieselbe Funktion wie `post-finish` im tusd-Hook: `sources` mit `storage_key`, `sha256`, `size_bytes`, `mime_type`, Audit `upload.created` und `rights.confirmed`). Ohne `TEMPORAL_ADDRESS` bleibt die Quelle `uploaded`; die Projektseite zeigt „Warte auf Worker“, bis der lokale Worker sie abholt. Der Bucket-Ordner `chopstr-sources` (beziehungsweise `S3_BUCKET_SOURCES`) ist derselbe, den der Python-Worker unter `LOCAL_STORAGE_DIR/<bucket-name>/<key>` liest (`workers/chopstr_worker/storage.py`).
- **Medien**: `GET /api/media/<key>` liefert Proxy, Audio, MP4, Poster, SRT und VTT aus `LOCAL_STORAGE_DIR/chopstr-derived/<key>` (das Original aus `chopstr-sources/`), mit Content-Type, `Accept-Ranges: bytes`, Range-Antworten (206) für das Scrubbing und `Cache-Control: private`. Berechtigt ist die Sitzung des Workspace, dem der Key gehört (`sources.storage_key|proxy_key|audio_key`, `clips.file_key|poster_key|srt_key|vtt_key`, sonst 404, ohne Sitzung 401). Die Gast-Freigabe `/freigabe/[token]` hängt `?t=<token>` an, das gegen `guest_approvals` geprüft wird (nur MP4 und Poster des freigegebenen Clips).
- **Editor und Review**: Sobald der Worker `proxy_key` gesetzt hat, spielen `VideoStage` (Transkript) und die Review-Seite das Proxy-Video über `<video src>`; `usePlayer` läuft synchron mit dem Element (currentTime per `requestAnimationFrame`, play/pause, seek). Vorher bleibt der simulierte Player.
- **Clips**: Karten zeigen das Poster und spielen das gerenderte MP4 per Klick ab; die Ton-aus-Vorschau zeigt bei fertigem Render die echte Datei stumm in Schleife. MP4-, SRT- und VTT-Links laufen über `GET /api/projects/[id]/clips/[clipId]/download`, das auf `/api/media/...` umleitet.
- **Render ohne Temporal**: `POST /api/projects/[id]/clips/[clipId]/render` und das Annehmen im Review setzen den Clip auf `draft` (`render_error = null`), wenn kein Signal zugestellt wurde; der lokale Worker rendert Clips mit `status = 'draft'`. Die UI meldet „Render eingeplant, lokaler Worker holt ab“. Löschjobs bleiben `queued` und werden ebenfalls vom lokalen Worker ausgeführt.

Prüfen per curl (Sitzungs-Cookie `chopstr_session` aus dem Browser):

```bash
ffmpeg -f lavfi -i testsrc=size=1280x720:rate=25 -f lavfi -i sine=frequency=440 -t 20 -pix_fmt yuv420p test.mp4
curl -b "chopstr_session=<id>" -F title=Test -F rights_status=own -F rights_confirmed=true -F file=@test.mp4 http://localhost:3000/api/uploads/direct
curl -b "chopstr_session=<id>" -H "Range: bytes=0-99" -I http://localhost:3000/api/media/renders/<clip>/<hash>.mp4
```

## Auth, Sitzungen und Rollen (Phase 4, Block A)

Vertrag: `packages/schema/PHASE4.md`, Abschnitte 1 bis 3 und 9. Eigene Auth-Schicht, tarifunabhängig (kein Supabase-Auth).

- **Passwörter**: Argon2id über `@node-rs/argon2` (m = 65536, t = 3, p = 4), PHC-String in `users.password_hash` (`lib/auth/password.ts`). Mindestens 10 Zeichen, Buchstaben und eine Ziffer.
- **Sitzungen**: Zeile in `sessions` (ID 32 Bytes base64url), Cookie `chopstr_session` (httpOnly, sameSite lax, secure außerhalb development, 30 Tage). Gleitende Verlängerung: `expires_at` wird nach frühestens einem Tag neu gesetzt (`lib/session.ts`), das Cookie erneuert `proxy.ts` bei jedem Request. `sessions.workspace_id` ist der aktive Workspace; `/workspaces` wechselt ihn.
- **Magic-Link, Passwort-Reset, E-Mail-Bestätigung**: `login_tokens` mit `purpose`, 15 Minuten, einmalig (`consumeLoginToken`). Die Links werden erst per Button eingelöst (Server Action), damit Mail-Scanner das Token nicht verbrauchen. Seiten: `/magic/[token]`, `/passwort` und `/passwort/[token]`, `/verifizieren/[token]`.
- **Rate-Limit**: 5 Anmeldeversuche pro 15 Minuten je E-Mail und je IP, in-memory (`lib/auth/rate-limit.ts`, TODO Redis für mehrere Instanzen).
- **`lib/session.ts`**: `getSession()` liest Cookie → Sitzung → Nutzer → Mitgliedschaft und liefert `{ userId, email, displayName, workspaceId, role, brandScope, … }` oder null (pro Request gecacht). `requireSession()` leitet auf `/anmelden?next=…` um (mit Login, aber ohne Workspace auf `/workspaces`). `requireRole(action)` wirft `ForbiddenError` (403, deutsche Meldung) für Server Actions; `requirePageRole(action)` leitet Seiten auf `/verboten?aktion=…` um. `withSessionContext(session, fn)` setzt die Sitzung explizit (tusd-Hook mit Upload-Token). Route-Handler nutzen `requireApiSession()` / `requireApiRole(action)` aus `lib/auth/guard.ts` (401/403 als JSON).
- **Rollen**: Matrix in `lib/auth/permissions.ts` (`can(role, action)`), Aktionen u. a. `source.upload`, `transcript.edit`, `candidate.verdict`, `hook.edit`, `clip.render`, `brand.edit`, `members.manage`, `workspace.update`, `audit.read` sowie für Block B bereits `billing.manage`, `dpa.accept`, `source.delete`, `workspace.delete`, `brand.assets`, `guest_approval.request`, `export.read`. `client` ist an `workspace_members.brand_profile_id` gebunden und sieht nur Quellen seiner Marke (RLS `app.brand_scope` plus Repository-Filter). Die Pill-Navigation blendet Upload und Markenprofil für `reviewer` und `client` aus.
- **Datenbank-Rollen**: `withContext(session, fn)` (App-Rolle `chopstr_app`, RLS) und `withAuthContext(fn)` (Auth-Rolle `chopstr_auth`, BYPASSRLS, ohne Mandantenkontext) in `lib/db.ts`. In Produktion beide über eigene URLs trennen (`DATABASE_URL`, `DATABASE_AUTH_URL`); `scripts/migrate.mjs` legt die Rollen an. In der Entwicklung ist die Verbindung Owner, die Trennung ist dokumentiert, nicht erzwungen.
- **`proxy.ts`** (Next 16, früher `middleware.ts`): leitet ohne Cookie auf `/anmelden` um, `/api/*` antwortet 401. Öffentlich: `/anmelden`, `/registrieren`, `/passwort`, `/magic/*`, `/einladung/*`, `/verifizieren/*`, `/freigabe/*`, `/rechtliches/*`, `/api/tus/hooks`, `/api/auth/*`, `/api/billing/webhook`. Im Demo-Modus keine Umleitung. Setzt `x-chopstr-path` für `?next=`.
- **Demo-Modus** (ohne `DATABASE_URL`): fester Demo-Nutzer „Demo“ (owner) ohne Login, Seed mit drei Mitgliedern (owner, editor, client mit Marke), Einladungen und Sitzungen in-memory; Anmeldeseiten zeigen einen Hinweis.

### Upload-Token

`POST /api/uploads/token` (Rolle editor oder höher) liefert `upload_token = base64url(payload).signature` mit `payload = { workspace_id, user_id, brand_profile_id, exp }` (1 Stunde) und HMAC-SHA256 über `TUS_HOOK_SECRET` (`lib/auth/upload-token.ts`). Kontingent-Gate (`lib/billing/quota.ts`): `usage_periods` und `subscriptions` mit `plans.included_hours`; bei `used >= included` ohne Mehrverbrauch antwortet die Route 402 „Stundenkontingent ausgeschöpft“. Regel ohne eigene Spalte: `trialing` → kein Mehrverbrauch, `active` → Mehrverbrauch erlaubt; ohne `subscriptions`-Zeile gilt der Plan aus `workspaces.plan` wie im Test. Der Upload-Client hängt das Token als tus-Metadatum `upload_token` an; `pre-create` prüft Signatur, Ablauf, Rolle und Kontingent, `post-finish` nimmt `workspace_id`, `user_id` und `brand_profile_id` aus dem Token (kein Session-Fallback mehr).

### Seiten und Routen (Block A)

| Route | Inhalt |
|---|---|
| `/anmelden` | E-Mail + Passwort, „Magic-Link senden“, „Passwort vergessen“. `?next=` nur relative Pfade. |
| `/registrieren` | Name, E-Mail, Passwort, Firma → Nutzer, Workspace (Name = Firma, Slug aus dem Namen), Mitgliedschaft `owner`, Standard-Markenprofil, `subscriptions` starter trialing 14 Tage, `usage_periods` für den Monat; Bestätigungsmail. |
| `/einladung/[token]` | Einladung annehmen: angemeldet per Button (Mitgliedschaft mit Rolle und Marke, `accepted_at`, Workspace-Wechsel), sonst Registrierung mit der E-Mail aus der Einladung. |
| `/workspaces` | Mitgliedschaften mit Rolle, Wechsel setzt `sessions.workspace_id`. |
| `POST /abmelden` | Sitzung löschen, Cookie leeren. |
| `/profil` | Anzeigename, E-Mail (Änderung setzt die Bestätigung zurück und sendet einen Link), Sprache. |
| `/einstellungen` | Allgemein: Name, Slug (read-only), Tarif (read-only), Datenregion, Aufbewahrung (owner, admin); Kontingent und Datenschutz lesend. |
| `/einstellungen/mitglieder` | Liste mit Rolle und Marke, Einladen per E-Mail mit Rolle und optional Marke (`workspace_invites`, Mail oder Konsolen-Link, 7 Tage), Rolle ändern, entfernen (owner nicht entfernbar, admin ändert keine admins), offene Einladungen zurückziehen. |
| `/einstellungen/sicherheit` | Aktive Sitzungen des Nutzers mit Abmelden und „Alle anderen abmelden“, Passwort ändern (beendet andere Sitzungen). |
| `/einstellungen/audit` | Audit-Log (owner, admin): Filter Aktion, Akteur, Zeitraum; 50 pro Seite; `GET /api/audit.csv` (Semikolon, BOM, bis 10.000 Zeilen, gleiche Filter). |
| `/verboten` | 403-Seite für Seitenaufrufe ohne passende Rolle. |
| `POST /api/uploads/token` | Upload-Token, siehe oben. |

Alle bestehenden Route-Handler und Server Actions prüfen die Rolle: Transkript `transcript.edit`, Kandidaten-Revision `candidate.edit`, Urteil `candidate.verdict`, Hook-Studio `hook.edit`, Re-Render `clip.render`, Markenprofil `brand.edit`, Upload `source.upload`; lesende Routen brauchen eine Sitzung.

## Gast-Freigabe, Abrechnung, AVV, Löschung, CI-Manager (Phase 4, Block B)

Vertrag: `packages/schema/PHASE4.md`, Abschnitte 4 bis 8. Repository-Methoden in `lib/repo/types.ts` (`BlockBRepo`), Postgres und Demo.

- **Gast-Freigabe** (`lib/guest/`): „Gast-Freigabe anfordern“ auf der Clip-Karte und im Hook-Studio (Rolle `guest_approval.request`, Plan-Gate `plans.features.guest_approval`, sonst Hinweis mit Link zur Abrechnung). Dialog mit Name, E-Mail (optional), Nachricht → `guest_approvals` (Token 32 Bytes base64url, 14 Tage), `clips.guest_approval_required = true`, E-Mail über `lib/auth/mail.ts` oder Konsole, Link zum Kopieren, Audit `guest_approval.requested`. Öffentliche Seite `/freigabe/[token]` (ohne Login, `proxy.ts` gibt `/freigabe/*` und `/api/freigabe/*` frei): Poster oder Video über `NEXT_PUBLIC_MEDIA_BASE_URL`, sonst Platzhalter; Titel, On-Screen- und gesprochener Hook, Post-Text, Plattform, Nachricht; Freigeben, Änderungen wünschen (Kommentar Pflicht), Ablehnen (Kommentar Pflicht) → `decision`, `comment`, `decided_at`, `viewed_at`, Audit `guest_approval.decided` (actor_type guest, IP). Abgelaufen oder entschieden zeigt eine klare Meldung. Clip-Karte zeigt den Status (ausstehend orange, freigegeben, Änderungen, abgelehnt); Export-Links laufen über `GET /api/projects/[id]/clips/[clipId]/download?kind=mp4|srt|vtt|poster`, die Route antwortet 409, solange `guest_approval_required` ohne `approved` ist, sonst 302 auf die Medien-URL (MP4 setzt den Clip auf `exported`, Audit `export.created`).
- **Abrechnung** `/einstellungen/abrechnung` (Rolle `billing.manage`): Tarif aus `plans`, Status (Testphase mit Testende, Aktiv, Zahlung überfällig, Gekündigt), Zeitraum, Verbrauchsbalken in Stunden (`usage_periods` des Monats, `period_end` inklusiv), lineare Prognose auf das Monatsende, Mehrverbrauch in € (`lib/billing/format.ts`, DACH-Format), Planvergleich, Rechnungsadresse (Server Action → `subscriptions.billing_address`), Verlauf vergangener Monate, Kündigung zum Periodenende. Provider-Abstraktion `lib/billing/provider.ts`: `manual` (Planwechsel schreibt `subscriptions.plan_code`, Hinweis „Rechnung per E-Mail“) und `stripe` (Checkout-Session mit `STRIPE_PRICE_<PLAN>`, Abo-Umstellung mit Proration, Customer-Portal, Kündigung über das SDK). Routen: `POST /api/billing/plan` (`{ plan_code }` oder `{ cancel_at_period_end }`), `POST /api/billing/checkout` (nur Stripe, sonst 409), `GET /api/billing/portal`, `POST /api/billing/webhook` (Signatur `t=…,v1=HMAC-SHA256(t.body)` mit `STRIPE_WEBHOOK_SECRET`, 5 Minuten Toleranz; Ereignisse `checkout.session.completed`, `customer.subscription.updated|deleted`, `invoice.paid|payment_failed` → `subscriptions`, `billing_events` idempotent über `provider_event_id`, Duplikat antwortet `{ duplicate: true }`; Workspace aus `metadata.workspace_id`/`client_reference_id`, sonst über Kunden- oder Abo-ID). Audit `billing.plan_changed`, `billing.checkout_started`, `billing.cancel_requested|revoked`, `billing.address_updated`, `billing.webhook` (system).
- **AVV und Rechtsseiten** `/rechtliches/avv|toms|subprozessoren` (öffentlich): Markdown aus `docs/rechtliches/*-<DPA_VERSION>.md`, beim Serverstart per `fs` gelesen (`lib/legal/docs.ts`, Pfad relativ zum Monorepo, Hinweis wenn die Datei fehlt), eigener Renderer `lib/legal/Markdown.tsx`. Platzhalter `[Firma des Kunden]`, `[Vertreter]`, `[Aufbewahrung …]`, `[Datum]`, IP und Version kommen aus Workspace, Rechnungsadresse und Annahme; Subprozessor-Liste je Tarif (`?tarif=standard|sovereign|alle`), Banner „Vorlage, juristisch zu prüfen“, Druckansicht (`@media print` in `globals.css`). Annahme (Rolle `dpa.accept`) über Firma, Vertreter, Checkbox → `POST /api/dpa/accept` → `dpa_acceptances` (Version, IP), `workspaces.dpa_signed_at`, Audit `dpa.accepted`. Ohne Annahme zeigt `PageShell` owner/admin ein dezentes Banner „AVV noch nicht angenommen“.
- **Löschung und Export**: „Löschen“ auf Projektseite und Projektliste (Rolle `source.delete`, kurze Rückfrage im Dialog, kein Eingabefeld) → `DELETE /api/projects/[id]` (`{ confirm_title }`; die Oberfläche schickt den Titel selbst mit, genauso wie `app/api/v1/sources/[id]`) → `sources.status = 'deleted'`, `deleted_at`, `deletion_jobs` (`entity = source`, `reason = user_request`, `requested_by`), Audit `source.delete_requested`, dann `startDeletionWorkflow(job_id)` in `lib/temporal.ts`: `DeletionWorkflow` mit ID `deletion-<job_id>` auf `TEMPORAL_TASK_QUEUE_CPU`, Argument `[{ job_id }]`. Ohne Temporal bleibt der Job `queued` (UI „Löschung eingeplant, Nachweis folgt“), der tägliche `RetentionWorkflow` holt ihn ab; mit Temporal „Löschung läuft“. Clip löschen analog (`DELETE /api/projects/[id]/clips/[clipId]`, `entity = clip`). Gelöschte Quellen und Clips filtern `listSources`, `getSource`, `listClips`, `getClip`, `countClips` (`status <> 'deleted'`). Seite `/einstellungen/loeschung`: Lösch-Aufträge mit Status und Nachweis (`keys_deleted`, `rows_deleted`), Workspace-Löschung (owner, 30 Tage Karenz → `deletion_requested_at`, `deletion_scheduled_for`, E-Mail oder Konsole, Audit `workspace.delete_requested`, Widerruf `workspace.delete_canceled`, Banner in `PageShell`), Datenexport `GET /api/export` (Rolle `export.read`): ZIP (`fflate`) mit JSON je Tabelle (workspaces, brand_profiles, brand_assets, brand_profile_versions, sources, transcript_versions, candidates, clips, hook_versions, caption_versions, guest_approvals ohne Token, audit_log, job_costs, usage_periods, subscriptions ohne Provider-IDs, dpa_acceptances, deletion_jobs) und `media-keys.json`, Audit `workspace.exported`.
- **CI-Manager** in `/marke`, Karte „Assets“: Upload Fonts (TTF/OTF/WOFF2, max. 5 MB; Familienname und Gewicht über `fontkit`, Fallback Dateiname), Logo (SVG/PNG, max. 2 MB), Bauchbinden-Hintergrund; Lizenz-Checkbox Pflicht (Text im Audit `brand.asset_uploaded`). `POST /api/brand/[id]/assets` (multipart `file`, `kind`, `license`) → `lib/storage.ts` (`derived`-Bucket, Key `brand/<profile>/<kind>/<sha>.<ext>`, S3 path-style oder In-Memory), Zeile in `brand_assets`; `GET /api/brand/[id]/assets/[assetId]` streamt die Datei für Vorschauen (Font per `@font-face`, Logo als Bild); `DELETE` mit `{ asset_id }` löst Verweise im CI (mit Snapshot) und entfernt Objekt und Zeile (Audit `brand.asset_deleted`). Auswahl Primär-/Sekundärfont, Logo und Wasserzeichen wird mit „Speichern“ nach `brand_profiles.ci` geschrieben: `fonts.primary_asset_id`, `secondary_asset_id`, `fallback: "Inter"`, `logo_asset_id`, `watermark.enabled`, `lower_third`, `hook_overlay` (der Worker liest genau diese Felder). Die stumme Vorschau (Clips, Hook-Studio) lädt den Primärfont per `@font-face` (`lib/brand/preview-font.ts`).
- **Markenprofil-Historie**: jede Änderung (Formular, Asset-Löschung mit Verweis, Wiederherstellen) schreibt vorher einen Snapshot der Zeile nach `brand_profile_versions` (`version = max + 1`, `to_jsonb(brand_profiles)`). Karte „Historie“ zeigt Zeitpunkt, Akteur und die danach geänderten Felder (`lib/brand/history.ts`); „Wiederherstellen“ → `POST /api/brand/[id]/restore` (`{ version }`), Audit `brand_profile.restored`.

### Seiten und Routen (Block B)

| Route | Inhalt |
|---|---|
| `/freigabe/[token]` | Öffentliche Gast-Freigabe (siehe oben), mobil ab 375 px. |
| `/einstellungen/abrechnung` | Tarif, Status, Verbrauch, Prognose, Planvergleich, Rechnungsadresse, Verlauf, Kündigung, Stripe-Portal. |
| `/einstellungen/loeschung` | Lösch-Aufträge mit Nachweis, Workspace-Löschung (owner), Datenexport. |
| `/rechtliches/avv`, `/rechtliches/toms`, `/rechtliches/subprozessoren` | Rechtstexte mit Platzhaltern aus dem Workspace, Annahme des AVV, Druckansicht. |
| `POST /api/projects/[id]/clips/[clipId]/guest-approval` | Gast-Freigabe anfordern (`guest_name`, `guest_email`, `message`). |
| `GET|POST /api/freigabe/[token]` | Freigabe lesen (setzt `viewed_at`) und entscheiden (`decision`, `comment`). |
| `GET /api/projects/[id]/clips/[clipId]/download` | Export-Link mit Gast-Freigabe-Sperre (409) und Umleitung auf die Medien-URL. |
| `POST /api/billing/plan`, `POST /api/billing/checkout`, `GET /api/billing/portal`, `POST /api/billing/webhook` | Abrechnung (siehe oben). |
| `POST /api/dpa/accept` | AVV annehmen (`company`, `representative`, `accepted`). |
| `DELETE /api/projects/[id]`, `DELETE /api/projects/[id]/clips/[clipId]` | Quelle oder Clip löschen. |
| `GET /api/export` | Datenexport als ZIP. |
| `POST|DELETE /api/brand/[id]/assets`, `GET /api/brand/[id]/assets/[assetId]`, `POST /api/brand/[id]/restore` | CI-Assets und Historie. |

Jede Route prüft `can()` über `requireApiRole` beziehungsweise `requireApiSession`; die Gast-Routen sind bewusst ohne Sitzung (das Token ist das Geheimnis).

## Demo-Modus

Ohne `DATABASE_URL` liefert `lib/repo/demo.ts` einen In-Memory-Speicher (überlebt Hot Reloads über `globalThis`):

- 3 Projekte: Podcast-Folge (62 min, `ready`, mit Transkript und 6 Kandidaten), Keynote (41 min, `transcribing`, simulierte Pipeline-Events), Interview (`uploaded`).
- 1 Markenprofil (du, AT, neutral, Wörterbuch mit PLACEMedia, Kleinecke, Rimowa).
- Deutsches Transkript mit 48 Sätzen (ca. 520 Wörter, knapp 6 Minuten), 2 Sprechern, Wortzeiten, Konfidenzen (einige unter 0,9), harten Füllwörtern, Modalpartikeln, Verneinungen, Zahlen, einer Gegenposition, einem Witz und einer späteren Relativierung („Das heißt aber nicht …“).
- 6 Kandidaten nach `packages/schema/CANDIDATES.md`: 3 mit allen Pflichtkriterien, einer mit bestätigtem Story-Graph-Flag (Reparatur: verlängern), einer mit fehlgeschlagenem `no_open_loop` und Titelkarten-Vorschlag, einer mit `humor` und `sensitive_topic`, einer aus `heuristic-v1` (`heuristic_only`). Grenzen, Text und Dauer werden aus den Seed-Sätzen abgeleitet.
- Laufende Pipelines werden zeitbasiert simuliert (Prüfung → Transkription → Sprechertrennung → Sprachanalyse → Kandidaten (`scoring`) → `ready`), sichtbar über SSE auf der Projektseite.
- Der Upload wird simuliert (Fortschrittsbalken, dann Projekt im Speicher). Auch mit Datenbank weicht die App auf die Simulation aus, wenn der tusd-Endpoint nicht erreichbar ist.
- Renders (Phase 3) werden simuliert: nach dem Annehmen läuft je Clip `draft → rendering → rendered` in etwa 6 Sekunden mit `pipeline_events` (`step = 'render'`, Fortschritt copy, reframe, captions, encode, provenance). Beim Abschluss entstehen `render_plan` (Vertrag `render_plan_v1`, Strategie `neutral`, `detector: 'none'`), `loudness` (-16,0 LUFS / -1,5 dBTP), `provenance` (`c2pa: 'skipped'`, „c2patool nicht installiert“), Dauer, Auflösung, `cps_warnings`, `hook_versions` v1 (origin `llm`, fünf Varianten, eine mit Lint-Hinweisen, eine mit Claim-Issues) und `caption_versions` v1 (Karten aus dem Clip-Text auf der Ausgabe-Timeline). Dateien im Bucket gibt es nicht, die Export-Links bleiben deaktiviert.

- Block B wird simuliert: Gast-Freigaben vollständig (Link, öffentliche Seite, Entscheidung), Abrechnung im Speicher (Tarif Starter in der Testphase, zwei vergangene Monate im Verlauf), AVV-Annahme, Lösch-Aufträge werden nach 1,5 s `running` und nach 5 s `done` mit Nachweis (Keys und Zeilenzähler), CI-Assets liegen im Speicher des Prozesses, Historie mit Wiederherstellen.

Die App ist im Demo-Modus vollständig bedienbar: kein Postgres, kein Temporal, kein tusd nötig.

## Seiten

| Route | Inhalt |
|---|---|
| `/` | Projekte: Pill-Navigation, Hintergrundwort, Glas-Karten mit Status, Dauer, Fortschritt, Zähler-Badge „6 Kandidaten“ und „Review öffnen“ (Transkript als Ghost-Link), sonst „Transkript öffnen“. |
| `/upload` | Upload-Formular (Titel, Markenprofil, Drag-and-drop, Rechtestatus, Pflicht-Checkbox, Sprecher, Briefing), tus-Upload mit Fortschritt (oder direkter Upload im lokalen Testmodus), Weiterleitung zum Projekt. |
| `/projekte/[id]` | Pipeline-Schritte live per SSE (`/api/projects/[id]/events`), Metadaten (Dauer, Auflösung, SHA-256, Löschfrist), Briefing. Bei `ready` mit Kandidaten: „Kandidaten prüfen“ mit Zähler („3 von 6 erfüllen alle Pflichtkriterien“). |
| `/projekte/[id]/transkript` | Transkript-Editor: Video (oder simulierter Player), synchrones Wort-Highlight, Klick springt, Konfidenz < 0,9 orange, Sprecher umbenennen, Wort per Doppelklick/Enter bearbeiten, Füllwort-Diff, Korrekturzähler, Speichern als neue Version, Korrekturen ins Marken-Wörterbuch. Tastatur: Leertaste, Pfeiltasten ±5 s. |
| `/projekte/[id]/review` | Kandidaten-Review (Phase 2): Player mit 8-Sekunden-Vorschau (gleicher Hook wie der Editor), Clip-Text mit Sprechern und Timecodes, Glas-Karten mit Struktur-Badge, Dauer, „DACH-Qualität“ (Gesamtwert) und Gate-Zähler, orange Warn-Chips (Relativierung, Humor, sensibles Thema, Heuristik). Detail: „Warum dieser Clip?“, Rubrik mit Score-Balken, Gewicht und Belegzitat, Pflichtkriterien als Status-Liste, Story-Graph als Haarlinien-Graph, Hinweis „Scores veraltet“ nach Grenzänderung. Aktionen: Annehmen öffnet die Ziel-Auswahl (Chips TikTok, Reels, Shorts, LinkedIn, Standard alle vier, Standard-Plattform des Markenprofils hervorgehoben und immer dabei), dann Spektrum-Glitch auf der Karte und Link zur Clip-Übersicht; Ablehnen mit Pflichtgrund, Verlängern und Kürzen um einen Satz, Titelkarte (max. 8 Wörter), „Umschreiben“ führt nach dem Annehmen ins Hook-Studio. Filter: Alle, Pflichtkriterien erfüllt, Mit Warnung, Angenommen, Abgelehnt. Tastatur: J/K, A (öffnet die Ziel-Auswahl), R, Leertaste. |
| `/projekte/[id]/clips` | Clip-Übersicht (Phase 3): Pakete je Kandidat mit Zähler „x von y gerendert“ und kurzem Spektrum-Glitch, wenn ein Paket fertig wird (nur beim Übergang, nicht beim Laden). Karten je Clip: Poster (oder Platzhalter), Plattform-Badge, Aspect, Dauer, Status als StatusCheck (Entwurf, Wird gerendert mit Fortschritt und Stufenanzeige aus den Events, Gerendert, Fehlgeschlagen orange mit `render_error`), Lautheit in Mono, Provenienz-Chip (C2PA signiert / übersprungen mit Grund), Werbelabel, Reframe-Hinweis (neutraler Crop, kein Detektor, orange), Lesetempo-Warnungen. Aktionen: MP4, SRT, VTT (Medien-URLs, im Demo deaktiviert mit Tooltip), Hook-Studio, Neu rendern, Ton-aus-Vorschau (lädt Hook und Captions nach und zeigt `SilentPreview` in der Karte). Live über SSE `/api/projects/[id]/clips/events`. |
| `/projekte/[id]/clips/[clipId]/hooks` | Hook-Studio: links fünf Varianten (Muster Identitäts-Anruf, Gegenposition, Offene Schleife, Ergebnis zuerst, Fehler-Warnung; Wortzähler, Lint-Hinweise grau, Claim-Issues orange), rechts drei Spalten (gesprochener Hook, On-Screen-Hook mit Overlay-Schalter, Post-Caption mit Tabs je Plattform und CTA). Live-Linter (`lib/copy/lint.ts`) und Live-Claim-Check (`lib/copy/claims.ts`) gegen `rubric.text` des Kandidaten. Speichern legt eine manuelle Version an, danach Hinweis „Für das Video neu rendern“ mit Button. Versionen-Liste mit Modell und Prompt in Mono. Ton-aus-Vorschau: CSS-Rahmen im Ausgabeformat, Safe Zones als Haarlinien, Hook-Overlay 3 s, Titelkarte 2,5 s, Caption-Karten im Preset-Stil an der Baseline, Bauchbinde, Scrubber und Play ohne Ton. |
| `/marke` | Markenprofil-Formular (Server Action): Anrede, Land, Gender-Modus, ASR-Variante, Plattform, Untertitel-Stil (leere Auswahl = NULL = automatisch nach Format, Migration 0007), Ton-Adjektive, Wörterbuch, geschützte Begriffe, gesperrte Phrasen. Karte „CI“: Primär-, Sekundär-, Akzent- und Caption-Highlight-Farbe als Hex-Felder mit Farbvorschau und AA-Kontrastprüfung gegen Weiß und Schwarz, Bauchbinde (Name, Funktion, an/aus), Hook-Overlay-Standard je Plattform; gespeichert in `brand_profiles.ci` und `caption_style`. Font-Upload kommt in Phase 4. |
| `/einstellungen` | Workspace-Einstellungen mit Reitern Allgemein, Mitglieder, Abrechnung, Sicherheit, Löschung, Audit-Log (siehe Block A und B). |

## API

| Route | Zweck |
|---|---|
| `POST /api/tus/hooks` | tusd-v2-Hooks. `pre-create` prüft Upload-Token (Signatur, Ablauf, Rolle, Kontingent), Rechte-Bestätigung und Größe; `post-finish` legt `sources` mit Workspace, Nutzer und Marke aus dem Token an, schreibt `audit_log` (`upload.created`, `rights.confirmed`) und startet den Temporal-Workflow. Der Browser sendet `client_ref` (UUID) als Metadatum, damit die Projekt-ID vorab bekannt ist. |
| `GET /api/projects/[id]/events` | Server-Sent Events, pollt `pipeline_events` alle 1,5 s, schließt bei `ready`/`failed`. |
| `GET/POST /api/projects/[id]/transcript` | Aktuelle Version lesen bzw. neue Version (`origin: manual`) plus `transcript_corrections` und optional Wörter ins `brand_profiles.brand_vocab` schreiben (`audit_log`: `transcript.corrected`). |
| `GET /api/projects/[id]/candidates` | Aktuelle Kandidaten-Versionen (ohne `human_verdict = 'edited'`), Pflichtkriterien erfüllt zuerst, dann `total` absteigend, plus Zähler. |
| `POST /api/projects/[id]/candidates/[cid]/verdict` | `{ verdict: "accepted" \| "rejected", reason, platforms }`. Ablehnen braucht einen Grund. Bei `accepted`: je Ziel eine `clips`-Zeile nach `packages/schema/CLIPS.md` (Aspect je Plattform, `composition`, `title_card`, `ad_label` aus Briefing `is_ad` und Land, Status `draft`; bestehende Zeilen je `(candidate_id, platform)` werden wiederverwendet), Urteil setzen, `audit_log` `clip.created` je Clip und `candidate.accepted` mit `clip_ids`, je Clip Signal `approve(candidate_id, platform)` an `project-<source_id>`. Antwort enthält `clips`. Im Demo-Modus startet die Render-Simulation. |
| `GET /api/projects/[id]/clips` | Alle Clips eines Projekts plus Zähler. |
| `GET /api/projects/[id]/clips/[clipId]` | Clip mit aktueller Hook-Version und aktuellen Captions. |
| `POST /api/projects/[id]/clips/[clipId]/hooks` | `{ spoken_hook, onscreen_hook, pattern, post_captions, cta }` → neue `hook_versions`-Zeile (`origin: manual`, `lint_notes`, `claim_issues` serverseitig berechnet). `audit_log`: `hook.saved`. |
| `POST /api/projects/[id]/clips/[clipId]/render` | Render (erneut) anstoßen: Signal `approve` je Clip, Demo: Simulation erneut. `audit_log`: `clip.render_requested`. |
| `GET /api/projects/[id]/clips/events` | Server-Sent Events für Renders: pollt `pipeline_events` mit `step = 'render'` alle 1,5 s, sendet `render`-Ereignisse und bei Änderung den Clip-Stand (`clips`), schließt, wenn alle Clips gerendert, exportiert oder fehlgeschlagen sind. |
| `POST /api/projects/[id]/candidates/[cid]/revise` | `{ first_sent, last_sent, title_card }`. Neue Zeile `version + 1` mit `rubric.parent_id`, `rubric.scores_stale = true` bei Grenzänderung, Gates deterministisch neu (`sentence_boundaries`, `no_open_loop` über die Open-Loop-Liste aus `dach_nlp`; `standalone`, `fidelity`, `verb_bracket` übernommen). Story-Graph-Flags, die jetzt im Clip liegen, entfallen. Alte Zeile bekommt `human_verdict = 'edited'`. `audit_log`: `candidate.revised`. |

## Struktur

```
app/                Seiten, Server Actions, API-Routen
proxy.ts            Next-16-Proxy (Middleware): Cookie-Prüfung, Umleitung auf /anmelden, Cookie-Verlängerung
components/ui/      PillNav (mit Nutzer-Menü), Button, GlassCard, Toggle, StatusCheck, Grain, LightCone, BackgroundWord, Field, TagInput, Badge, Timecode, FormNotice, ConfirmForm
components/brand/   Wordmark, Mark (SVGs aus public/brand)
components/layout/  PageShell (liest die Sitzung für die Navigation), AuthShell (Anmeldeseiten ohne Navigation)
lib/auth/           permissions (Rollenmatrix), password (Argon2id), tokens, cookies, mail (nodemailer), rate-limit, upload-token (HMAC), service (Login, Registrierung, Mails), guard (API 401/403), url, form
lib/session.ts      getSession, requireSession, requireRole, requirePageRole, withSessionContext, Demo-Sitzung
lib/billing/        quota.ts: Kontingent-Gate; provider.ts: manual/stripe; stripe.ts: Signatur und Ereignis-Abbildung; format.ts: €-Format, Prognose
lib/guest/          approval.ts: Status je Clip, Export-Sperre; mail.ts: E-Mail an den Gast
lib/legal/          docs.ts: Rechtstexte aus docs/rechtliches (Platzhalter, Tarif-Filter); Markdown.tsx: Renderer
lib/brand/          assets.ts: Regeln für CI-Assets; fonts.ts: fontkit; history.ts: geänderte Felder; preview-font.ts: @font-face für die Vorschau
lib/storage.ts      Objektspeicher (S3 path-style oder In-Memory) für CI-Assets
lib/audit/          query.ts: Filter der Audit-Seite und des CSV-Exports
lib/repo/           Repository-Interface (Fach, Auth, Workspace-Verwaltung), Postgres- und Demo-Implementierung, Seed-Daten
lib/db.ts           Postgres-Verbindung: withContext (RLS-Kontext) und withAuthContext (Auth-Tabellen)
lib/temporal.ts     Workflow-Start (ClipProjectWorkflow, Signal approve, DeletionWorkflow)
lib/transcript/     Füllwort- und Verneinungsregeln (Spiegel von dach_nlp), Sätze aus Wörtern (sentences.ts)
lib/candidates/     Gates (Open-Loop-Liste, Neuberechnung), Revision (neue Version), deutsche Labels
lib/copy/           Copy-Linter (Spiegel von copy_de.lint, Wortlimits 12/9), Claim-Check (Spiegel von fidelity.hook_claim_check), Hook-Versionen und Demo-Varianten
lib/clips/          Caption-Presets mit Safe Zones (Spiegel von captions_de.PRESETS), Caption-Karten, Labels, Demo-Render (render_plan_v1)
lib/color.ts        Hex-Prüfung und WCAG-Kontrast für das CI
components/clips/   SilentPreview (stumme Vorschau im Ausgabeformat)
```

## Clips und Render (Phase 3)

Vertrag: `packages/schema/CLIPS.md` (`clips_v1`, `render_plan_v1`), Tabellen aus Migration 0001 und 0002. Die Web-App legt Clips
beim Annehmen an, sendet das Signal und liest, was der Worker schreibt. Im Demo-Modus übernimmt `lib/repo/demo.ts` die Rolle
des Workers (siehe oben). Die stumme Vorschau spiegelt die Preset-Werte des Workers (TikTok oben 108 px, unten 320, links 60,
rechts 120; Reels 210 bis 1610; Shorts 120 bis 1620; LinkedIn 120 bis 1700 mit 80 px Rand, bei 4:5 proportional) und ersetzt
keinen Render.

## API-Schlüssel, öffentliche API, Webhooks, MCP (Phase 5, Welle 5a)

Vertrag: `packages/schema/PHASE5.md` (5a und „Interne Schnittstelle Worker ↔ Web“), Migration `0005_phase5.sql`. Eigene Module, damit `lib/repo/{types,postgres,demo}.ts` unberührt bleiben: `lib/repo/types-api.ts` (Typen), `lib/repo/api.ts` (Postgres, `getApiRepo()`), `lib/repo/api-demo.ts` (In-Memory).

- **API-Schlüssel** (`/einstellungen/api`, Aktion `api.manage` = owner/admin): Klartext `chp_live_<32 Bytes base64url>`, gespeichert nur `key_prefix` (8 Zeichen) und `key_hash` (SHA-256). Scopes `read`, `write`, `publish`, `admin`; Ablauf 30/90/365 Tage oder unbegrenzt; Widerruf; `last_used_at` höchstens einmal pro Minute. Klartext erscheint nur einmal nach dem Anlegen. Audit `api_key.created`, `api_key.revoked`. `lib/api/auth.ts` löst den Schlüssel zu `{ workspaceId, scopes, role }` auf (read → reviewer, write und publish → editor, admin → admin) und baut daraus eine `Session`; die Route läuft in `withSessionContext`, also mit denselben Repository-Methoden und RLS-Kontext wie die Web-App. Audit-Einträge laufen auf den Ersteller des Schlüssels (`payload.api_key_id`).
- **Öffentliche API `/api/v1`** (`lib/api/handler.ts` `apiRoute(scope, handler)`): Bearer-Auth → Rate-Limit (`lib/api/rate-limit.ts`, 600/min je Schlüssel, in-memory, TODO Redis) → Scope-Prüfung (`admin` schließt `write` und `read` ein, `write` und `publish` schließen `read` ein) → Handler. Fehler `{ error: { code, message } }` auf Deutsch; Erfolgsformen wie im MCP-Mock: Listen `{ sources }`, `{ candidates, count }`, `{ clips, count }`, `{ brand_profiles }`, `{ webhooks }`; Einzelobjekte `{ source }`, `{ transcript }`, `{ candidate }`, `{ clip, hook, media }` (Clip enthält `media: { video_url, poster_url, srt_url, vtt_url }`, `hook`, `captions`, `guest_approval`), `{ publication }`, `{ approval, link }`, `{ usage }`, `/me` mit `workspace`, `scopes`, `role`, `key`. Die schreibenden Handler (Verdict, Revise, Hooks, Render, Gast-Freigabe, Download, Löschen, SSE) delegieren an die bestehenden Routen unter `app/api/projects/**` (`lib/api/delegate.ts`) und passen nur die Fehlerform an; damit bleiben Audit, Temporal-Signale und Gates identisch. `POST /sources` mit `upload: "tus"` legt die Quelle als `uploading` an und liefert `upload_token`, `tus_endpoint` und `tus_metadata` (`client_ref` = Quellen-ID; der tusd-Hook vervollständigt die Zeile statt eine neue anzulegen); mit `upload: "url"` (nur mit `rights_confirmed`, `source_owner`, `source_url`) entsteht die Quelle mit `brief.import_url` und der `ClipProjectWorkflow` startet, falls Temporal erreichbar ist. `POST /clips/{id}/publish` (Scope `publish`): Gates Clip rendered, Kandidat accepted, Gast-Freigabe approved falls verlangt, AVV angenommen, Plan `features.publishing` (sonst 402), Verbindung `connected`; legt `publications` an und startet `PublishWorkflow` (`publish-<id>`, `lib/api/publish-workflow.ts`), ohne Temporal bleibt sie `scheduled` mit Hinweis. `GET /clips/{id}/download` 302 auf die Medien-URL, 409 `guest_approval_pending`. `GET /sources/{id}/events` ist SSE. OpenAPI 3.1 unter `/api/v1/openapi.json` aus `lib/api/openapi.ts`; dieselben Schemata prüfen die Request-Bodies (`lib/api/validate.ts`, kleiner JSON-Schema-Prüfer ohne zod).
- **Webhooks** (`/einstellungen/webhooks`): URL nur https ohne privaten Host (`lib/api/webhooks.ts`), Ereignisse aus `WEBHOOK_EVENTS`, Secret `whsec_…` nur einmal sichtbar, aktiv/pausiert, Löschen, „Ping“ (Outbox-Ereignis `webhook.ping`, sofort als verarbeitet markiert, plus direkte `webhook_deliveries`-Zeile für genau diesen Endpunkt), Zustellungsliste (Status, Versuche, Antwortcode, nächster Versuch). Zustellung und Retries macht der Worker (`OutboxWorkflow`, `deliver_webhook`). Web-seitige Outbox: `lib/outbox.ts` `emitOutbox(workspaceId, event, entity, entityId, payload)`; eingebaut bei `guest_approval.decided` (`app/api/freigabe/[token]`) und `usage.threshold` (80 % und 100 %, `noteUsageThresholds` nach jeder Kontingent-Prüfung im Upload-Token, `POST /api/v1/sources` und `GET /api/v1/usage`; Merker sind die vorhandenen Outbox-Ereignisse der Periode, keine neue Spalte).
- **Interne Endpunkte** `POST /api/internal/{publish,metrics,mail}` (`X-Internal-Secret` = `INTERNAL_API_SECRET`, `lib/api/internal-auth.ts`): `publish` und `metrics` delegieren über `lib/api/internal-publish.ts` dynamisch an `lib/publishing/registry` (Welle 5b, `publish(publicationId)` und `metrics(publicationId, window)`); fehlt das Modul, kommt `status: "failed"` mit „Publishing-Provider nicht verfügbar“ beziehungsweise alle Metriken `null`. `mail` versendet je Empfänger über `lib/auth/mail.ts` (Textmail; `html` wird angenommen, aber nicht gesendet).
- **Entwicklerseite `/entwickler`** (owner/admin, Navigationspunkt „Entwickler“): Grundlagen, Endpunktliste aus `ENDPOINTS`, Beispiele curl, Python (`requests`), MCP-Konfiguration (Claude Desktop, Claude Code, aus `packages/mcp-server/README.md`), Webhook-Signaturprüfung.
- **Schweizerdeutsch-Beta (5c, UI-Teil)**: `lib/transcript/dialect.ts` liest `transcript_versions.stats.dialect` (`{ variant, confidence, markers }`) und `words[].text_norm`. Der Transkript-Editor zeigt „Schweizerdeutsch erkannt, CH-Modell empfohlen, Beta“ (orange, wenn `asr_variant` nicht `de-CH` ist) oder einen grauen AT/CH-Hinweis und einen Umschalter „Original / Standard“ (Standard nutzt `text_norm`, normalisierte Wörter sind gepunktet unterstrichen, Bearbeiten ändert immer das Original). Markenprofil: Feld „Caption-Text“ (`caption_style.caption_text_field`: `text` | `text_norm`, Typ `CaptionStyleExt`) und Beta-Badge an der ASR-Variante `de-CH`.

Geprüft gegen Postgres (Migrationen 0001 bis 0005) mit curl: alle v1-Endpunkte inklusive 401 ohne Schlüssel, 403 bei fehlendem Scope, 429 nach 600 Anfragen, 302/409 beim Download, Guest-Approval, Usage, Me, Webhooks, `outbox_events` für `guest_approval.decided`, `webhook.ping` und `usage.threshold` (je einmal pro Periode); interne Endpunkte mit und ohne Secret; `openapi.json` parsebar mit 21 Pfaden und 25 Operationen. MCP-Server aus `packages/mcp-server` per stdio gegen die echte API: `list_sources`, `get_source`, `get_transcript`, `list_candidates`, `list_clips`, `get_clip`, `get_usage`, `render_clip` (Vorschau) und die Resource `render-plan` liefern die erwarteten Formen ohne Abweichung zum Mock.

Offene Punkte 5a:

- Ingest per URL (`upload: "url"`): Die Web-App legt die Quelle mit `status = uploading` und `brief.import_url` an und startet `ClipProjectWorkflow`; der Worker hat noch keinen Download-Schritt für `import_url` (`storage_key` bleibt leer). Bis dahin bleibt die Quelle `uploading`.
- Rate-Limit und `last_used_at`-Drossel sind in-memory je Prozess (TODO Redis bei mehreren Instanzen).
- `POST /api/internal/mail` sendet nur Text; `html` wird ignoriert, weil `lib/auth/mail.ts` keinen HTML-Teil kennt.
- `webhook.ping` ist nicht abonnierbar und steht nicht in `EVENTS` von `workers/chopstr_worker/outbox.py`; die Zustellung entsteht direkt als `webhook_deliveries`-Zeile, das Outbox-Ereignis ist nur der Nachweis.
- Die Antwort von `POST /clips/{id}/guest-approval` enthält wie die Web-Route das Token im `approval` (es steckt ohnehin im `link`).
- Demo-Modus: Schlüssel, Webhooks und Publikationen leben nur im Speicher des Serverprozesses (`lib/repo/api-demo.ts`); die Demo-Verbindung `77777777-7777-4777-8777-777777777701` (manual) erlaubt einen Publish-Durchlauf.

## Publishing, Decision Log, Hook-A/B, Serien, Berichte (Phase 5, Welle 5b) und Reframe-Override (5c)

Vertrag: `packages/schema/PHASE5.md` (5b, „Folien-Crop“, „Interne Schnittstelle Worker ↔ Web“), Migration `0005_phase5.sql`, Entscheidungen P13 bis P15. Eigene Module, damit `lib/repo/{types,postgres,demo}.ts` unberührt bleiben: `lib/repo/types-publishing.ts` (Typen), `lib/repo/publishing.ts` (Postgres, `getPublishingRepo()`, plus sitzungslose Lader für die internen Endpunkte), `lib/repo/publishing-demo.ts` (In-Memory). Rollen in `lib/auth/permissions-publishing.ts` (`canExt`): `publishing.manage` (owner, admin), `publishing.publish`, `series.manage`, `experiments.manage` (owner, admin, editor); Server-Helfer in `lib/publishing/auth.ts`.

- **Provider und Registry** (`lib/publishing/providers/*`, `lib/publishing/registry.ts`): `manual` (immer verfügbar), `tiktok` (Login Kit, Content Posting API mit FILE_UPLOAD oder PULL_FROM_URL, Status-Polling), `instagram` (Graph API, Reels-Container über die verknüpfte Seite, braucht öffentliche `video_url` aus `NEXT_PUBLIC_MEDIA_BASE_URL`), `youtube` (OAuth mit `access_type=offline`, resumable `videos.insert`, „#Shorts“-Hinweis, Statistik plus Analytics), `linkedin` (OpenID Connect, Videos API initialize/finalize, Posts API, Social Actions). Jeder Provider: `authorizeUrl`, `exchangeCode`, `refresh`, `publish`, `fetchMetrics`, `capabilities()`; alle Endpunkte sind mit `TODO verify against current docs` markiert (CON-007). `registry.publish(publicationId)` und `registry.metrics(publicationId, window)` werden von `/api/internal/{publish,metrics}` (5a) dynamisch importiert, laufen über die Auth-Verbindung (kein Nutzer beteiligt), erneuern abgelaufene Tokens (`refresh`, verschlüsselt gespeichert; bei Fehler Verbindung `expired`) und liefern `{ status, external_id, external_url, error }` beziehungsweise `{ metrics }`, wobei `lib/publishing/capabilities.ts` `maskMetrics` nur Felder durchlässt, deren Capability Flag `true` oder `conditional` ist (Master 8.2: `views, likes, comments, shares, saves, avg_watch_time, retention_curve, follow_attribution, publish, schedule`). Zugangsdaten: `lib/publishing/crypto.ts` (AES-256-GCM mit `CREDENTIALS_KEY`).
- **Verbindungen `/einstellungen/verbindungen`** (owner, admin): Provider-Karten mit Status „konfiguriert“, OAuth-Start `GET /api/publishing/oauth/[platform]/start` (State im httpOnly-Cookie `chopstr_oauth_state`, 10 Minuten) und Callback `/callback` (Verbindung mit Capability Flags des Providers, Audit `connection.created`), manuelle Verbindung (`POST /api/publishing/connections`), Marke zuordnen und trennen (`PATCH`/`DELETE /api/publishing/connections/[id]`, trennen = `revoked` und Zugangsdaten gelöscht), Capability-Tabelle je Verbindung. Nicht konfigurierte Provider leiten mit Hinweis zurück.
- **Veröffentlichen** (Clip-Karte, `app/projekte/[id]/clips/ClipPublishing.tsx`, Rolle `publishing.publish`): Gates aus `lib/publishing/gates.ts` (Clip rendered, Kandidat accepted, Gast-Freigabe approved falls verlangt, AVV angenommen, Plan `features.publishing` mit Link zur Abrechnung) werden live auf der Karte gezeigt („n Gates offen“) und serverseitig in `POST /api/projects/[id]/clips/[clipId]/publish` erneut geprüft. Dialog mit Verbindung (passend zur Clip-Plattform, `reels` → `instagram`, `shorts` → `youtube`, oder manuell), Titel, Caption (vorbelegt aus `post_captions[platform]` der Hook-Version), Zeitpunkt jetzt oder geplant, Bestätigungs-Checkbox. Ergebnis: `publications` (`scheduled` mit `workspace_id`, `connection_id`, `created_by`; bei manueller Verbindung `manual`), Decision Log `publish` (actor user), `startPublishWorkflow` (`PublishWorkflow`, ID `publish-<id>`, `[{ publication_id }]`, CPU-Queue; ohne Temporal Hinweis „Worker holt ab“), Audit `publication.created`. Liste je Clip mit Status, Zeit, externer URL, Fehler und Metriken 6h/48h/7d (aus `publications.metrics` oder `performance_feedback`, `null` als „nicht verfügbar“), Abbrechen (Signal `cancel`, Status `failed` „Vom Nutzer abgebrochen“) und Umplanen (Signal `reschedule`) über `PATCH /api/publishing/publications/[id]`; manuelle Publikation: Post-URL eintragen und Metriken von Hand (`POST /api/publishing/publications/[id]/metrics` → `performance_feedback` mit `metric_window = manual`, `follows_per_1k`, `saves_per_1k`).
- **Decision Log (Web)** `lib/decision-log.ts` `recordDecision(...)` (Fehler werden geloggt, die Aktion bleibt gültig): `candidate_verdict` mit Rubrik-Merkmalen (Verdict-Route), `hook_selected` beim Speichern im Hook-Studio und beim Anlegen von Variante B, `hook_variant_shown` beim Laden des Hook-Studios (actor system, `features.patterns` in der Reihenfolge der Anzeige, wie `learning.rebuild_hook_stats` es liest), `publish`, `reframe_strategy`. Hook-Studio: Reihenfolge der fünf Varianten per Thompson Sampling (`lib/experiments/thompson.ts`, Port von `learning.thompson_order`: Beta(chosen + 1, shown − chosen + 1) mal Reward-Mittel, Seed aus der Clip-ID) über `hook_pattern_stats` der Marke; mit Statistik trägt der erste Eintrag „Vorschlag der Lernschleife“, ohne bleibt die Standardreihenfolge.
- **Hook-A/B** (`/experimente`, Rolle `experiments.manage`): „Variante B anlegen“ im Hook-Studio (`POST /api/experiments`): `experiments`-Zeile (`draft`, Hypothese), Klon des Clips mit gleicher Komposition, Plattform und Kandidat (`variant = B`, Original `A`), Hook-Version 1 für B aus der gewählten Variante. Detailseite mit beiden Clips, Metriken je Variante (jüngstes Feedback, 7d vor 48h vor 6h vor manuell), Bedingungen (`lib/experiments/stats.ts`: beide Publikationen mindestens 48 h alt, `min_exposure` Views je Variante) mit Begründung am deaktivierten Button, Konfidenz P(A > B) als Monte-Carlo über Beta(follows + 1, views − follows + 1) mit 2.000 Ziehungen und Seed aus der Experiment-ID (ohne Folge-Signal Saves, sonst Likes, mit Hinweis), Gewinner setzen (`POST /api/experiments/[id]`, `winner_clip_id`, `confidence`, `decided_at`, Audit `experiment.decided`).
- **Serien** (`/serien`, Rolle `series.manage`): Anlegen mit Name, Marke, Kadenz, Regeln (Struktur, Plattformen, Caption-Preset, Hook-Muster), pausieren; Detailseite mit Kalender (8 Slots zurück und voraus relativ zu `created_at`, Lücken orange) und Clip-Liste. Zuordnung über die Clip-Karte (`POST /api/series/[id]/assign`): Variations-Prüfung `lib/series/variation.ts` gegen die letzten 9 Clips der Serie (Caption-Preset, Hook-Muster, Struktur, Länge ±15 %); drei oder mehr gleiche Merkmale → Dialog „Zu ähnlich, Variante ziehen“, Zuordnung mit „Trotzdem zuordnen“ möglich; `clips.series_index` ist der Slot-Index zum Zeitpunkt der Zuordnung.
- **Berichte** (`/berichte`): `weekly_reports` des Workspace (Woche, Publikationen, Zusammenfassung, 3 beste und 3 schwächste Clips mit Ursache und Änderung), Opt-out `workspaces.weekly_report_enabled` per Server Action (owner, admin, Audit `workspace.weekly_report`), Hinweis ohne Berichte.
- **Reframe-Override (5c)**: Auswahl „Bildausschnitt“ auf der Clip-Karte (automatisch, Talking Head, zwei Sprecher, neutral, Folie + Sprecher) → `PATCH /api/projects/[id]/clips/[clipId]/reframe` schreibt `clips.reframe_override`, Decision Log `reframe_strategy`, Audit `clip.reframe_override`; Kurzinfo zeigt die erkannte Strategie und, falls der Render-Plan sie liefert, `slide_region.confidence`; danach „Neu rendern“.
- Sekundärnavigation `components/publishing/PublishingNav.tsx` (Serien, Experimente, Berichte, Verbindungen) auf den 5b-Seiten; die Clip-Übersicht verlinkt Serien und Experimente.

Geprüft gegen Postgres (Migrationen 0001 bis 0005, `CREDENTIALS_KEY` gesetzt, Produktions-Build auf Port 3001): manuelle Verbindung angelegt; OAuth-Start eines nicht konfigurierten Providers zeigt den Hinweis; Gast-Freigabe-Sperre blockiert das Veröffentlichen mit Begründung; manuelle Publikation plus Metriken → `performance_feedback` (`manual`, `follows_per_1k` 25); geplante Publikation über eine TikTok-Verbindung mit AES-verschlüsselten Zugangsdaten (`credentials` beginnt mit `v1:`, kein Klartext) → `scheduled` mit Decision-Log `publish`, Audit `publication.created`, Umplanen und Abbrechen; Variante B → zwei Clips mit `experiment_id` und Hook-Version für B, Experiment-Seite mit deaktivierter Entscheidung und Begründungen, nach SQL-Metriken (2 × 7d, > 1.000 Views, 3 Tage alt) Konfidenz und Gewinner; Serie angelegt, zwei ähnliche Clips → Warnung, Kalender mit Lücken nach Rückdatierung; Berichte-Seite mit SQL-Bericht und Opt-out; Reframe-Override `slide_pip`; Hook-Studio mit `hook_pattern_stats` zeigt „Vorschlag der Lernschleife“; mobil 375 px auf Verbindungen und Experimente ohne horizontalen Überlauf.

Offene Punkte 5b:

- Plattform-APIs sind nach Dokumentationsstand geschrieben und ohne echte App-Zugangsdaten nicht gegen die Plattformen getestet (alle Endpunkte `TODO verify against current docs`, CON-007). Unsicher: TikTok `privacy_level` vor dem Audit und die Post-URL aus `publicaly_available_post_id`; Instagram Insights-Metriknamen (`views` statt `plays`) und das Pflichtfeld `video_url` (öffentliche Medien-URL); YouTube Analytics-Verzögerung (Felder bleiben bis dahin `null`); LinkedIn `r_member_postAnalytics` (Partner-Zugang, sonst bleiben Impressionen und Reshares `null`) und der Refresh-Token nur mit Freischaltung.
- Capability Flags je Provider sind Defaults nach Master 8.2 in `lib/publishing/capabilities.ts`; sie sind mit den Plattform-Verträgen abzugleichen.
- Render von Variante B: „Neu rendern“ signalisiert `approve(candidate_id, platform)` an den Projekt-Workflow, der Clips über Kandidat und Plattform auflöst; der Worker braucht einen Render-Pfad je Clip-ID, damit B (gleicher Kandidat, gleiche Plattform) den eigenen Hook bekommt.
- `hook_variant_shown` wird bei jedem Laden des Hook-Studios geschrieben (auch beim Neuladen); das erhöht `shown` je Aufruf, nicht je Sitzung.
- Serien-Slots sind an `series.created_at` verankert; ein Clip landet im aktuellen Slot, ein Wunsch-Slot ist nicht wählbar.
- Demo-Modus: Verbindungen, Publikationen, Experimente, Serien und Berichte leben nur im Speicher (`lib/repo/publishing-demo.ts`), Variante B ist dort ein Klon ohne Render-Simulation, `hook_pattern_stats` sind leer.
- `/verboten?aktion=publishing.*` zeigt die generische Meldung, weil die Seite nur `ACTIONS` aus `lib/auth/permissions.ts` kennt.

## Offene Punkte

- Auth: Rate-Limit ist in-memory (Redis folgt); `chopstr_auth` und `chopstr_app` sind dokumentiert, in der Entwicklung aber nicht getrennt (Owner-Verbindung, RLS greift nicht, deshalb filtern die Repository-Abfragen explizit). Kein Passkey, kein 2FA. Der Editor- und Hook-Studio-Client zeigt für reviewer/client die Schreib-Buttons noch an; der Server antwortet 403.
- E-Mail-Änderung im Profil wird sofort übernommen und als unbestätigt markiert (keine Spalte für eine ausstehende Adresse).
- Demo-Modus: Registrierung und Einladungen sind ohne Wirkung, Profil- und Passwortänderungen werden nicht gespeichert.
- Video-Proxy im Editor: es gibt noch keine signierten URLs aus dem `derived`-Bucket; `NEXT_PUBLIC_MEDIA_BASE_URL` ist ein Provisorium.
- Die Postgres-Implementierung ist gegen das Schema geschrieben, aber ohne laufende Datenbank auf dieser Maschine nicht integrationsgetestet.
- Medien-URLs (MP4, SRT, VTT, Poster) sind unsigniert über `NEXT_PUBLIC_MEDIA_BASE_URL`; signierte URLs kommen in Phase 4. Font-Upload für das CI ebenfalls Phase 4.
- Die Postgres-Methoden für Clips, Hook- und Caption-Versionen sind gegen das Schema geschrieben, aber ohne laufende Datenbank nicht integrationsgetestet. `requestClipRender` ändert in Postgres nur `render_error`; den Status setzt der Worker nach dem Signal.
- Ohne Temporal bleibt ein Clip in Postgres `draft`; die Clip-Seite pollt bis zu 30 Minuten und zeigt „Wartet auf den Render“.
- Der Claim-Check vergleicht Ziffern wörtlich (wie der Worker); ausgeschriebene Zahlen im Transkript („vierzehntausend“) decken „14.000“ im Hook nicht ab. Das ist gewollt: der Mensch prüft.
- Die Bauchbinde in der stummen Vorschau ist eine Annäherung an `corporate_third`; Position und Schrift des Renders bestimmt der Worker.
- Verlängern und Kürzen arbeiten satzweise über `sentence_idx` des aktuellen Transkripts; Rubrik-Scores werden nach einer Grenzänderung nicht neu bewertet, sondern als veraltet markiert.
- Die Reihenfolge der Kandidatenliste bleibt nach einem Urteil stabil (Sortierung kommt vom Server beim Laden).
- Speichern der Sprecher-Namen erfolgt in `transcript_versions.stats.speaker_names`; eine eigene Tabelle gibt es im Schema nicht.
- Keine automatisierten Tests für die Web-App; `npm test` ist im Workspace noch nicht definiert.
- Block B: Stripe ist gegen die API-Formen des SDK geschrieben, aber nur der Webhook wurde mit selbst signierten Payloads geprüft (kein Stripe-Konto). `subscriptions.provider = 'stripe'` wird erst durch Checkout oder Webhook gesetzt. Mollie bleibt Interface ohne Code.
- Block B: CI-Assets liegen ohne S3-Konfiguration nur im Speicher des Serverprozesses (Neustart löscht sie; die `brand_assets`-Zeilen bleiben). Der Worker braucht denselben `derived`-Bucket.
- Block B: Der Freigabestatus auf der Clip-Karte aktualisiert sich nicht live (Button „Status aktualisieren“ oder Neuladen). Medien auf der Freigabeseite sind unsigniert über `NEXT_PUBLIC_MEDIA_BASE_URL`.
- Block B: Ohne Temporal bleiben Lösch-Aufträge `queued`, bis der Retention-Lauf sie abholt; der Workspace-Job selbst wird vom Worker nach der Karenz angelegt, die `workspaces`-Zeile bleibt (Web-App löscht sie noch nicht).
- Block B: PDF-Download des AVV fehlt (Druckansicht), Sovereign ist im Planvergleich nur mit Sovereign-Workspace wählbar, `allow_overage` bleibt die Regel aus `lib/billing/quota.ts` (keine eigene Spalte).
