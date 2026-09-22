# Datenvertrag: Kandidaten (Phase 2)

Tabelle `candidates` (Migration 0001). Der Worker schreibt, die Web-App liest und setzt das
menschliche Urteil. Alle JSON-Spalten haben genau diese Form. Änderungen nur hier, mit Version.

Vertragsversion: `candidates_v1`

## Spalten

| Spalte | Inhalt |
|---|---|
| `id`, `source_id`, `version` | Version zählt pro Kandidat hoch, wenn Grenzen im Review geändert werden (neue Zeile mit gleicher `first_sent`-Herkunft in `rubric.parent_id`). |
| `segments` | `[{ "start": 812.4, "end": 861.0, "role": "body" }]` in Abspielreihenfolge. Phase 2 liefert genau ein `body`-Segment; Teaser (`role: "teaser"`) kommen in Phase 3. |
| `start_s`, `end_s` | Erstes Segment-Start, letztes Segment-Ende (Sekunden im Original). |
| `first_sent`, `last_sent` | Satzindizes (aus `segment.sentences_from_words` über das aktuelle Transkript). |
| `structure` | eine von `payoff_first`, `tension_first`, `hook_build_payoff`, `decision_story`, `how_to_list`, `loop`. |
| `rubric` | siehe unten. |
| `gates` | siehe unten. |
| `story_graph_flags` | Liste, siehe unten. |
| `risk_flags` | Liste von Strings: `humor`, `sensitive_topic`, `claim`, `ad`, `heuristic_only`. |
| `total` | gewichteter Score 0 bis 10 (`hook 0.30, payoff 0.25, specificity 0.20, tension 0.15, audience_fit 0.10`; Gewichte aus `brand_profiles.learned_weights` können überschreiben). |
| `gate_passed` | alle Pflichtkriterien erfüllt. |
| `why` | ein Satz Klartext, z. B. „Kernaussage in 38 Sekunden vollständig, Einstieg mit klarer Gegenposition, keine spätere Relativierung gefunden, passt für LinkedIn.“ |
| `model_id`, `prompt_version` | z. B. `eu.anthropic...` und `score_clip_v1`; Heuristik ohne Sprachmodell (Provider `local-heuristic`, nur Entwicklung und Demo): `model_id = "heuristic-v1"`, `prompt_version` bleibt gesetzt (der Heuristik-Provider liest den gerenderten Prompt), `risk_flags` enthält `heuristic_only`. |
| `human_verdict` | `accepted`, `rejected`, `edited` oder null. `verdict_reason`, `verdict_by`, `verdict_at`. |

## `rubric`

```json
{
  "contract": "candidates_v1",
  "text": "Wörtlicher Clip-Text (Sätze first_sent..last_sent, mit Sprechern)",
  "speakers": ["SPEAKER_00"],
  "duration_s": 38.2,
  "scores": {
    "hook":         { "value": 8, "weight": 0.30, "evidence": "wörtliches Zitat aus dem Clip" },
    "payoff":       { "value": 7, "weight": 0.25, "evidence": "..." },
    "specificity":  { "value": 9, "weight": 0.20, "evidence": "..." },
    "tension":      { "value": 6, "weight": 0.15, "evidence": "..." },
    "audience_fit": { "value": 7, "weight": 0.10, "evidence": "..." }
  },
  "unresolved_references": ["wie gesagt"],
  "needs_earlier_context": false,
  "ends_before_answer": false,
  "is_humor": false,
  "sensitive_topic": false,
  "suggested_title_card": "",
  "repair": { "rounds": 1, "expanded_front": 1, "expanded_back": 0, "failed": false },
  "proposal_why": "Begründung aus Stufe 2 (propose_moments)",
  "parent_id": null
}
```

## `gates`

```json
{
  "standalone":          { "passed": true,  "detail": "keine offenen Verweise" },
  "fidelity":            { "passed": true,  "detail": "keine entfernte Verneinung oder Einschränkung" },
  "sentence_boundaries": { "passed": true,  "detail": "Start und Ende an Satzgrenzen" },
  "verb_bracket":        { "passed": true,  "detail": "kein Schnitt in einer Verbklammer", "available": true },
  "no_open_loop":        { "passed": false, "detail": "endet auf „aber“" }
}
```

`gate_passed = alle passed`. Fehlt spaCy, ist `verb_bracket.available = false` und `passed = true`
mit Hinweis (kein Blocker, aber sichtbar).

## `story_graph_flags`

```json
[
  {
    "sentence_idx": 143,
    "seconds_after": 21.5,
    "marker": "das heißt aber nicht",
    "text": "Das heißt aber nicht, dass das für jede Branche gilt.",
    "overlap": 0.31,
    "confirmed": true,
    "reason": "Der spätere Satz beschränkt die Aussage auf eine Branche.",
    "repair": "extend",
    "suggestion": "Clip bis Satz 143 verlängern oder Einschränkung als Text einblenden"
  }
]
```

`confirmed` ist `true` nur nach LLM-Bestätigung (`story_graph_confirm_v1`); ohne Sprachmodell bleibt
`confirmed = null` (Heuristik-Treffer, Mensch prüft). `repair` ist `"extend"` oder `"overlay"`.

## Review-Aktionen der Web-App

| Aktion | Wirkung |
|---|---|
| annehmen | `human_verdict = 'accepted'`, `audit_log candidate.accepted`; wenn Temporal erreichbar: Signal `approve(candidate_id, destination)` an `project-<source_id>` (Render folgt in Phase 3). |
| ablehnen | `human_verdict = 'rejected'` mit `verdict_reason` (Pflicht, kurzer Grund: Lernsignal). |
| verlängern / kürzen | neue Zeile `version + 1` mit angepassten `first_sent`/`last_sent`, `segments`, `start_s`/`end_s`, `rubric.parent_id = <alte id>`, Gates werden deterministisch neu berechnet (Satzgrenzen, Open-Loop); Scores bleiben, `rubric.scores_stale = true`. Alte Zeile bekommt `human_verdict = 'edited'`. |
| Kontext ergänzen | `rubric.suggested_title_card` überschreiben (max. 8 Wörter), neue Version. |

## Ereignisse

`pipeline_events.step = 'detect_candidates'` mit `progress` pro Kapitel; `finished`-Payload:
`{ "candidates": 12, "gate_passed": 9, "chapters": 15, "provider": "bedrock-eu", "model_id": "...", "prompt_versions": ["propose_moments_v1", "score_clip_v1", "story_graph_confirm_v1"] }`.
`sources.status` läuft `analyzing → scoring → ready`.
