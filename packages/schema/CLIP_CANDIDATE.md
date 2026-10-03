# Datenvertrag: ClipCandidate (internes Ergebnisformat)

Vertragsversion: `clip_candidate_v1`. JSON-Schema (Draft 2020-12): `packages/schema/clip_candidate_v1.json`.
Erzeugt von `workers/chopstr_worker/pipeline/clip_candidate.py` (`from_result`, `from_report`), geprüft
ohne externe Bibliothek mit `clip_candidate.validate`. Das Schema steht im Code als `SCHEMA`; die
JSON-Datei ist seine Kopie, ein Test hält beide gleich.

Der ClipCandidate ist das interne Ergebnisformat aus Master-Prompt Abschnitt 21. Er ist ein Adapter
über `story_engine.CandidateResult` und verändert den Vertrag `candidates_v1` nicht. Die Web-App liest
ihn nicht. In `candidates.rubric` landet nur die kompakte Teilmenge (siehe unten), additiv.

Stand: Der Adapter ist gebaut, aber noch nicht in `DetectReport` verdrahtet. Geplant ist das Feld
`clip_candidates` im Bericht im Storage und die kompakte Teilmenge in der Rubrik (Plan AP8).

## Grundregeln

* Fehlende Datenbasis ist `null`. Nichts wird erfunden: kein Zeitstempel außerhalb einer Wortgrenze,
  kein Sprecher ohne Sprecherangabe in den Wörtern, keine Sicherheit ohne Grundlage.
* `source_in` ist immer der Anfang eines Wortes, `source_out` immer das Ende eines Wortes, beide in
  Sekunden der Quelle (Original-Timeline). `output_in` und `output_out` sind Sekunden der Clip-Timeline.
* „Die Quelle sagt das“ ist getrennt von „extern geprüft“: `externally_verified` ist immer `null`,
  bis es eine externe Prüfung gibt.
* Ohne Ergebnisdaten gibt es keine Kalibrierung: `calibration` ist `uncalibrated`, für die Heuristik
  und für ein Sprachmodell. `calibrated` ist für später reserviert.
* Alle Werte sind JSON-Typen. `ClipCandidate.from_dict(cc.to_dict()) == cc`.

## Felder

| Feld | Typ | Herkunft | Null-Regel |
|---|---|---|---|
| `contract` | `"clip_candidate_v1"` | fest | nie null |
| `candidate_id` | Text | `cc_` plus SHA-256 aus Quelle, Transkriptversion, Satzspanne und Segmenten; deterministisch | nie null |
| `source_asset_id` | Text | Aufrufer (`source.id`, die Quelle) | null ohne Angabe |
| `source_version` | Zahl oder Text | Aufrufer (`source.version`, die Transkriptversion) | null ohne Angabe |
| `objective` | Text | Brief: `objective`, sonst `wanted` (gewünschte Momente) | null, wenn der Brief nichts sagt |
| `audience_context` | Text | nur Brief `audience` | null ohne Brief-Angabe; nie geraten |
| `audience_context_provenance` | `explicit` oder null | `explicit`, wenn `audience_context` aus dem Brief kommt | null, wenn `audience_context` null ist |
| `central_idea` | Text | kein Stufenergebnis liefert sie heute | heute immer null |
| `viewer_promise` | Text | kein Stufenergebnis liefert es heute | heute immer null |
| `payoff_description` | Text | Beleg der Rubrik für `payoff` (wörtliches Zitat, `rubric.scores.payoff.evidence`) | null ohne Beleg |
| `narrative_type` | Text | `candidates.structure` | null, wenn leer |
| `opening_source_span` | Spanne | erster gespielter Satz: der Teaser (`rubric.teaser_satz`), sonst der erste Satz des Body | null nur ohne Satz |
| `required_context_spans` | Liste von Spannen | Sätze, die Reparatur, Heilung oder Kontextzugabe vorn (`rubric.repair.expanded_front`) oder hinten (`expanded_back`) ergänzt haben | leere Liste ohne Ergänzung |
| `payoff_source_span` | Spanne | der Satz im Clip, der den Beleg für `payoff` enthält | null, wenn kein Satz den Beleg enthält |
| `segments` | Liste | `candidates.segments` in Abspielreihenfolge, siehe unten | leere Liste nur bei `reject` erlaubt |
| `removed_spans` | Liste | Entfernungen innerhalb des Clips (AP7) | heute leer, es wird nichts entfernt |
| `meaning_dependencies` | Liste | Story-Graph-Treffer (`story_graph_flags`): spätere Relativierung außerhalb des Clips | leere Liste ohne Treffer |
| `unresolved_questions` | Liste | offene Verweise (`rubric.unresolved_references`), `needs_earlier_context`, `ends_before_answer` | leere Liste ohne Befund |
| `quality_gate_results` | Objekt | die fünf Tore aus `candidates.gates`, unverändert | nie null |
| `editorial_subscores` | Objekt | `rubric.rubric_points` (sieben Kriterien) und `scale_max` der Richtlinie | Einzelwerte null, wenn nicht messbar |
| `assessment_uncertainties` | Liste | siehe unten | leere Liste ohne Unsicherheit |
| `decision` | `accept` oder `reject` | angeboten (`report.candidates`) oder von `select_best` verworfen (`report.verworfen`); ohne Bericht aus `gate_passed` | nie null |
| `decision_reason` | Text | `candidates.why` bei `accept`; bei `reject` der Grund aus `report.discarded` (`gate` mit den gerissenen Toren, `overlap`, `limit`) | nie leer |
| `alternatives_considered` | Liste oder null | aus `from_report`: überdeckende Kandidaten (Anteil am kürzeren mindestens 0,4) mit Rolle | null, wenn der Aufrufer die Auswahl nicht kennt (`from_result` allein) |
| `model_version` | Text | `candidates.model_id` | null ohne Modellangabe |
| `prompt_version` | Objekt | alle gepinnten Prompts der Richtlinie, Name zu `name_vN` | nie null |
| `policy_version` | Text | `clip_policy_v1` oder `clip_policy_v2` | nie null |
| `externally_verified` | null | keine externe Prüfung | immer null |
| `calibration` | `uncalibrated` | keine Ergebnisdaten | immer `uncalibrated` |

### Spanne

`{ "source_in", "source_out", "word_range": [a, b], "sentence_range": [i, j], "note" }`. Zeiten aus dem
ersten und letzten Wort, Wortindizes inklusiv, Satzindizes aus der Satzzerlegung des Laufs
(`clip_candidate.sentences_for`, dieselbe wie in `story_engine.run`).

### Segment

| Feld | Herkunft | Null-Regel |
|---|---|---|
| `segment_id` | `s1`, `s2`, … in Abspielreihenfolge | nie null |
| `source_in`, `source_out` | Anfang des ersten und Ende des letzten Wortes, das vollständig im Segment liegt (Toleranz 1 ms für gerundete Grenzen) | null, wenn kein Wort im Segment liegt |
| `output_in`, `output_out` | deterministisch: lückenlos ab 0, Länge wie in der Quelle, auf Millisekunden gerundet (`clip_candidate.output_timeline`, gleiche Rechnung wie `compose.remap_words`) | null, wenn `source_in` null ist |
| `speaker_id` | Sprecher der Wörter | null ohne Sprecherangabe oder bei mehreren Sprechern im Segment |
| `word_ids` | Indizes der Wörter im Segment | leere Liste ohne Wörter |
| `verbatim_text` | Wörter des Segments, wörtlich | leer ohne Wörter |
| `editorial_role` | `teaser` oder `body` aus `candidates.segments[].role` | nie null |
| `boundary_confidence` | Sicherheit der Schnittkanten (AP10b) | heute immer null, dazu ein Eintrag `boundary_confidence_missing` |

`clip_candidate.output_timeline` nimmt `compose.output_timeline` (AP7), wenn es sie gibt, und rechnet
sonst lokal dasselbe. Der lokale Zweig entfällt, sobald AP7 eingecheckt ist.

### Entfernte Stelle (`removed_spans[]`)

`{ "source_in", "source_out", "removal_reason", "protected_context_check" }`, Zeiten an Wortgrenzen.
Heute nicht befüllt (AP7).

### Unsicherheit (`assessment_uncertainties[]`)

`{ "kind", "detail", "word_id", "text", "prob" }`. `word_id`, `text`, `prob` nur bei Wortbefunden, sonst null.

| `kind` | Wann |
|---|---|
| `low_confidence_number` | Zahl im Clip mit `prob` unter `transcribe.LOW_CONF_THRESHOLD` (0,5); Testfall 6, am Audio prüfen |
| `low_confidence_name` | großgeschriebenes Wort (Name oder Begriff) im Clip mit `prob` unter der Schwelle |
| `heuristic_only` | Bewertung ohne Sprachmodell; Humor, Sensitivität und Relativierungen ungeprüft |
| `nlp_unavailable` | spaCy fehlt: Verbklammer nur heuristisch oder gar nicht geprüft (Tor `verb_bracket`, `DetectReport.nlp_status`) |
| `boundary_from_pause` | Tor `sentence_boundaries` meldet „Grenze nur aus Pause“ (Regel v2, `rubric.sentence_rule`) |
| `boundary_confidence_missing` | ein Segment hat keine `boundary_confidence` |
| `story_graph_unconfirmed` | eine spätere Relativierung ist gefunden, aber nicht bestätigt (`confirmed = null`) |

Die ASR-Sicherheit kommt aus `prob` (Transkript); Testfixtures nennen sie `asr_confidence`, das gilt
gleichwertig. Ein Wort ohne Angabe gilt nicht als unsicher.

## Kompakte Teilmenge für `candidates.rubric`

`clip_candidate.compact_for_rubric(cc)` liefert genau diese Schlüssel, additiv zur bestehenden Rubrik:

| Schlüssel | Inhalt |
|---|---|
| `versions` | `{ "contract": "clip_candidate_v1", "model_version", "prompt_version", "policy_version" }` |
| `decision`, `decision_reason` | wie im ClipCandidate |
| `quality_gate_results` | wie im ClipCandidate |
| `editorial_subscores` | wie im ClipCandidate |
| `assessment_uncertainties` | wie im ClipCandidate |
| `removed_spans` | wie im ClipCandidate |
| `calibration` | `uncalibrated` |

`candidates.policy_version` bleibt im `rubric`-JSON (`rubric.policy_version`); es gibt keine Migration.
Rollback: unter Fassung 1 schreibt der Adapter später nichts in die Rubrik (Plan AP8).
