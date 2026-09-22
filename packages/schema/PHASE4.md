# Datenvertrag Phase 4: Auth, Rollen, Gast-Freigabe, Abrechnung, AVV, Löschung, CI-Manager

Migration 0003. Abnahme: Pilot in der eigenen Agentur. Alles ist tarifunabhängig (Standard: Supabase-Postgres,
Sovereign: Hetzner), deshalb eigene Auth-Schicht statt Supabase-Auth.

## 1. Auth

- **Registrierung**: E-Mail + Passwort (Argon2id über `@node-rs/argon2`), oder Magic-Link (Token per E-Mail,
  15 Minuten gültig). E-Mail-Versand über SMTP (`SMTP_URL`, EU-Anbieter); ohne SMTP wird der Link in der
  Serverkonsole geloggt (`APP_ENV=development`).
- **Sitzung**: Cookie `chopstr_session` (httpOnly, secure außerhalb development, sameSite lax, 30 Tage),
  Inhalt nur die Sitzungs-ID; Zeile in `sessions` mit `workspace_id` = aktiver Workspace. `lib/session.ts`
  liest die Sitzung serverseitig (`getSession()` liefert `{ userId, workspaceId, role, brandScope }` oder
  leitet auf `/anmelden` um). Der Dev-Workspace-Fallback entfällt; ein Seed-Skript legt Nutzer und Workspace an.
- **Datenbank-Rollen**: `chopstr_auth` (BYPASSRLS) für users/sessions/login_tokens/invites-Annahme,
  `chopstr_app` mit `set local app.workspace_id`, `app.actor_id` und `app.brand_scope` (nur für client).
- **Workspace-Wechsel**: `/workspaces` listet Mitgliedschaften; Wechsel schreibt `sessions.workspace_id`.
- **Erster Workspace**: Registrierung erstellt Workspace (Name = Firma), Mitgliedschaft `owner`, Plan `starter`
  mit 14 Tagen Test (`subscriptions.status = trialing`), Standard-Markenprofil.

## 2. Rollen (Matrix)

| Aktion | owner | admin | editor | reviewer | client |
|---|---|---|---|---|---|
| Upload, Löschung anstoßen | ja | ja | ja | nein | nein |
| Transkript korrigieren, Kandidaten bearbeiten | ja | ja | ja | nein | nein |
| Kandidaten annehmen/ablehnen | ja | ja | ja | ja | ja (nur eigene Marke) |
| Hook-Studio speichern, Re-Render | ja | ja | ja | nein | nein |
| Markenprofil und CI ändern | ja | ja | ja | nein | nein |
| Mitglieder einladen, Rollen ändern | ja | ja | nein | nein | nein |
| Abrechnung, Plan, AVV | ja | ja | nein | nein | nein |
| Workspace löschen | ja | nein | nein | nein | nein |
| Audit-Log lesen | ja | ja | nein | nein | nein |

`client` ist immer an ein `brand_profile_id` gebunden (`workspace_members.brand_profile_id`); RLS filtert
Quellen über `app.brand_scope`. `lib/auth/permissions.ts` exportiert `can(role, action)`; jede Route und
Server Action prüft damit und antwortet 403 mit deutscher Meldung.

## 3. Upload-Token

Der tusd-Hook hat keine Sitzung. Beim Start eines Uploads holt der Browser `POST /api/uploads/token`
(prüft Rolle und Kontingent) und erhält `upload_token = base64url(payload).signature` mit
`payload = { workspace_id, user_id, brand_profile_id, exp }` und HMAC-SHA256 über `TUS_HOOK_SECRET`.
Das Token geht als tus-Metadatum mit. `pre-create` prüft Signatur, Ablauf und Kontingent; `post-finish`
nimmt `workspace_id`/`user_id` aus dem Token, nicht aus freien Metadaten.

## 4. Gast-Freigabe (Persönlichkeitsrecht)

- Editor setzt an einem Clip „Gast-Freigabe nötig“, gibt Name, E-Mail (optional) und Nachricht ein →
  `guest_approvals` mit Token (32 Bytes), `expires_at` = 14 Tage; Link `/freigabe/<token>`, per E-Mail oder
  zum Kopieren. Audit `guest_approval.requested`.
- Öffentliche Seite ohne Login: Poster/Video (Medien-URL), Titel, On-Screen-Hook, Post-Text, Plattform,
  drei Buttons: Freigeben, Änderungen wünschen (Kommentar Pflicht), Ablehnen (Kommentar Pflicht).
  Schreibt `decision`, `comment`, `decided_at`, `viewed_at`; Audit `guest_approval.decided` (actor_type guest).
- Clip-Status: mit `guest_approval_required = true` kann ein Clip erst `exported` werden, wenn eine
  Freigabe `approved` vorliegt; Export-Links sind bis dahin gesperrt (UI-Hinweis, API 409).
- Plan-Gate: `plans.features.guest_approval`.

## 5. Abrechnung nach Stunden

- Einheit: Stunden Quellmaterial pro Monat (`usage_periods.used_source_minutes`, summiert aus `job_costs`
  mit `job_type = 'ingest'` zum Zeitpunkt des Ingests). Kein Credit-System.
- Preise in `plans` (Starter 29 €, 4 h; Pro 79 €, 12 h; Agentur 199 €, 40 h; Sovereign 399 €, 40 h;
  Mehrverbrauch pro angefangener Stunde). Anzeige im DACH-Format („29 €“, „7,50 €“).
- Provider-Abstraktion `lib/billing/provider.ts`: `manual` (Rechnung per Hand, alles in der App sichtbar)
  und `stripe` (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, Preise über `STRIPE_PRICE_<PLAN>`;
  Checkout-Session, Customer-Portal, Webhooks `checkout.session.completed`, `customer.subscription.updated|deleted`,
  `invoice.paid|payment_failed` → `subscriptions` + `billing_events` idempotent über `provider_event_id`).
  Mollie als dritter Provider vorgesehen (Interface, kein Code in Phase 4).
- Kontingent-Gate: Upload-Token wird verweigert, wenn `used + geplante Dauer > included` und Mehrverbrauch
  nicht aktiviert ist (`workspaces`-Einstellung `allow_overage`, Default true bei aktivem Abo, false im Test).
- Seite `/einstellungen/abrechnung`: Plan, Zeitraum, Verbrauchsbalken (Stunden), Prognose, Mehrverbrauch,
  Rechnungen (Stripe) oder Hinweis (manual), Planwechsel, Kündigung zum Periodenende.

## 6. AVV / DPA

- Seite `/rechtliches/avv`: Vertragstext Version `2026-09` (Vorlage nach Art. 28 DSGVO mit Platzhaltern,
  deutlich als „juristisch zu prüfen“ markiert), TOMs (`/rechtliches/toms`) und Subprozessor-Liste
  (`/rechtliches/subprozessoren`, je Tarif: Standard mit AWS Bedrock EU und Supabase, Sovereign ohne US-Anbieter).
- Annahme durch owner/admin mit Firma und Vertreter → `dpa_acceptances`, `workspaces.dpa_signed_at`, Audit.
  Download als PDF kommt später; jetzt Druckansicht.
- Ohne AVV-Annahme: Upload erlaubt, aber Banner im Workspace („AVV noch nicht angenommen“).

## 7. Lösch-Workflow

- Quelle löschen (editor+): `sources.status = 'deleted'`, `deleted_at`, `deletion_jobs` (`entity = source`,
  `reason = user_request`, `status = queued`), Audit `source.delete_requested`. Sofort unsichtbar in Listen.
- Worker-Activity `delete_entity(job_id)`: löscht Objektspeicher-Keys (Original, Audio, Proxy, alle
  Render-Keys, Caption-Dateien) mit Nachweis in `keys_deleted`, dann DB-Zeilen (transcript_versions,
  transcript_corrections, candidates, clips, hook_versions, caption_versions, pipeline_events, guest_approvals)
  mit Zählern in `rows_deleted`; die `sources`-Zeile bleibt anonymisiert (Titel „gelöscht“, Keys null) als
  Nachweis. Audit `source.deleted` mit Job-ID. Workflow-Historie: Temporal-Workflow wird per `terminate`
  beendet, wenn er läuft.
- Retention: Temporal-Schedule `retention-daily` (Workflow `RetentionWorkflow`, 03:00 Europe/Vienna):
  Quellen mit `delete_after < now()` → Deletion-Job `reason = retention`. Workspace-Löschung: owner fordert an,
  30 Tage Karenz (`deletion_scheduled_for`), E-Mail an owner, danach Job `entity = workspace`.
- Datenexport (Art. 15/20): `GET /api/export` (owner/admin) liefert ZIP mit JSON aller Workspace-Tabellen
  und Liste der Medien-Keys; Audit `workspace.exported`.

## 8. CI-Manager

- Assets pro Markenprofil: Fonts (TTF/OTF/WOFF2, max. 5 MB, Familienname und Gewicht aus der Datei über
  `fontkit` oder `opentype.js`), Logo (SVG/PNG, max. 2 MB), Bauchbinden-Hintergrund. Upload über
  `POST /api/brand/[id]/assets` (multipart) in den `derived`-Bucket unter `brand/<profile>/<kind>/<sha>.<ext>`;
  Lizenzbestätigung Pflicht (Checkbox, Text im Audit).
- `brand_profiles.ci` erweitert: `{ colors, fonts: { primary_asset_id, secondary_asset_id, fallback: "Inter" },
  logo_asset_id, lower_third: { enabled, name, function, position }, hook_overlay: { tiktok, reels, shorts, linkedin } }`.
- Worker: Render lädt Font-Assets aus dem Storage in den Fonts-Ordner und nutzt sie in ASS (`Fontname`) und
  `drawtext`; Logo als Wasserzeichen optional (Plan-Feld `watermark`).
- Jede Änderung am Markenprofil schreibt vorher einen Snapshot nach `brand_profile_versions`; Seite zeigt
  Historie mit „Wiederherstellen“.

## 9. Audit-Log-Seite

`/einstellungen/audit` (owner/admin): Filter nach Aktion, Akteur, Zeitraum; Export CSV.

## Umgebungsvariablen (neu)

`SESSION_SECRET`, `SMTP_URL`, `MAIL_FROM`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`STRIPE_PRICE_STARTER|PRO|AGENCY|SOVEREIGN`, `BILLING_PROVIDER=manual|stripe`, `DPA_VERSION=2026-09`,
`RETENTION_CRON=0 3 * * *`.
