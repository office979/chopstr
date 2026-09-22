# @chopstr/web

Web-App von chopstr (Phase 0 + Phase 1: Fundament und „Deutsch hören“). Next.js App Router, Tailwind v4,
Design-System „Lichtbruch“ aus `packages/design`.

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
| `DATABASE_URL` | Postgres-Verbindung. **Nicht gesetzt = Demo-Modus** (In-Memory-Repository mit Seed-Daten). |
| `DEV_WORKSPACE_ID`, `DEV_ACTOR_ID` | Entwicklungs-Session (genau ein Workspace, ein Akteur). Echte Auth kommt in Phase 4. |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE_CPU` | Startet `ClipProjectWorkflow` nach dem Upload. Ohne Adresse oder im Demo-Modus wird nur geloggt. |
| `NEXT_PUBLIC_TUS_ENDPOINT` (Fallback `TUS_ENDPOINT`) | tusd-Endpoint für den Browser-Upload, Default `http://localhost:1080/files/`. |
| `TUS_HOOK_SECRET` | Secret für `/api/tus/hooks` (Header `Hook-Secret` oder Query `?secret=`). Nicht gesetzt: Hook wird mit Warnung angenommen (nur Entwicklung). |
| `UPLOAD_MAX_BYTES` | Upload-Limit, Default 5 GB. |
| `NEXT_PUBLIC_DEMO_UPLOAD=true` | Erzwingt den simulierten Upload auch mit Datenbank. |
| `NEXT_PUBLIC_MEDIA_BASE_URL` | Basis-URL für den 720p-Proxy im Transkript-Editor (optional; ohne sie läuft der simulierte Player). |
| `APP_VERSION` | Wird im Footer angezeigt. |

Die Session-Werte werden pro Transaktion als `app.workspace_id` und `app.actor_id` gesetzt (`lib/db.ts`, via `set_config(..., true)` = `SET LOCAL`), damit die Row-Level-Security aus `packages/schema/migrations/0001_init.sql` greift.

## Demo-Modus

Ohne `DATABASE_URL` liefert `lib/repo/demo.ts` einen In-Memory-Speicher (überlebt Hot Reloads über `globalThis`):

- 3 Projekte: Podcast-Folge (62 min, `ready`, mit Transkript), Keynote (41 min, `transcribing`, simulierte Pipeline-Events), Interview (`uploaded`).
- 1 Markenprofil (du, AT, neutral, Wörterbuch mit PLACEMedia, Kleinecke, Rimowa).
- Deutsches Transkript mit ca. 160 Wörtern, 2 Sprechern, Wortzeiten, Konfidenzen (einige unter 0,9), harten Füllwörtern, Modalpartikeln und Verneinungen.
- Laufende Pipelines werden zeitbasiert simuliert (Prüfung → Transkription → Sprechertrennung → Sprachanalyse → `ready`), sichtbar über SSE auf der Projektseite.
- Der Upload wird simuliert (Fortschrittsbalken, dann Projekt im Speicher). Auch mit Datenbank weicht die App auf die Simulation aus, wenn der tusd-Endpoint nicht erreichbar ist.

Die App ist im Demo-Modus vollständig bedienbar: kein Postgres, kein Temporal, kein tusd nötig.

## Seiten

| Route | Inhalt |
|---|---|
| `/` | Projekte: Pill-Navigation, Hintergrundwort, Glas-Karten mit Status, Dauer, Fortschritt, „Transkript öffnen“. |
| `/upload` | Upload-Formular (Titel, Markenprofil, Drag-and-drop, Rechtestatus, Pflicht-Checkbox, Sprecher, Briefing), tus-Upload mit Fortschritt, Weiterleitung zum Projekt. |
| `/projekte/[id]` | Pipeline-Schritte live per SSE (`/api/projects/[id]/events`), Metadaten (Dauer, Auflösung, SHA-256, Löschfrist), Briefing. |
| `/projekte/[id]/transkript` | Transkript-Editor: Video (oder simulierter Player), synchrones Wort-Highlight, Klick springt, Konfidenz < 0,9 orange, Sprecher umbenennen, Wort per Doppelklick/Enter bearbeiten, Füllwort-Diff, Korrekturzähler, Speichern als neue Version, Korrekturen ins Marken-Wörterbuch. Tastatur: Leertaste, Pfeiltasten ±5 s. |
| `/marke` | Markenprofil-Formular (Server Action): Anrede, Land, Gender-Modus, ASR-Variante, Plattform, Caption-Preset, Ton-Adjektive, Wörterbuch, geschützte Begriffe, gesperrte Phrasen. |
| `/einstellungen` | Workspace, nur lesend: Tarif, Datenregion, Aufbewahrung, US-Subprozessoren, Training. |

## API

| Route | Zweck |
|---|---|
| `POST /api/tus/hooks` | tusd-v2-Hooks. `pre-create` prüft Rechte-Bestätigung und Größe, `post-finish` legt `sources` an, schreibt `audit_log` (`upload.created`, `rights.confirmed`) und startet den Temporal-Workflow. Der Browser sendet `client_ref` (UUID) als Metadatum, damit die Projekt-ID vorab bekannt ist. |
| `GET /api/projects/[id]/events` | Server-Sent Events, pollt `pipeline_events` alle 1,5 s, schließt bei `ready`/`failed`. |
| `GET/POST /api/projects/[id]/transcript` | Aktuelle Version lesen bzw. neue Version (`origin: manual`) plus `transcript_corrections` und optional Wörter ins `brand_profiles.brand_vocab` schreiben (`audit_log`: `transcript.corrected`). |

## Struktur

```
app/                Seiten, Server Actions, API-Routen
components/ui/      PillNav, Button, GlassCard, Toggle, StatusCheck, Grain, LightCone, BackgroundWord, Field, TagInput, Badge, Timecode
components/brand/   Wordmark, Mark (SVGs aus public/brand)
components/layout/  PageShell (Hintergrundwort → Lichtkegel → Glas → Inhalt)
lib/repo/           Repository-Interface, Postgres- und Demo-Implementierung, Seed-Daten
lib/db.ts           Postgres-Verbindung mit RLS-Kontext
lib/temporal.ts     Workflow-Start
lib/transcript/     Füllwort- und Verneinungsregeln (Spiegel von dach_nlp)
```

## Offene Punkte

- Echte Authentifizierung und Workspace-Wechsel (Phase 4). Bis dahin: ein Dev-Workspace aus Env-Variablen.
- Video-Proxy im Editor: es gibt noch keine signierten URLs aus dem `derived`-Bucket; `NEXT_PUBLIC_MEDIA_BASE_URL` ist ein Provisorium.
- Die Postgres-Implementierung ist gegen das Schema geschrieben, aber ohne laufende Datenbank auf dieser Maschine nicht integrationsgetestet.
- Der tusd-Hook läuft im Kontext der Dev-Session; in Produktion muss `workspace_id` aus den Metadaten gegen die Session geprüft werden.
- Kandidaten (Phase 2) sind in der Pipeline nur als ausgegrauter Schritt angekündigt.
- Speichern der Sprecher-Namen erfolgt in `transcript_versions.stats.speaker_names`; eine eigene Tabelle gibt es im Schema nicht.
- Keine automatisierten Tests für die Web-App; `npm test` ist im Workspace noch nicht definiert.
