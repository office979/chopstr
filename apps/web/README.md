# @chopstr/web

Web-App von chopstr (Phase 0 bis 3: Fundament, „Deutsch hören“, Kandidaten-Review, Clips mit Hook-Studio).
Next.js App Router, Tailwind v4, Design-System „Lichtbruch“ aus `packages/design`.

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
| `NEXT_PUBLIC_MEDIA_BASE_URL` | Basis-URL für Medien aus dem `derived`-Bucket: 720p-Proxy im Editor sowie MP4, SRT, VTT und Poster auf der Clip-Seite (lokal MinIO `http://localhost:9000/chopstr-derived`). Ohne sie: simulierter Player und deaktivierte Export-Links. |
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
- Renders (Phase 3) werden simuliert: nach dem Annehmen läuft je Clip `draft → rendering → rendered` in etwa 6 Sekunden mit `pipeline_events` (`step = 'render'`, Fortschritt copy, reframe, captions, encode, provenance). Beim Abschluss entstehen `render_plan` (Vertrag `render_plan_v1`, Strategie `neutral`, `detector: 'none'`), `loudness` (-16,0 LUFS / -1,5 dBTP), `provenance` (`c2pa: 'skipped'`, „c2patool nicht installiert“), Dauer, Auflösung, `cps_warnings`, `hook_versions` v1 (origin `llm`, fünf Varianten, eine mit Lint-Hinweisen, eine mit Claim-Issues) und `caption_versions` v1 (Karten aus dem Clip-Text auf der Ausgabe-Timeline). Dateien im Bucket gibt es nicht, die Export-Links bleiben deaktiviert.

Die App ist im Demo-Modus vollständig bedienbar: kein Postgres, kein Temporal, kein tusd nötig.

## Seiten

| Route | Inhalt |
|---|---|
| `/` | Projekte: Pill-Navigation, Hintergrundwort, Glas-Karten mit Status, Dauer, Fortschritt, Zähler-Badge „6 Kandidaten“ und „Review öffnen“ (Transkript als Ghost-Link), sonst „Transkript öffnen“. |
| `/upload` | Upload-Formular (Titel, Markenprofil, Drag-and-drop, Rechtestatus, Pflicht-Checkbox, Sprecher, Briefing), tus-Upload mit Fortschritt, Weiterleitung zum Projekt. |
| `/projekte/[id]` | Pipeline-Schritte live per SSE (`/api/projects/[id]/events`), Metadaten (Dauer, Auflösung, SHA-256, Löschfrist), Briefing. Bei `ready` mit Kandidaten: „Kandidaten prüfen“ mit Zähler („3 von 6 erfüllen alle Pflichtkriterien“). |
| `/projekte/[id]/transkript` | Transkript-Editor: Video (oder simulierter Player), synchrones Wort-Highlight, Klick springt, Konfidenz < 0,9 orange, Sprecher umbenennen, Wort per Doppelklick/Enter bearbeiten, Füllwort-Diff, Korrekturzähler, Speichern als neue Version, Korrekturen ins Marken-Wörterbuch. Tastatur: Leertaste, Pfeiltasten ±5 s. |
| `/projekte/[id]/review` | Kandidaten-Review (Phase 2): Player mit 8-Sekunden-Vorschau (gleicher Hook wie der Editor), Clip-Text mit Sprechern und Timecodes, Glas-Karten mit Struktur-Badge, Dauer, „DACH-Qualität“ (Gesamtwert) und Gate-Zähler, orange Warn-Chips (Relativierung, Humor, sensibles Thema, Heuristik). Detail: „Warum dieser Clip?“, Rubrik mit Score-Balken, Gewicht und Belegzitat, Pflichtkriterien als Status-Liste, Story-Graph als Haarlinien-Graph, Hinweis „Scores veraltet“ nach Grenzänderung. Aktionen: Annehmen öffnet die Ziel-Auswahl (Chips TikTok, Reels, Shorts, LinkedIn, Standard alle vier, Standard-Plattform des Markenprofils hervorgehoben und immer dabei), dann Spektrum-Glitch auf der Karte und Link zur Clip-Übersicht; Ablehnen mit Pflichtgrund, Verlängern und Kürzen um einen Satz, Titelkarte (max. 8 Wörter), „Umschreiben“ führt nach dem Annehmen ins Hook-Studio. Filter: Alle, Pflichtkriterien erfüllt, Mit Warnung, Angenommen, Abgelehnt. Tastatur: J/K, A (öffnet die Ziel-Auswahl), R, Leertaste. |
| `/projekte/[id]/clips` | Clip-Übersicht (Phase 3): Pakete je Kandidat mit Zähler „x von y gerendert“ und kurzem Spektrum-Glitch, wenn ein Paket fertig wird (nur beim Übergang, nicht beim Laden). Karten je Clip: Poster (oder Platzhalter), Plattform-Badge, Aspect, Dauer, Status als StatusCheck (Entwurf, Wird gerendert mit Fortschritt und Stufenanzeige aus den Events, Gerendert, Fehlgeschlagen orange mit `render_error`), Lautheit in Mono, Provenienz-Chip (C2PA signiert / übersprungen mit Grund), Werbelabel, Reframe-Hinweis (neutraler Crop, kein Detektor, orange), Lesetempo-Warnungen. Aktionen: MP4, SRT, VTT (Medien-URLs, im Demo deaktiviert mit Tooltip), Hook-Studio, Neu rendern, Ton-aus-Vorschau (lädt Hook und Captions nach und zeigt `SilentPreview` in der Karte). Live über SSE `/api/projects/[id]/clips/events`. |
| `/projekte/[id]/clips/[clipId]/hooks` | Hook-Studio: links fünf Varianten (Muster Identitäts-Anruf, Gegenposition, Offene Schleife, Ergebnis zuerst, Fehler-Warnung; Wortzähler, Lint-Hinweise grau, Claim-Issues orange), rechts drei Spalten (gesprochener Hook, On-Screen-Hook mit Overlay-Schalter, Post-Caption mit Tabs je Plattform und CTA). Live-Linter (`lib/copy/lint.ts`) und Live-Claim-Check (`lib/copy/claims.ts`) gegen `rubric.text` des Kandidaten. Speichern legt eine manuelle Version an, danach Hinweis „Für das Video neu rendern“ mit Button. Versionen-Liste mit Modell und Prompt in Mono. Ton-aus-Vorschau: CSS-Rahmen im Ausgabeformat, Safe Zones als Haarlinien, Hook-Overlay 3 s, Titelkarte 2,5 s, Caption-Karten im Preset-Stil an der Baseline, Bauchbinde, Scrubber und Play ohne Ton. |
| `/marke` | Markenprofil-Formular (Server Action): Anrede, Land, Gender-Modus, ASR-Variante, Plattform, Caption-Preset, Ton-Adjektive, Wörterbuch, geschützte Begriffe, gesperrte Phrasen. Karte „CI“: Primär-, Sekundär-, Akzent- und Caption-Highlight-Farbe als Hex-Felder mit Farbvorschau und AA-Kontrastprüfung gegen Weiß und Schwarz, Bauchbinde (Name, Funktion, an/aus), Hook-Overlay-Standard je Plattform; gespeichert in `brand_profiles.ci` und `caption_style`. Font-Upload kommt in Phase 4. |
| `/einstellungen` | Workspace, nur lesend: Tarif, Datenregion, Aufbewahrung, US-Subprozessoren, Training. |

## API

| Route | Zweck |
|---|---|
| `POST /api/tus/hooks` | tusd-v2-Hooks. `pre-create` prüft Rechte-Bestätigung und Größe, `post-finish` legt `sources` an, schreibt `audit_log` (`upload.created`, `rights.confirmed`) und startet den Temporal-Workflow. Der Browser sendet `client_ref` (UUID) als Metadatum, damit die Projekt-ID vorab bekannt ist. |
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
components/ui/      PillNav, Button, GlassCard, Toggle, StatusCheck, Grain, LightCone, BackgroundWord, Field, TagInput, Badge, Timecode
components/brand/   Wordmark, Mark (SVGs aus public/brand)
components/layout/  PageShell (Hintergrundwort → Lichtkegel → Glas → Inhalt)
lib/repo/           Repository-Interface, Postgres- und Demo-Implementierung, Seed-Daten
lib/db.ts           Postgres-Verbindung mit RLS-Kontext
lib/temporal.ts     Workflow-Start
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

## Offene Punkte

- Echte Authentifizierung und Workspace-Wechsel (Phase 4). Bis dahin: ein Dev-Workspace aus Env-Variablen.
- Video-Proxy im Editor: es gibt noch keine signierten URLs aus dem `derived`-Bucket; `NEXT_PUBLIC_MEDIA_BASE_URL` ist ein Provisorium.
- Die Postgres-Implementierung ist gegen das Schema geschrieben, aber ohne laufende Datenbank auf dieser Maschine nicht integrationsgetestet.
- Der tusd-Hook läuft im Kontext der Dev-Session; in Produktion muss `workspace_id` aus den Metadaten gegen die Session geprüft werden.
- Medien-URLs (MP4, SRT, VTT, Poster) sind unsigniert über `NEXT_PUBLIC_MEDIA_BASE_URL`; signierte URLs kommen in Phase 4. Font-Upload für das CI ebenfalls Phase 4.
- Die Postgres-Methoden für Clips, Hook- und Caption-Versionen sind gegen das Schema geschrieben, aber ohne laufende Datenbank nicht integrationsgetestet. `requestClipRender` ändert in Postgres nur `render_error`; den Status setzt der Worker nach dem Signal.
- Ohne Temporal bleibt ein Clip in Postgres `draft`; die Clip-Seite pollt bis zu 30 Minuten und zeigt „Wartet auf den Render“.
- Der Claim-Check vergleicht Ziffern wörtlich (wie der Worker); ausgeschriebene Zahlen im Transkript („vierzehntausend“) decken „14.000“ im Hook nicht ab. Das ist gewollt: der Mensch prüft.
- Die Bauchbinde in der stummen Vorschau ist eine Annäherung an `corporate_third`; Position und Schrift des Renders bestimmt der Worker.
- Verlängern und Kürzen arbeiten satzweise über `sentence_idx` des aktuellen Transkripts; Rubrik-Scores werden nach einer Grenzänderung nicht neu bewertet, sondern als veraltet markiert.
- Die Reihenfolge der Kandidatenliste bleibt nach einem Urteil stabil (Sortierung kommt vom Server beim Laden).
- Speichern der Sprecher-Namen erfolgt in `transcript_versions.stats.speaker_names`; eine eigene Tabelle gibt es im Schema nicht.
- Keine automatisierten Tests für die Web-App; `npm test` ist im Workspace noch nicht definiert.
