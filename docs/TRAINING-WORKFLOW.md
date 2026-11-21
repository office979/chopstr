# Trainings-Workflow: Gold-Set, mehrstufige Engine, Messung

Stand: 21.11.2026 (Auftrag T2). Ziel: chopstr ersetzt Clipping-Agenturen für Formate, Shows, Podcasts, Interviews
und Streams. Standard ist Short-Form (TikTok, Reels, Shorts). Dieses Dokument beschreibt, wie wir messen, ob die
Clips so gut sind wie die von Menschen veröffentlichten, und wie aus jedem Lauf Trainingsdaten werden.

## 1. Ablauf in einem Satz

Gold-Clips sammeln (Metadaten, URL, Fundstelle, Zerlegung), je Langform einen Job anlegen, den Job ohne Datenbank
durch die Pipeline laufen lassen, die Clips gegen das Gold vergleichen, eine Scorecard schreiben und die Ergebnisse
als Ranking- und Präferenzdaten exportieren.

```
gold validate ─► job create ─► run ─► compare ─► scorecard ─► export / feed
                                │
                                └─ Cache .local/eval-cache/<hash>/ (Medien, Transkript, Modellantworten)
```

## 2. Die Engine (mehrstufig, `CHOPSTR_ENGINE=tiered`)

| Stufe | Was | Modell (Standard) | Kosten |
|---|---|---|---|
| 0 | Szenen-Scan: Video auf 1 fps, 360p, Mono herunterrechnen, in Fenster von 10 min (20 s Überlappung) teilen, Ereignisse wie Lachen, Reaktion, Schrei, Applaus, Themenwechsel finden | Gemini Flash (`CHOPSTR_MM_PROVIDER=gemini`); ohne Provider lokaler Fallback aus Pegelsprüngen, Sprecherwechseln, ASR-Lachmarkern | lokal 0 € |
| A | Seeds aus Heatmap und Ereignissen | keins | 0 € |
| B | Vorfilter: je Transkriptblock (8 min) Kandidaten als Satzspannen mit Typ, Grund, Score | Haiku (`CHOPSTR_MODEL_PREFILTER`) | billig, Richtlinie aus dem Prompt-Cache |
| C | Editor nur für die besten K: exakte Grenzen als Wortnummern, Hook (erste 1 bis 3 s), Titel, On-Screen-Text, Post-Text je Plattform, Bewertung mit Belegen | Sonnet (`CHOPSTR_MODEL_EDITOR`) | teuer, deshalb nur Top-K; der Block liegt im Prompt-Cache |
| danach | Heilungen, harte Gates, Kritiker, ClipCandidate, Claim-Check wie im bisherigen Pfad | Richter-Stufe Haiku für Rückfragen | wenig |

- Ereignisse stehen als Pseudo-Sätze wie `[LACHT] (12:03, stark)` ohne Nummer im Blocktext. Ein Modell kann sie
  als Auflösung erkennen, aber nie als Schnittkante wählen; Copy und Captions laufen durch `strip_pseudo`.
- Volumen nach Länge: `candidates_per_source_hour` (12) mal Quellstunden, zwischen 3 und 40. Short-Form-Mindestlänge
  8 s, Höchstlänge 75 s (`implementation.engine` in `packages/editorial/clip_policy_v2.yaml`).
- Rückfall: `CHOPSTR_ENGINE=classic` oder Schalter aus (Standard), dann läuft der bisherige Pfad unverändert.
- Ohne Sprachmodell (`LLM_PROVIDER=local-heuristic`) laufen Vorfilter und Editor lokal (Payoff-Suche, Seeds). Das ist
  nur für Trockenläufe gedacht.

Nach dem ersten echten Lauf (T2c, 0 Clips aus 16 min Interview):

- Editor ab `editor_v2`: `editor_v1` hatte den Platzhalter `{candidate_words}` nicht im Text, der Editor sah also keine
  Wortnummern. v2 reicht sie durch, legt den Start auf den Anfang des Gedankens bzw. auf die Frage im Interview und
  lehnt nur mit einem Grund aus `tiered_engine.REJECT_REASONS` ab. Eine Ablehnung ohne gültigen Grund gilt nicht.
- Reparatur (`repair`, `editor_repair_v1`): scheitert ein Kandidat an Eigenständigkeit oder Satzanfang, oder lehnt der
  Editor mit `needs_context` ab, gibt es genau einen Versuch mit dem Befund und 60 s mehr Transkript davor
  (`repair_context_s`). Ergebnis je Versuch in `report.search.tiered.editor.repairs`.
- Ausbeute: mindestens `editor_per_source_hour` (12) Kandidaten je Quellstunde an den Editor, Ziel
  `target_clips_per_source_hour` (16, also 4 Clips bei 15 min, mindestens `min_target_clips`). Liegen weniger über den
  Toren, schiebt `backfill` die nächstbesten Vorfilter-Kandidaten nach, solange Budget da ist (`max_backfill`).
  Gezählt wird vor der Redundanzprüfung, ein nachgeschobener Kandidat kann dort noch fallen.
- Diagnose: jede Ablehnung in `report.discarded` trägt Spanne (`source_in`, `source_out`, `word_range`); Editor-
  Ablehnungen dazu `reject_code`, `reject_reason`, `reason_detail`, `scores`, `suggestion`; Gate-Ablehnungen
  `failed_gates`, `reason_detail`, `scores`.
- Robustes JSON: CLI-Hülle (Objekt oder Ereignisliste, `result`, `structured_output`), Codeblöcke auch ohne
  schließende Zäune, Vor- und Nachtext; ohne Tool-Block liest Anthropic den Text genauso. Danach genau ein
  Wiederholversuch mit Korrekturhinweis, der gescheiterte Versuch steht mit seinen Tokens im Kostenbuch.
- Bewertungsstufe: Neubewertung nach Heilung, Bestätigung und Kritiker laufen über `score_tier` (Standard `judge`,
  also Haiku) und sehen nur die Sätze des Kandidaten plus die Richtlinie, nie das ganze Transkript.
- Mehrsegment (Vorbereitung, `multi_segment: false`): der Editor darf `segments` (Wortspannen) liefern. Nur mit dem
  Schalter ersetzen sie die Segmente des Kandidaten bis `ClipCandidate.segments`; eine Umstellung (Cold Open) bleibt
  durch die Vertrauensregel in `compose` gesperrt.

## 3. Datenmodell

### Gold-Clip `gold_clip_v1` (`workers/eval/gold/gold_clip_v1.schema.json`)

```
{id, tier: format|podcast|streamer|own, creator,
 clip:{url, platform, published_at, duration_s, title, caption, hashtags[], metrics:{views, likes, comments, shares, saves, measured_at}},
 source:{url, title, duration_s, start_s, end_s, segments: [[start_s, end_s], ...],
         alignment: manual|transcript_match|description|unknown, confidence},
 breakdown:{hook_type, hook_text_first_3s, onscreen_text, cut_in:{kind, note}, cut_out:{kind, note}, length_s,
            context_setup, payoff, payoff_type, structure,
            edits:{cold_open, jump_cuts, reordered, n_source_segments, compression},
            captions_style, copy_pattern, language_notes},
 provenance:{collected_by, collected_at, method}, rights: "metadata_only"}
```

Unbekanntes ist `null`. Der Validator meldet je Clip Fehler, Vollständigkeit und fehlende Kernfelder. Für den
Vergleich zählt ein Clip nur mit `source.url`, `source.start_s` und `source.end_s`. Nie Medien ins Repo: nur URLs.

Verdichtete Clips: `source.segments` listet die Quellstellen in Clip-Reihenfolge (je Stelle Start vor Ende, Zahlen
ab 0), `edits.n_source_segments` ihre Zahl und `edits.compression` die Quellspanne geteilt durch die Cliplänge. Alle
drei sind optional. Wichtigster Befund aus `dach_v1.json` (25 Clips, 7 mit Fundstelle): 5 der 7 sind aus 2 bis 6
Quellstellen verdichtet, Kompression 2,5 bis 4,6. Top-Clips sind also oft kein zusammenhängender Ausschnitt.

### Job (`workers/eval/jobs/<id>.json`, `train_job_v1`)

Quelle als Datei (Dateiname oder Pfad im Repo, sha256, Cache-Referenz) oder URL, Briefing, Gold-IDs, Gold-Datei,
optional Transkript als Cache-Referenz. Absolute Pfade stehen nur im Cache (`source.json`), nie in der Job-Datei.

### Lauf (`.local/eval-cache/<hash>/runs/<run_id>/`)

`meta.json` (Job, Richtlinie, Engine, Modelle, Zeiten), `clips.json` (Rang, Zeiten, Scores, Hook, Copy, Merkmale),
`report.json` (DetectReport), `costs.json` (Kostenbuch), `events.json` (Szenen-Scan), nach `compare` `compare.json`,
nach `scorecard` `scorecard.md` und `scorecard.json`. Der Ergebnis-Cache liegt daneben unter `results/`: ein zweiter
Lauf mit gleichen Eingaben schickt keine Anfrage an ein Modell.

## 4. Befehle (im Ordner `workers`)

```bash
.venv/bin/python -m eval.train gold validate --gold eval/gold/dach_v1.json
.venv/bin/python -m eval.train gold stats --gold eval/gold/dach_v1.json

.venv/bin/python -m eval.train job create --source ~/Videos/folge.mp4 --brief "Gründer, Fehler mit Zahlen" \
    --gold dach-001,dach-002 --gold-file eval/gold/dach_v1.json
.venv/bin/python -m eval.train job create --source https://www.youtube.com/watch?v=... --brief brief.json

.venv/bin/python -m eval.train run --job eval/jobs/<id>.json [--provider anthropic|claude-cli|local-heuristic] \
    [--mm-provider gemini|mock|none] [--budget-eur 2] [--render]
.venv/bin/python -m eval.train compare --run <laufordner> [--iou 0.5 --center-s 10] [--batch] [--no-judge]
.venv/bin/python -m eval.train scorecard --run <laufordner>
.venv/bin/python -m eval.train export --format ranking|preferences [--run <laufordner>] [--with-text]
.venv/bin/python -m eval.train feed --run <laufordner> --gold eval/gold/dach_v1.json [--db postgres://...test]
```

- `run` braucht ffmpeg für Audio und Heatmap, eine ASR (`ASR_MODEL_DE`, faster-whisper) oder ein vorhandenes
  Transkript (`job create --transcript wort.json`), und für URL-Quellen `yt-dlp`. Downloads landen nur im Cache.
- `--render` schneidet die Clips einfach in 9:16 (mittig, ohne Captions und Branding) in den Cache, zum Ansehen.
  Der volle Render mit Captions läuft weiter über den Worker.
- `feed` schreibt in die Datei-Ablage `.local/eval-cache/learning/feed.jsonl`. In eine Datenbank nur mit `--db` und
  `--brand-profile`; Port 5499 und die Datenbank `chopstr` verweigert der Befehl hart.

## 5. Metriken

| Metrik | Bedeutung |
|---|---|
| Treffer | Vorschlag und Gesamtspanne des Gold-Clips überlappen mit IoU ab 0,5 oder ihre Mitten liegen höchstens 10 s auseinander (einstellbar), oder der Vorschlag erreicht IoU ab 0,5 gegen die Vereinigung der Quellstellen (`source.segments`); jeder Gold-Clip und jeder Vorschlag zählt höchstens einmal. `compare.json` nennt je Paar die Grundlage (`basis`: `span` oder `segments`) |
| `multi_segment_gold` | Anteil der Gold-Clips dieser Quelle mit mehr als einer Quellstelle. Unsere Engine schneidet bisher nur zusammenhängende Spannen, diese Clips kann sie nur über die Spanne treffen, nicht nachbauen |
| `segment_coverage_mean` | Bei Treffern auf verdichtete Gold-Clips: Anteil der Quellstellen-Sekunden, die der Vorschlag enthält (dazu `multi_segment_hits`, `hits_by_segments_only`) |
| Recall@K | Anteil der Gold-Clips, die unter den ersten K Vorschlägen (Rang nach Gesamtwert) getroffen werden; K = 3, 5, 10, alle |
| Precision@K | Anteil der ersten K Vorschläge, die einen Gold-Clip treffen |
| Grenzfehler | Start und Ende je Treffer in Sekunden (Vorschlag minus Gesamtspanne Gold): mittlerer Betrag und Median mit Vorzeichen |
| Längenabweichung | Länge Vorschlag minus Länge der Gesamtspanne Gold (bei verdichteten Clips länger als der fertige Clip) |
| Richter | hook, context, payoff, copy je 0 bis 10 mit einer Rubrik aus dem Gold-Breakdown; ohne Gold zur selben Stelle referenzfrei |
| Kosten | EUR und Tokens gesamt und je Quellstunde, getrennt nach Stufe und Modell; Laufzeit |

Ein fehlender Wert ist nie 0: ohne Gold steht `null`, in der Scorecard „nicht messbar“.

Richter: zuerst Haiku. Liegt ein Wert nahe der Schwelle (6 ± 1), folgt ein zweiter Haiku-Durchgang; weichen beide um
2 Punkte oder mehr ab, entscheidet Sonnet (`judge_escalate`). Sonst gilt der Mittelwert. Mit `--batch` laufen die
ersten Durchgänge über die Batch-API (halber Preis, Ergebnis bis zu 24 h später).

## 6. Keys und Anbieter

| Wofür | Variable | Hinweis |
|---|---|---|
| Vorfilter, Editor, Richter über Claude | `ANTHROPIC_API_KEY`, `LLM_PROVIDER=anthropic` | Anthropic ist kein EU-Anbieter: nur mit `CHOPSTR_ALLOW_NON_EU_PROVIDERS=1`, nie Sovereign |
| Erster Testlauf ohne Key | `LLM_PROVIDER=claude-cli` (oder `--provider claude-cli`) | ruft `claude -p` über ein Abo auf, 0 €, Kennzeichnung `dev_subscription`; unter `APP_ENV=production` gesperrt |
| Szenen-Scan über Google AI Studio | `GEMINI_API_KEY`, `CHOPSTR_MM_PROVIDER=gemini` | kein EU-Anbieter: nur mit `CHOPSTR_ALLOW_NON_EU_PROVIDERS=1` |
| Szenen-Scan über Vertex AI (EU) | `GOOGLE_APPLICATION_CREDENTIALS`, `VERTEX_PROJECT`, `VERTEX_LOCATION=europe-west4` | gilt als EU; Token per `cryptography` (falls installiert) oder `gcloud` |
| Modelle je Stufe | `CHOPSTR_MODEL_PREFILTER`, `CHOPSTR_MODEL_EDITOR`, `CHOPSTR_MODEL_JUDGE`, `CHOPSTR_MODEL_JUDGE_ESCALATE`, `CHOPSTR_MODEL_MM` | leer: Haiku, Sonnet, Haiku, Sonnet, Gemini Flash |
| Engine | `CHOPSTR_ENGINE=tiered` | im Worker; `eval.train run` nutzt immer die mehrstufige Engine |
| Budget | `CHOPSTR_RUN_BUDGET_EUR`, `CHOPSTR_RUN_BUDGET_TOKENS` oder `--budget-eur`, `--budget-tokens` | 0 heißt ohne Grenze |
| Preise | `CHOPSTR_PRICE_TABLE`, `CHOPSTR_BATCH_DISCOUNT` | Standardpreise sind Platzhalter, vor dem Betrieb prüfen |

Anthropic und AI Studio brauchen zusätzlich die Zustimmung des Workspaces zu US-Unterauftragnehmern
(`workspaces.allow_us_subprocessors`); der interne Eval-Mandant von `eval.train` hat sie. Vertex gilt nur in Regionen
mit Standort in der EU (`residency.VERTEX_EU_REGIONS`, etwa `europe-west3`, `europe-west4`); `europe-west2` (London)
und `europe-west6` (Zürich) sind gesperrt. Die Claude-CLI startet ohne `ANTHROPIC_API_KEY` in der Umgebung, damit
sie wirklich über das Abo läuft.

Keys nur in der Umgebung des Prozesses, nie in Code, Job-Dateien oder Logs. `CHOPSTR_ALLOW_NON_EU_PROVIDERS` ist
standardmäßig aus; ohne sie sperrt der Residency-Guard `api.anthropic.com` und `generativelanguage.googleapis.com`
schon vor dem Verbindungsaufbau.

## 7. Kostenlogik

- Jeder Aufruf geht ins Kostenbuch (`costlog.RunLedger`): Tokens (Eingabe, aus dem Cache gelesene Eingabe,
  Cache-Schreiben, Ausgabe), Modell, Stufe, geschätzte EUR nach Preistabelle. Batch-Aufrufe kosten den Batch-Anteil,
  die CLI und lokale Stufen 0 €.
- Sparen: Haiku sieht alles, Sonnet nur die Top-K; System-Prompt, Richtlinie und Transkriptblock stehen als Cache-Blöcke
  vorn, nur die Aufgabe ist neu; der Ergebnis-Cache verhindert doppelte Rechnung; Richter-Eskalation nur bei Streit.
- Budget: vor jeder Stufe prüft das Kostenbuch. Ist das Budget erreicht, fallen die restlichen Modellstufen weg (der
  Vorfilter läuft lokal weiter, der Editor übernimmt die Grenzen des Vorfilters), und `skipped` im Bericht nennt die
  Stufe. Der Lauf endet sauber mit dem, was bis dahin da ist.
- `claude-cli` kostet 0 € (Abo), aber jede Zeile im Kostenbuch trägt `eur_api_equivalent`: dieselben Tokens zum
  Listenpreis der Tabelle (Alias `haiku` als `claude-haiku` usw.). Scorecard und Verlauf zeigen den Wert. Die CLI-Tokens
  enthalten den eigenen Systemprompt und die Werkzeuge der CLI (im ersten Lauf rund 70 000 Tokens je Aufruf, fast
  alles Cache), deshalb liegt das Äquivalent deutlich über einem echten API-Lauf. `CHOPSTR_CLAUDE_CLI_ARGS` reicht
  Zusatzflags an `claude -p` durch, etwa um diesen Systemprompt zu verkleinern (Flags vorher gegen die installierte
  Version prüfen).

## 8. Grenzen (ehrlich)

- Die Engine ist mit gemockten Modellen getestet, nicht gegen echte Anthropic- oder Gemini-Antworten. Der erste echte
  Lauf (mit `claude-cli` oder einem Key) muss Schema-Treue, Kosten und Qualität erst zeigen.
- Die Standardpreise und Modellnamen sind Annahmen; vor dem Betrieb gegen die Preisliste prüfen und per ENV setzen.
- Die Grenzen des Editors werden auf Satzgrenzen gelegt, weil die Gates an Satzgrenzen prüfen. Ein Schnitt mitten im
  Satz steht in `cut_inside_sentence`, wird aber nicht umgesetzt.
- Gemini bekommt das Fenster inline (bis etwa 20 MB). Sehr lange Fenster oder hohe Auflösung brechen mit Hinweis ab;
  die Files-API ist nicht angebunden.
- `--render` ist ein Sichtungsrender ohne Captions. `feed --db` ist gegen keine echte Datenbank getestet.
- Gelernte Rubrik-Gewichte sind erst ab 20 Zeilen belastbar (`weights_reliable`); die Engine nutzt sie nicht für die
  Rangfolge (Entscheidung P29).
- `eval/gold/dach_v1.json` hat 25 Clips, aber nur 7 mit Fundstelle (`ready_for_compare`); die übrigen 18 zählen erst
  nach Ausrichtung. Die Fundstellen stammen aus einem 4-Gramm-Abgleich mit Auto-Untertiteln (Konfidenz teils unter
  0,5), kurze Quellstellen können Fehltreffer sein (`gold validate` meldet Stellen außerhalb der Spanne als Hinweis).
- Die Engine baut standardmäßig keine Clips aus mehreren Quellstellen (`multi_segment: false`). Bei verdichteten
  Gold-Clips misst `compare` nur, ob die Spanne getroffen ist und wie viel der Quellstellen der Vorschlag enthält.
