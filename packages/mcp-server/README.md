# @chopstr/mcp-server

MCP-Server für chopstr. Er verbindet Claude Desktop, Claude Code, ChatGPT und andere MCP-fähige Clients mit
der öffentlichen chopstr-API (`/api/v1`): Quellen anlegen, Transkripte lesen, Kandidaten prüfen, Clips
rendern, Hooks schreiben, Gast-Freigaben anfordern und Clips veröffentlichen.

Grundsatz wie im Produkt: Die KI schlägt vor, ein Mensch gibt frei. Jedes schreibende Tool braucht
`confirm: true` im Aufruf. Ohne Bestätigung liefert das Tool nur eine Vorschau dessen, was passieren würde.
Es gibt keine stillen Aktionen.

## Installation

Im Monorepo (Node 20 oder neuer):

```bash
npm install
npm run build --workspace packages/mcp-server
```

Danach liegt der Server unter `packages/mcp-server/dist/cli.js`, im Monorepo auch als Bin
`node_modules/.bin/chopstr-mcp`. Nach einer Veröffentlichung auf npm reicht `npx chopstr-mcp`.

## Konfiguration

| Variable | Zweck |
|---|---|
| `CHOPSTR_API_KEY` | Pflicht. API-Schlüssel `chp_live_…`, wird als `Authorization: Bearer` gesendet. Anlegen unter `/entwickler` in der Web-App. |
| `CHOPSTR_API_URL` | Basis-URL der API. Standard `http://localhost:3000/api/v1`. |
| `CHOPSTR_API_TIMEOUT_MS` | Zeitlimit je Anfrage, Standard 30000. |

Kommandozeile:

```
chopstr-mcp                        stdio (Standard)
chopstr-mcp --http 8765            Streamable HTTP unter http://127.0.0.1:8765/mcp
chopstr-mcp --http 8765 --host 0.0.0.0   auf allen Schnittstellen, nur hinter einem Proxy mit TLS
```

Der Client verhält sich zur API so: Zeitlimit 30 s, keine Wiederholung bei 4xx, zwei Wiederholungen bei
5xx und Netzfehlern. Fehler der API (`{ error: { code, message } }`) werden in verständliche deutsche
Meldungen übersetzt, unter anderem 402 (Kontingent erschöpft), 403 (Scope oder Rolle fehlt) und 409
(Gast-Freigabe fehlt oder Zustand passt nicht).

### Claude Desktop

`claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "chopstr": {
      "command": "npx",
      "args": ["-y", "chopstr-mcp"],
      "env": {
        "CHOPSTR_API_URL": "https://app.chopstr.example/api/v1",
        "CHOPSTR_API_KEY": "chp_live_…"
      }
    }
  }
}
```

Lokaler Pfad statt npx:

```json
{
  "mcpServers": {
    "chopstr": {
      "command": "node",
      "args": ["/pfad/zu/chopstr/packages/mcp-server/dist/cli.js"],
      "env": { "CHOPSTR_API_URL": "http://localhost:3000/api/v1", "CHOPSTR_API_KEY": "chp_live_…" }
    }
  }
}
```

### Claude Code

```bash
claude mcp add chopstr -e CHOPSTR_API_KEY=chp_live_… -e CHOPSTR_API_URL=https://app.chopstr.example/api/v1 -- npx -y chopstr-mcp
```

Lokaler Pfad:

```bash
claude mcp add chopstr -e CHOPSTR_API_KEY=chp_live_… -- node /pfad/zu/chopstr/packages/mcp-server/dist/cli.js
```

Prüfen mit `claude mcp list`, entfernen mit `claude mcp remove chopstr`.

### ChatGPT und andere Clients über Streamable HTTP

Server starten:

```bash
CHOPSTR_API_KEY=chp_live_… CHOPSTR_API_URL=https://app.chopstr.example/api/v1 chopstr-mcp --http 8765
```

Der MCP-Endpunkt ist `http://127.0.0.1:8765/mcp` (Streamable HTTP mit Sitzungen, `Mcp-Session-Id`),
`GET /healthz` antwortet mit `{ ok: true }`. Für Clients außerhalb der Maschine den Server hinter einen
Reverse-Proxy mit TLS legen und die URL `https://…/mcp` im Client als MCP-Server (Custom Connector) eintragen.

Schlüssel je Sitzung: Sendet der Client einen Header `Authorization: Bearer chp_live_…`, benutzt der Server
diesen Schlüssel für die Sitzung statt `CHOPSTR_API_KEY`. So kann ein gemeinsam betriebener HTTP-Server
mehrere Workspaces bedienen, ohne dass Schlüssel auf dem Server liegen müssen (ein Schlüssel als Fallback
bleibt trotzdem Pflicht beim Start).

## Sicherheitshinweise

- **Minimale Scopes.** Für reine Recherche einen Schlüssel mit Scope `read` anlegen. `write` erst, wenn
  Kandidaten und Hooks bearbeitet werden sollen, `publish` nur für Veröffentlichungen. `admin` braucht der
  MCP-Server nie.
- **Bestätigungspflicht.** Schreibende Tools (`create_source_from_url`, `accept_candidate`,
  `reject_candidate`, `revise_candidate`, `render_clip`, `write_hooks`, `request_guest_approval`,
  `publish_clip`) führen ohne `confirm: true` nichts aus. Die Server-Instruktionen weisen das Modell an,
  `confirm` nur nach ausdrücklicher Zustimmung des Nutzers zu setzen. `publish_clip` wirkt nach außen und
  ist über die API nicht rücknehmbar.
- **Keine Transkripte in Logs.** Der Server schreibt nur Startmeldungen und Fehler auf stderr, nie
  Anfrage- oder Antwortinhalte. Transkripte bleiben in der MCP-Verbindung zum Client. Wer den HTTP-Modus
  hinter einem Proxy betreibt, sollte dort Request-Bodies nicht protokollieren.
- **HTTP-Modus nur lokal oder hinter TLS.** Standard-Bind ist `127.0.0.1`. Der Endpunkt selbst hat keine
  eigene Authentifizierung; Zugriffsschutz kommt vom Netz (lokal) oder vom Proxy.
- **Rechte an Quellen.** `create_source_from_url` verlangt `rights_confirmed: true`, `source_owner` und
  `source_url`. Ohne bestätigte Rechte legt der Server keine Quelle an.

## Tool-Referenz

Alle Tools antworten mit einem kurzen deutschen Resümee plus einem JSON-Anhang (`structuredContent`).
Listen sind auf 50 Einträge begrenzt.

| Tool | Scope | Zweck | Wichtige Parameter |
|---|---|---|---|
| `list_sources` | read | Quellen mit Status und Dauer | `status`, `limit` |
| `get_source` | read | Details einer Quelle | `source_id` |
| `create_source_from_url` | write | Quelle aus Video-URL anlegen, Ingest starten | `title`, `source_url`, `source_owner`, `rights_confirmed: true`, `brand_profile_id`, `brief`, `confirm` |
| `get_transcript` | read | Kurzfassung (Dauer, Sprecher, erste 200 Wörter) oder Fenster mit Sprechern und Timecodes | `source_id`, `start_s`, `end_s` |
| `list_candidates` | read | Kandidaten nach Score mit Gates, Flags, Story-Graph, Begründung | `source_id`, `gate_passed`, `verdict` (`accepted`, `rejected`, `edited`, `open`), `limit` |
| `accept_candidate` | write | Kandidat annehmen, Clips je Plattform anlegen und rendern | `candidate_id`, `platforms`, `confirm` |
| `reject_candidate` | write | Kandidat ablehnen, Grund ist Pflicht | `candidate_id`, `reason`, `confirm` |
| `revise_candidate` | write | Verlängern, kürzen oder Titelkarte (max. 8 Wörter), neue Version | `candidate_id`, `first_sent`, `last_sent`, `title_card`, `confirm` |
| `list_clips` | read | Clips einer Quelle mit Status und Gast-Freigabe-Hinweis | `source_id`, `status`, `limit` |
| `get_clip` | read | Clip mit Medien-URLs, Hook und Varianten, Lautheit, Provenienz, Render-Plan-Kurzfassung | `clip_id` |
| `render_clip` | write | Render oder Re-Render starten | `clip_id`, `confirm` |
| `write_hooks` | write | Manuelle Hook-Version speichern; prüft Wortlimits 12 (gesprochen) und 9 (im Bild) vor dem Senden; Vorschau zeigt die KI-Varianten | `clip_id`, `spoken_hook`, `onscreen_hook`, `pattern`, `post_captions`, `cta`, `confirm` |
| `request_guest_approval` | write | Freigabe der gezeigten Person anfordern (Link 14 Tage) | `clip_id`, `guest_name`, `guest_email`, `message`, `confirm` |
| `publish_clip` | publish | Sofort oder geplant veröffentlichen | `clip_id`, `connection_id`, `scheduled_for` (ISO 8601 mit Zeitzone), `caption`, `title`, `confirm` |
| `get_usage` | read | Stundenkontingent des Monats | |

### Resources

| URI | Inhalt |
|---|---|
| `chopstr://sources/{id}/transcript` | Transkript als Text mit Sprechern und Timecodes |
| `chopstr://clips/{id}/render-plan` | Vollständiger Render-Plan (`render_plan_v1`) als JSON |
| `chopstr://usage` | Kontingent des Monats als JSON |

### Prompts

| Name | Zweck |
|---|---|
| `review_session` | Anleitung für eine Review-Sitzung: Eigenständigkeit, Sinntreue, keine Zahl ohne Beleg, Humor immer Mensch. Argumente `source_id`, `focus`. |
| `hook_brief` | Regeln aus `packages/prompts/hooks_v1.md` als Vorlage. Argumente `address`, `country`, `platform`, `protected_terms`, `clip_text`. |

## Entwicklung

```bash
npm run build --workspace packages/mcp-server
npm test --workspace packages/mcp-server
npm run lint --workspace packages/mcp-server
```

Die Tests laufen gegen einen gemockten API-Server (`test/mock-api.ts`, Node `http`) und sprechen den
MCP-Server über den SDK-Client mit In-Memory-Transport sowie über Streamable HTTP an. Geprüft werden
unter anderem Bestätigungspflicht, Fehlerübersetzung, Fensterung des Transkripts, Wortlimits und die
Übereinstimmung des eingebetteten Hook-Briefings mit `packages/prompts/hooks_v1.md`.

## Abweichungen und offene Punkte gegenüber `packages/schema/PHASE5.md`

- `request_guest_approval` ruft `POST /clips/{id}/guest-approval` mit `{ guest_name, guest_email, message }`
  auf und erwartet `{ approval, link }`. Der Endpunkt ist Teil des Vertrags (PHASE5.md) und in der API umgesetzt;
  gegen die echte API geprüft.
- Antwortformen: Der Server akzeptiert Listen roh oder unter `sources`, `candidates`, `clips` (auch
  `data`, `items`) und Einzelobjekte roh oder unter `source`, `clip`, `candidate`, `hook`, `publication`,
  `approval`. Medien-URLs werden aus `media.{video_url, poster_url, srt_url, vtt_url}` oder gleichnamigen
  Feldern am Clip gelesen.
- `list_clips` braucht eine `source_id`, weil der Vertrag nur `GET /sources/{id}/clips` und keine
  workspace-weite Clip-Liste vorsieht.
- `get_transcript` erwartet `words[]` mit `speaker`, `start`, `end` und Sprechernamen unter
  `stats.speaker_names` (wie `transcript_versions`).
