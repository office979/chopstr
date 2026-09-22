# @chopstr/web

Web-App von chopstr (Phase 0 bis 2: Fundament, „Deutsch hören“ und Kandidaten-Review). Next.js App Router,
Tailwind v4, Design-System „Lichtbruch“ aus `packages/design`.

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

- 3 Projekte: Podcast-Folge (62 min, `ready`, mit Transkript und 6 Kandidaten), Keynote (41 min, `transcribing`, simulierte Pipeline-Events), Interview (`uploaded`).
- 1 Markenprofil (du, AT, neutral, Wörterbuch mit PLACEMedia, Kleinecke, Rimowa).
- Deutsches Transkript mit 48 Sätzen (ca. 520 Wörter, knapp 6 Minuten), 2 Sprechern, Wortzeiten, Konfidenzen (einige unter 0,9), harten Füllwörtern, Modalpartikeln, Verneinungen, Zahlen, einer Gegenposition, einem Witz und einer späteren Relativierung („Das heißt aber nicht …“).
- 6 Kandidaten nach `packages/schema/CANDIDATES.md`: 3 mit allen Pflichtkriterien, einer mit bestätigtem Story-Graph-Flag (Reparatur: verlängern), einer mit fehlgeschlagenem `no_open_loop` und Titelkarten-Vorschlag, einer mit `humor` und `sensitive_topic`, einer aus `heuristic-v1` (`heuristic_only`). Grenzen, Text und Dauer werden aus den Seed-Sätzen abgeleitet.
- Laufende Pipelines werden zeitbasiert simuliert (Prüfung → Transkription → Sprechertrennung → Sprachanalyse → Kandidaten (`scoring`) → `ready`), sichtbar über SSE auf der Projektseite.
- Der Upload wird simuliert (Fortschrittsbalken, dann Projekt im Speicher). Auch mit Datenbank weicht die App auf die Simulation aus, wenn der tusd-Endpoint nicht erreichbar ist.

Die App ist im Demo-Modus vollständig bedienbar: kein Postgres, kein Temporal, kein tusd nötig.

## Seiten

| Route | Inhalt |
|---|---|
| `/` | Projekte: Pill-Navigation, Hintergrundwort, Glas-Karten mit Status, Dauer, Fortschritt, Zähler-Badge „6 Kandidaten“ und „Review öffnen“ (Transkript als Ghost-Link), sonst „Transkript öffnen“. |
| `/upload` | Upload-Formular (Titel, Markenprofil, Drag-and-drop, Rechtestatus, Pflicht-Checkbox, Sprecher, Briefing), tus-Upload mit Fortschritt, Weiterleitung zum Projekt. |
| `/projekte/[id]` | Pipeline-Schritte live per SSE (`/api/projects/[id]/events`), Metadaten (Dauer, Auflösung, SHA-256, Löschfrist), Briefing. Bei `ready` mit Kandidaten: „Kandidaten prüfen“ mit Zähler („3 von 6 erfüllen alle Pflichtkriterien“). |
| `/projekte/[id]/transkript` | Transkript-Editor: Video (oder simulierter Player), synchrones Wort-Highlight, Klick springt, Konfidenz < 0,9 orange, Sprecher umbenennen, Wort per Doppelklick/Enter bearbeiten, Füllwort-Diff, Korrekturzähler, Speichern als neue Version, Korrekturen ins Marken-Wörterbuch. Tastatur: Leertaste, Pfeiltasten ±5 s. |
| `/projekte/[id]/review` | Kandidaten-Review (Phase 2): Player mit 8-Sekunden-Vorschau (gleicher Hook wie der Editor), Clip-Text mit Sprechern und Timecodes, Glas-Karten mit Struktur-Badge, Dauer, „DACH-Qualität“ (Gesamtwert) und Gate-Zähler, orange Warn-Chips (Relativierung, Humor, sensibles Thema, Heuristik). Detail: „Warum dieser Clip?“, Rubrik mit Score-Balken, Gewicht und Belegzitat, Pflichtkriterien als Status-Liste, Story-Graph als Haarlinien-Graph, Hinweis „Scores veraltet“ nach Grenzänderung. Aktionen: Annehmen (Spektrum-Glitch auf der Karte), Ablehnen mit Pflichtgrund, Verlängern und Kürzen um einen Satz, Titelkarte (max. 8 Wörter), „Umschreiben“ deaktiviert bis Phase 3. Filter: Alle, Pflichtkriterien erfüllt, Mit Warnung, Angenommen, Abgelehnt. Tastatur: J/K, A, R, Leertaste. |
| `/marke` | Markenprofil-Formular (Server Action): Anrede, Land, Gender-Modus, ASR-Variante, Plattform, Caption-Preset, Ton-Adjektive, Wörterbuch, geschützte Begriffe, gesperrte Phrasen. |
| `/einstellungen` | Workspace, nur lesend: Tarif, Datenregion, Aufbewahrung, US-Subprozessoren, Training. |

## API

| Route | Zweck |
|---|---|
| `POST /api/tus/hooks` | tusd-v2-Hooks. `pre-create` prüft Rechte-Bestätigung und Größe, `post-finish` legt `sources` an, schreibt `audit_log` (`upload.created`, `rights.confirmed`) und startet den Temporal-Workflow. Der Browser sendet `client_ref` (UUID) als Metadatum, damit die Projekt-ID vorab bekannt ist. |
| `GET /api/projects/[id]/events` | Server-Sent Events, pollt `pipeline_events` alle 1,5 s, schließt bei `ready`/`failed`. |
| `GET/POST /api/projects/[id]/transcript` | Aktuelle Version lesen bzw. neue Version (`origin: manual`) plus `transcript_corrections` und optional Wörter ins `brand_profiles.brand_vocab` schreiben (`audit_log`: `transcript.corrected`). |
| `GET /api/projects/[id]/candidates` | Aktuelle Kandidaten-Versionen (ohne `human_verdict = 'edited'`), Pflichtkriterien erfüllt zuerst, dann `total` absteigend, plus Zähler. |
| `POST /api/projects/[id]/candidates/[cid]/verdict` | `{ verdict: "accepted" \| "rejected", reason }`. Ablehnen braucht einen Grund. Bei `accepted` und erreichbarem Temporal: Signal `approve(candidate_id, destination)` an `project-<source_id>` (`destination` = Plattform aus Briefing oder Markenprofil); im Demo-Modus nur geloggt. `audit_log`: `candidate.accepted`, `candidate.rejected`. |
| `POST /api/projects/[id]/candidates/[cid]/revise` | `{ first_sent, last_sent, title_card }`. Neue Zeile `version + 1` mit `rubric.parent_id`, `rubric.scores_stale = true` bei Grenzänderung, Gates deterministisch neu (`sentence_boundaries`, `no_open_loop` über die Open-Loop-Liste aus `dach_nlp`; `standalone`, `fidelity`, `verb_bracket` übernommen). Story-Graph-Flags, die jetzt im Clip liegen, entfallen. Alte Zeile bekommt `human_verdict = 'edited'`. `audit_log`: `candidate.revised`. |

## Struktur

```
app/                Seiten, Server Actions, API-Routen
components/ui/      PillNav, Button, GlassCard, Toggle, StatusCheck, Grain, LightCone, BackgroundWord, Field, TagInput, Badge, Timecode
components/brand/   Wordmark, Mark (SVGs aus public/brand)
components/layout/  PageShell (Hintergrundwort → Lichtkegel → Glas → Inhalt)
lib/repo/           Repository-Interface, Postgres- und Demo-Implementierung, Seed-Daten
lib/db.ts           Postgres-Verbindung mit RLS-Kontext
lib/temporal.ts     Workflow-Start
lib/transcript/     Füllwort- und Verneinungsregeln (Spiegel von dach_nlp), Sätze aus Wörtern (sentences.ts)
lib/candidates/     Gates (Open-Loop-Liste, Neuberechnung), Revision (neue Version), deutsche Labels
```

## Offene Punkte

- Echte Authentifizierung und Workspace-Wechsel (Phase 4). Bis dahin: ein Dev-Workspace aus Env-Variablen.
- Video-Proxy im Editor: es gibt noch keine signierten URLs aus dem `derived`-Bucket; `NEXT_PUBLIC_MEDIA_BASE_URL` ist ein Provisorium.
- Die Postgres-Implementierung ist gegen das Schema geschrieben, aber ohne laufende Datenbank auf dieser Maschine nicht integrationsgetestet.
- Der tusd-Hook läuft im Kontext der Dev-Session; in Produktion muss `workspace_id` aus den Metadaten gegen die Session geprüft werden.
- Render nach „Annehmen“ kommt in Phase 3; das Signal `approve` wird bereits gesendet, wenn Temporal erreichbar ist. Hook-Studio („Umschreiben“) ebenfalls Phase 3.
- Verlängern und Kürzen arbeiten satzweise über `sentence_idx` des aktuellen Transkripts; Rubrik-Scores werden nach einer Grenzänderung nicht neu bewertet, sondern als veraltet markiert.
- Die Reihenfolge der Kandidatenliste bleibt nach einem Urteil stabil (Sortierung kommt vom Server beim Laden).
- Speichern der Sprecher-Namen erfolgt in `transcript_versions.stats.speaker_names`; eine eigene Tabelle gibt es im Schema nicht.
- Keine automatisierten Tests für die Web-App; `npm test` ist im Workspace noch nicht definiert.
