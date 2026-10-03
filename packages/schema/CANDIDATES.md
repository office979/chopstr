# Datenvertrag: Kandidaten (Phase 2)

Tabelle `candidates` (Migration 0001). Der Worker schreibt, die Web-App liest und setzt das
menschliche Urteil. Alle JSON-Spalten haben genau diese Form. Änderungen nur hier, mit Version.

Vertragsversion: `candidates_v1`

## Spalten

| Spalte | Inhalt |
|---|---|
| `id`, `source_id`, `version` | Version zählt pro Kandidat hoch, wenn Grenzen im Review geändert werden (neue Zeile mit gleicher `first_sent`-Herkunft in `rubric.parent_id`). |
| `segments` | `[{ "start": 812.4, "end": 861.0, "role": "body" }]` in Abspielreihenfolge, Originalzeit. Ein `body`-Segment (mehrere nur bei wirksamer Kürzung unter Fassung 2, heute nicht der Fall), davor optional ein Teaser (`role: "teaser"`, höchstens 6 s, ein Satz aus dem Body, `structure = payoff_first`, `rubric.teaser_satz`), wenn `compose.Composition.validate` ihn annimmt. `start_s`/`end_s` beschreiben nur den Body. Der Render ändert diese Spalte nie: unter Fassung 2 mit `cut.padding` steht die gepaddete Komposition nach dem Render in `clips.composition` (`docs/PIPELINE.md` 1.13). |
| `start_s`, `end_s` | Erstes Segment-Start, letztes Segment-Ende (Sekunden im Original). |
| `first_sent`, `last_sent` | Satzindizes des Laufs. Unter Fassung 1 aus `segment.sentences_from_words`, unter Fassung 2 aus der `sentence_idx` der Transkriptversion (`segment.sentences_from_annotated`); das Web zählt gleich. |
| `structure` | eine von `payoff_first`, `tension_first`, `hook_build_payoff`, `decision_story`, `how_to_list`, `loop`. |
| `rubric` | siehe unten. |
| `gates` | siehe unten. |
| `story_graph_flags` | Liste, siehe unten. |
| `risk_flags` | Liste von Strings: `humor`, `sensitive_topic`, `claim`, `ad`, `heuristic_only`. |
| `total` | Gesamtwert auf der Skala der Richtlinie (`story_engine.policy_total`): `Policy.gesamtwert(rubric_points)` über sieben Kriterien zu je 0 bis 2, also nominal 0 bis 14, mal `(1 - laenge_abzug)`, danach Klang-Faktor (mit Heatmap bis 16,1 möglich). Kein Wert auf 0 bis 10. Die fünf alten Schlüssel in `rubric.scores` (0 bis 10) und die Gewichte aus `brand_profiles.learned_weights` gehen nicht in `total` ein. |
| `gate_passed` | alle Pflichtkriterien erfüllt. `story_engine.select_best` verwirft jeden Kandidaten mit gerissenem Tor (Grund `gate` in `report.discarded`), deshalb schreibt der Worker nur Zeilen mit `gate_passed = true`. `false` entsteht nur durch eine Revision in der Web-App. |
| `why` | ein Satz Klartext, z. B. „Kernaussage in 38 Sekunden vollständig, Einstieg mit klarer Gegenposition, keine spätere Relativierung gefunden, passt für LinkedIn.“ |
| `model_id`, `prompt_version` | z. B. `eu.anthropic...` und `score_clip_v2` (unter Fassung 2 `score_clip_v3`; der gepinnte Prompt der Bewertung, `docs/PIPELINE.md` Abschnitt 6); Heuristik ohne Sprachmodell (Provider `local-heuristic`, nur Entwicklung und Demo): `model_id = "heuristic-v1"`, `prompt_version` bleibt gesetzt (der Heuristik-Provider liest den gerenderten Prompt), `risk_flags` enthält `heuristic_only`. |
| `human_verdict` | `accepted`, `rejected`, `edited` oder null. `verdict_reason`, `verdict_by`, `verdict_at`. Die Automatik setzt `accepted` mit `verdict_by = NULL`, außer sie hält den Kandidaten zurück (`humor`, `sensitive_topic`, freigaberelevante Behauptung, `claim_unchecked`): dann bleibt das Urteil null und `verdict_reason` beginnt mit „automatische Freigabe ausgesetzt“ (P27, P36). |

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

### Additive Rubrik-Schlüssel aus der Policy-Fassung 2

Nur unter Fassung 2 und nur, wenn der jeweilige Schalter wirkt (`docs/PIPELINE.md` Abschnitt 8). Keiner der obigen Schlüssel ändert sich; wer die neuen nicht kennt, ignoriert sie. Unter Fassung 1 fehlen sie, die Rubrik bleibt byte-gleich.

| Schlüssel | Wann | Inhalt |
|---|---|---|
| `sentence_rule`, `start_heal`, `pre_heal_scores`, `heal_rounds` | `implementation.sentence_rule` | Satzende-Regel des Laufs (`v2` oder `v1_fallback_no_punct`), Notiz zum Heilen des Anfangs (`healed`, `sentences`, `seconds`, `defects`), die Werte vor der Neubewertung, Zahl der Heilungen |
| `quality_gate_results`, `quality_gate_decision`, `gate_heal` | Schalter `implementation.gates.discard_hard` (heute an; die Regel `gates.discard_hard` ist heute aus, das ist der Berichtsmodus) | Ergebnis je hartem Gate (`passed`, `detail`, `evidence_word_ids`, `healable`, `origin`); Entscheidung `quality_gate_decision` (`decision` `accepted`, `reported` oder `rejected`, dazu `reason`, `detail`, `failed`, `flagged`, `unhealable`, `discard_hard`, `switch`; im Berichtsmodus nie `rejected`); Heilnotizen `gate_heal` (`front`, `back`, `null`, wenn nichts geheilt wurde). Mit diesem Schalter steht auch `heal_rounds` |
| `trim`, `removed_spans`, `composition` | Regel und Schalter `trim.enabled` (Regel heute aus) | Ergebnis der Kürzung (`applied`, `reason`, `reward_end`, `findings`, `composition`), entfernte Stellen, Komposition: bei wirksamer Kürzung `local_cuts`, `semantic_splices`, `density`, `is_debate`, `valid`, `issues` und `segments` (die Segmente der Kürzung, damit die Web-Revision und der Render erkennen, ob der Clip noch diese Schnitte hat), sonst `null` |
| `proposal_missing_v2_fields` | Suche (`search.payoff_first`) | Felder, die dem Modellvorschlag aus `propose_moments_v2` fehlten (der Vorschlag wurde abgewertet) |
| `opening_choice`, `alternatives_considered` | Regel `search.compare_openings` (heute an) | Einstiegsvergleich (`story_engine.compare_openings`): gewählter Einstieg mit `chosen`, `previous`, `changed`, `reason`, `options`; die nicht gewählten Originaleinstiege mit Satz, Dauer, Satzstärke, gerissenen Gates und je einem `reason` |
| `rescore_skipped` | nur wenn die Neubewertung nach einer Heilung oder einem Einstiegswechsel am Modellbudget scheitert | `"llm_budget"`; die Rubrik beschreibt dann die Spanne vor der Heilung |
| `anchor_subscores` | immer unter Fassung 2 | Teilwerte 0 bis 4 mit wörtlichem Beleg (`score_clip_v3`), siehe unten; `null` mit dem Pin `score_clip` 2 |
| `learned_weights_applied`, `learned_weights_reason` | immer unter Fassung 2 | `false` und der Grund: gelernte Gewichte (P14) ändern die Rangfolge nicht (P29) |
| `critic`, `critic_findings`, `promoted` | Regel und Schalter `roles.critic` (heute an) | Ablauf der Kritikerprüfung, geprüfte Befunde, Nachrücken aus der Reserve (`docs/PIPELINE.md` 1.10a), siehe unten |

Form der neuen Schlüssel (Werte beispielhaft). `anchor_subscores`: die sieben Teilwerte stammen vom Modell, `distinctiveness_vs_others` aus der Auswahl (`output.max_candidates`, Lemma-Jaccard zum nächsten Kandidaten); ein Wert ohne wörtliches Zitat im Kandidatentext ist `null` und steht in `ungrounded`, der Heuristik-Provider misst keinen (alle `null`). Alle Teilwerte sind `uncalibrated` und gehen in kein `total` ein.

```json
{
  "anchor_subscores": {
    "scale_max": 4, "calibration": "uncalibrated", "source": "score_clip_v3",
    "values": { "audience_relevance": 3, "opening_clarity": 2, "content_strength": 3, "progress": 2,
                "evidence_quality": null, "closing": 3, "naturalness": 2, "distinctiveness_vs_others": 4 },
    "evidence": { "audience_relevance": "wörtliches Zitat aus dem Kandidaten" },
    "ungrounded": ["evidence_quality"], "not_measured": [],
    "distinctiveness": { "nearest_jaccard": 0.12, "nearest": [60, 71], "method": "lemma_jaccard" }
  },
  "learned_weights_applied": false,
  "opening_choice": { "chosen": 41, "previous": 43, "changed": true, "reason": "deutlich stärkerer Einstieg (Satzstärke 6.0 gegen 3.0)", "options": 2 },
  "alternatives_considered": [
    { "opening_sent": 43, "first_sent": 43, "last_sent": 52, "duration_s": 38.4, "hook_type": null, "strength": 3.0,
      "gates_failed": [], "length_allowed": true, "length_good": true,
      "reason": "schwächerer Einstieg (Satzstärke 3.0 gegen 6.0)" }
  ],
  "critic": { "status": "checked", "prompt_version": "critique_clip_v1", "heuristic": false, "confirmed": false,
              "model_confirmed": false, "hook_source": "first_sentence", "dropped": [] },
  "critic_findings": [
    { "kind": "unclear_pronoun", "severity": "clarity", "evidence_quote": "wörtliches Zitat aus Clip oder Kontext",
      "sentence_refs": [41], "explanation": "ein Satz auf Deutsch", "location": "clip" }
  ],
  "promoted": { "from": "reserve", "replaces": [12, 20] }
}
```

`critic.status` ist `checked`, `llm_budget` (Modellbudget erschöpft), `invalid_answer` (Antwort unbrauchbar) oder `not_checked` (über der Obergrenze der Prüfungen); nur bei `checked` stehen `critic_findings` und die übrigen Felder. `critic_findings[].kind` ist eine von `hook_contradicted`, `claim_contradicted`, `unclear_pronoun`, `removed_condition`, `false_transition`, `reported_position`, `severity` eine von `fidelity`, `clarity`, `minor`, `location` `clip`, `context_before` oder `context_after`. Verworfen wird nur bei `confirmed` (Modell bestätigt, mindestens ein belegter Befund der Schwere `fidelity`, kein Heuristik-Lauf); der verworfene Kandidat steht dann mit Grund `critic:<art>` in `report.discarded`, nicht in der Tabelle. `promoted` steht am Nachrücker, `replaces` nennt die Sätze des verworfenen Kandidaten. Die Rubrik-Schlüssel `composition`, `removed_spans` und `trim` fallen bei einer Web-Revision mit geänderten Grenzen weg (siehe Review-Aktionen).

### Additive Rubrik-Schlüssel aus dem ClipCandidate (`clip_candidate_v1`)

Verdrahtet unter Fassung 2: `story_engine.attach_clip_candidates` ruft am Ende von `run` `clip_candidate.compact_for_rubric` auf und schreibt diese Schlüssel zusätzlich in die Rubrik jedes angebotenen und jedes verworfenen Kandidaten; der vollständige ClipCandidate steht nur im Bericht im Storage (`clip_candidates`), nicht in der Datenbank. Unter Fassung 1 fehlen die Schlüssel. Inhalt und Null-Regeln stehen in `packages/schema/CLIP_CANDIDATE.md`.

| Schlüssel | Inhalt |
|---|---|
| `versions` | `{ "contract": "clip_candidate_v1", "model_version", "prompt_version" (alle gepinnten Prompts), "policy_version" }` |
| `decision` | `accept` oder `reject` |
| `decision_reason` | Grund der Entscheidung, nie leer |
| `quality_gate_results` | die fünf Tore wie in `gates`, dazu die Ergebnisse der harten Gates, wenn sie liefen (die Schlüssel werden zusammengeführt) |
| `assessment_uncertainties` | Liste `{ "kind", "detail", "word_id", "text", "prob" }`, etwa unsicher erkannte Zahlen und Namen |
| `removed_spans` | Entfernungen im Clip; leer, solange die Kürzung nicht wirkt |
| `calibration` | `uncalibrated` |

Nicht in dieser Teilmenge: die Teilwerte 0 bis 4 stehen als `rubric.anchor_subscores` (AP9), die sieben
Rubrikpunkte als `rubric.rubric_points`; der ClipCandidate führt sie als `editorial_subscores` und `rubric_points`.

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

`gate_passed = alle passed`. Fassung 1: Fehlt spaCy, ist `verb_bracket.available = false` und `passed = true`
mit Hinweis (kein Blocker, aber sichtbar). Fassung 2: `verb_bracket` prüft über die Schnittgrenze und trägt `method` (`spacy`, `heuristic` oder `off`); ohne spaCy entscheidet die Heuristik, nur mit `verb_bracket.fallback: off` bleibt das Tor ungeprüft und sagt es. Das Tor `sentence_boundaries` meldet unter Fassung 2 „Grenze nur aus Pause“, wenn ein Pause-Kandidat die Grenze bildet.

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
| „Video clippen“ an einem zurückgehaltenen Clip | gilt als Annahme: erst `human_verdict = 'accepted'` mit dem Nutzer als `verdict_by`, bedingt auf ein noch offenes Urteil, dann der Render; ein abgelehnter oder ersetzter Kandidat wird nicht gerendert (P37). |
| ablehnen | `human_verdict = 'rejected'` mit `verdict_reason` (Pflicht, kurzer Grund: Lernsignal). |
| verlängern / kürzen | neue Zeile `version + 1` mit angepassten `first_sent`/`last_sent`, `segments`, `start_s`/`end_s`, `rubric.parent_id = <alte id>`, Gates werden deterministisch neu berechnet (Satzgrenzen, Open-Loop); Scores bleiben, `rubric.scores_stale = true`. Ändern sich die Grenzen, entfallen die schnittgebundenen Rubrik-Schlüssel (`composition`, `removed_spans`, `trim` und die kompakte ClipCandidate-Teilmenge, `apps/web/lib/candidates/revise.ts`); eine reine Titeländerung behält Segmente und diese Schlüssel. Alte Zeile bekommt `human_verdict = 'edited'`. |
| Kontext ergänzen | `rubric.suggested_title_card` überschreiben (max. 8 Wörter), neue Version. |

## Ereignisse

`pipeline_events.step = 'detect_candidates'` mit `progress` pro Kapitel; `finished`-Payload:
`{ "candidates": 12, "clips": 12, "gate_passed": 12, "chapters": 15, "provider": "bedrock-eu", "model_id": "...", "prompt_versions": ["propose_moments_v1", "score_clip_v2", "story_graph_confirm_v1"], "discarded": [...], "proposals": 40, "cached": false, "nlp_status": null }`. Unter Fassung 2 steht `score_clip_v3` statt `score_clip_v2` in `prompt_versions`, mit der Suche `propose_moments_v2` und `episode_overview_v1` und mit Kritiker zusätzlich `critique_clip_v1`; `nlp_status` ist `spacy`, `heuristic` oder `off`. Vier Felder kommen aus `analyze.step_summary` dazu: `gate_rejections` (Quote je Gate und je `critic:<art>`), `llm_budget`, `duplicates` (Zähler je Dublettenart) und `search` (Summen über die Kapitel); unter Fassung 1 fehlen sie.
`sources.status` läuft `analyzing → scoring → ready`.
