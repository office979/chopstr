# Datenvertrag: ClipCandidate (internes Ergebnisformat)

Vertragsversion: `clip_candidate_v1`. JSON-Schema (Draft 2020-12): `packages/schema/clip_candidate_v1.json`.
Erzeugt von `workers/chopstr_worker/pipeline/clip_candidate.py` (`from_result`, `from_report`), geprüft
ohne externe Bibliothek mit `clip_candidate.validate`. Das Schema steht im Code als `SCHEMA`; die
JSON-Datei ist seine Kopie, ein Test hält beide gleich.

Der ClipCandidate ist das interne Ergebnisformat aus Master-Prompt Abschnitt 21. Er ist ein Adapter
über `story_engine.CandidateResult` und verändert den Vertrag `candidates_v1` nicht. Die Web-App liest
ihn nicht. In `candidates.rubric` landet nur die kompakte Teilmenge (siehe unten), additiv.

Verdrahtung: Unter Fassung 2 schreibt `story_engine.run` (`attach_clip_candidates`) alle ClipCandidates
des Laufs in `DetectReport.clip_candidates` (Bericht im Storage) und die kompakte Teilmenge additiv in
die Rubrik jedes Kandidaten. Unter Fassung 1 schreibt der Adapter nichts (Rollback). Verstößt ein
ClipCandidate gegen den Vertrag, bleibt der Lauf gültig und `report.discarded` erhält
`clip_candidate_error`.

## Grundregeln

* Fehlende Datenbasis ist `null`. Nichts wird erfunden: kein Sprecher ohne Sprecherangabe in den
  Wörtern, keine Sicherheit ohne Grundlage, keine Wortgenauigkeit, die der Schnitt nicht hat.
* `source_in` und `source_out` eines Segments sind Schnittzeiten in Sekunden der Quelle (Original-Timeline):
  die Segmentgrenzen der Komposition. Ohne Kürzung und ohne Vor- und Nachlauf liegen sie auf Wortgrenzen
  (Anfang des ersten, Ende des letzten Wortes); mit Kürzung (AP7) und Vor- und Nachlauf (AP10b,
  `cut.padding`) können sie in einer Pause zwischen Wörtern liegen. Liegt ein Schnitt innerhalb 1 ms an
  einer Wortgrenze, gilt die Wortzeit. Die Wortgrenzen stehen getrennt über `word_ids`. `output_in` und
  `output_out` sind Sekunden der Clip-Timeline.
* „Die Quelle sagt das“ ist getrennt von „extern geprüft“: `externally_verified` ist immer `null`,
  bis es eine externe Prüfung gibt.
* Ohne Ergebnisdaten gibt es keine Kalibrierung: `calibration` ist `uncalibrated`, für die Heuristik
  und für ein Sprachmodell. `calibrated` ist für später reserviert.
* Alle Werte sind JSON-Typen, Zahlen endlich (kein NaN, kein Unendlich). `ClipCandidate.from_dict(cc.to_dict()) == cc`.
* Regeln über Felder hinweg (`clip_candidate.validate`, nur gegen dieses Schema): `audience_context` und
  `audience_context_provenance` sind beide gesetzt oder beide null; `output_in`/`output_out` nur mit
  `source_in`/`source_out`; `speaker_id` nur bei einem Segment mit Wörtern; eine entfernte Stelle endet
  nach ihrem Anfang; `word_id`, `text`, `prob` nur bei Wortbefunden, dort `word_id` Pflicht; ein
  angenommener Kandidat hat Segmente.

## Felder

| Feld | Typ | Herkunft | Null-Regel |
|---|---|---|---|
| `contract` | `"clip_candidate_v1"` | fest | nie null |
| `candidate_id` | Text | `cc_` plus SHA-256 aus Quelle, Transkriptversion, Richtlinie (`policy_version`), Engine (`story_engine.ENGINE_VERSION`), Satzspanne und Segmenten; deterministisch, derselbe Schnitt unter einer anderen Fassung hat eine andere ID | nie null |
| `source_asset_id` | Text | Aufrufer (`source.id`, die Quelle) | null ohne Angabe |
| `source_version` | Zahl oder Text | Aufrufer (`source.version`, die Transkriptversion) | null ohne Angabe |
| `objective` | Text | nur Brief `objective` (Kommunikationsziel); `wanted` (gewünschte Momente) ist kein Ziel und zählt nicht | null ohne `brief.objective` |
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
| `removed_spans` | Liste | Entfernungen innerhalb des Clips aus der Kürzung (AP7, `trim_plan`, über `rubric.removed_spans`): Pausen, Füllwörter, Ränder, semantische Splices | leere Liste ohne Kürzung (Fassung 1, `trim.enabled` oder Schalter `implementation.trim.enabled` aus) |
| `meaning_dependencies` | Liste | Story-Graph-Treffer (`story_graph_flags`): spätere Relativierung außerhalb des Clips | leere Liste ohne Treffer |
| `unresolved_questions` | Liste | offene Verweise (`rubric.unresolved_references`), `needs_earlier_context`, `ends_before_answer` | leere Liste ohne Befund |
| `quality_gate_results` | Objekt | die fünf Tore aus `candidates.gates`, unverändert | nie null |
| `editorial_subscores` | Objekt | Teilwerte nach Master-Prompt 19, Anker 0 bis 4, aus `rubric.anchor_subscores` (AP9): `audience_relevance`, `opening_clarity`, `content_strength`, `progress`, `evidence_quality`, `closing`, `naturalness` vom Sprachmodell ab `score_clip_v3` mit wörtlichem Beleg (`evidence`), `distinctiveness_vs_others` aus der Auswahl (Lemma-Jaccard zum nächsten Kandidaten); dazu `scale_max` 4, `calibration`, `source` | jeder Wert null, wenn nicht gemessen: Fassung 1, Heuristik, fehlender oder nicht gefundener Beleg; `calibration` immer `uncalibrated` |
| `rubric_points` | Objekt | die sieben Rubrikpunkte der Richtlinie (`rubric.rubric_points`, Skala 0 bis 2) und `scale_max` der Richtlinie | Einzelwerte null, wenn nicht messbar |
| `assessment_uncertainties` | Liste | siehe unten | leere Liste ohne Unsicherheit |
| `decision` | `accept` oder `reject` | angeboten (`report.candidates`) oder von `select_best` verworfen (`report.verworfen`); ohne Bericht aus `gate_passed` | nie null |
| `decision_reason` | Text | `candidates.why` bei `accept`; bei `reject` der Grund aus `report.discarded` (`gate` mit den gerissenen Toren, `overlap`, `limit`) | nie leer |
| `alternatives_considered` | Liste oder null | aus `from_report`: überdeckende Kandidaten (Anteil am kürzeren mindestens 0,4) mit Rolle | null, wenn der Aufrufer die Auswahl nicht kennt (`from_result` allein) |
| `model_version` | Text | `candidates.model_id` | null ohne Modellangabe |
| `prompt_version` | Objekt | alle gepinnten Prompts der Richtlinie, Name zu `name_vN` | nie null |
| `policy_version` | Text | `clip_policy_v1` oder `clip_policy_v2` | nie null |
| `externally_verified` | null | keine externe Prüfung | immer null |
| `calibration` | `uncalibrated` oder `calibrated` | keine Ergebnisdaten | heute immer `uncalibrated`; `calibrated` ist reserviert für eine Prognose, die an Ergebnisdaten geeicht ist |

### Spanne

`{ "source_in", "source_out", "word_range": [a, b], "sentence_range": [i, j], "note" }`. Zeiten aus dem
ersten und letzten Wort, Wortindizes inklusiv, Satzindizes aus der Satzzerlegung des Laufs
(`clip_candidate.sentences_for`, dieselbe wie in `story_engine.run`).

### Segment

| Feld | Herkunft | Null-Regel |
|---|---|---|
| `segment_id` | `s1`, `s2`, … in Abspielreihenfolge | nie null |
| `source_in`, `source_out` | Schnittzeiten: Segmentgrenzen der Komposition; innerhalb 1 ms an einer Wortgrenze die Wortzeit, sonst die Schnittzeit (Kürzung, Vor- und Nachlauf) | null, wenn kein Wort im Segment liegt |
| `output_in`, `output_out` | deterministisch: lückenlos ab 0, Länge wie in der Quelle, auf Millisekunden gerundet (`clip_candidate.output_timeline`, gleiche Rechnung wie `compose.remap_words`) | null, wenn `source_in` null ist |
| `speaker_id` | Sprecher der Wörter | null ohne Sprecherangabe oder bei mehreren Sprechern im Segment |
| `word_ids` | Indizes der Wörter, die vollständig im Segment liegen (Toleranz 1 ms); sie tragen die Wortgrenzen | leere Liste ohne Wörter |
| `verbatim_text` | Wörter des Segments, wörtlich | leer ohne Wörter |
| `editorial_role` | `teaser` oder `body` aus `candidates.segments[].role` | nie null |
| `boundary_confidence` | Sicherheit der Schnittkanten, 0 bis 1 (`transitions.segment_confidence`, die schwächere der beiden Kanten), nur unter Fassung 2 mit `cut.padding` | sonst null, dazu ein Eintrag `boundary_confidence_missing` |

`clip_candidate.output_timeline` rechnet mit `compose.output_timeline` (dieselbe Rechnung wie
`compose.remap_words`).

### Entfernte Stelle (`removed_spans[]`)

`{ "source_in", "source_out", "removal_reason", "protected_context_check" }`. Die Zeiten sind
Schnittzeiten wie bei den Segmenten: die Lücke zwischen zwei Segmenten der Komposition oder der Rand vor
dem ersten und nach dem letzten. Eine gekürzte Pause liegt deshalb nicht auf Wortgrenzen (vom Ende des
einen Segments bis zum Anfang des nächsten, die Zielpause bleibt stehen). Welche Wörter entfernt sind,
steht in `protected_context_check.detail.word_ids` und `text`; `detail.kind` ist `local`, `semantic`
oder `edge`. `removal_reason` nennt die Gründe, mit `+` verbunden (etwa `technical_pause`, `hard_filler`), `protected_context_check`
das Ergebnis der Schutzprüfung (`passed`, `touched_types`, `review_types`, `checked_spans`).

### Unsicherheit (`assessment_uncertainties[]`)

`{ "kind", "detail", "word_id", "text", "prob" }`. `word_id`, `text`, `prob` nur bei Wortbefunden, sonst null.

| `kind` | Wann |
|---|---|
| `low_confidence_number` | Zahl im Clip mit `prob` unter `transcribe.LOW_CONF_THRESHOLD` (0,5), auch Zahl- und Bruchzahlwörter („vierzig“, „Hälfte“, „anderthalb“); Testfall 6, am Audio prüfen |
| `low_confidence_name` | möglicher Name mit `prob` unter der Schwelle: großgeschrieben, kein Funktionswort, Pronomen oder Anrede („Sie“), nicht am Satzanfang; am Satzanfang nur nach einem Titel („Frau“, „Dr.“) oder wenn das Wort in der bekannten Namensliste steht (`names`, etwa `brand_vocab`) |
| `heuristic_only` | Bewertung ohne Sprachmodell; Humor, Sensitivität und Relativierungen ungeprüft |
| `nlp_unavailable` | Verbklammer nicht mit spaCy geprüft (Tor `verb_bracket`, `DetectReport.nlp_status`); `detail` unterscheidet „laut Richtlinie abgeschaltet“ von „spaCy-Modell fehlt“ (heuristisch oder gar nicht geprüft) |
| `boundary_from_pause` | eine Schnittkante ist nur durch eine Pause eine Satzgrenze (`dach_nlp.cut_boundary_kind` ergibt `pause_candidate`, dieselbe Regel wie Zerlegung und Tor) |
| `boundary_from_length_cap` | eine Schnittkante stammt aus der Satzlängengrenze von Regel v2 (`length_cap`), nicht aus Satzzeichen |
| `boundary_confidence_missing` | ein Segment hat keine `boundary_confidence` |
| `story_graph_unconfirmed` | eine spätere Relativierung ist gefunden, aber nicht bestätigt (`confirmed = null`) |

Die ASR-Sicherheit kommt aus `prob` (Transkript); fehlt `prob` oder ist es null, gilt `asr_confidence`
(so heißt das Feld in den Testfixtures). Ein Wort ohne beide Angaben gilt nicht als unsicher.

## Kompakte Teilmenge für `candidates.rubric`

`clip_candidate.compact_for_rubric(cc)` liefert genau diese Schlüssel, additiv zur bestehenden Rubrik:

| Schlüssel | Inhalt |
|---|---|
| `versions` | `{ "contract": "clip_candidate_v1", "model_version", "prompt_version", "policy_version" }` |
| `decision`, `decision_reason` | wie im ClipCandidate |
| `quality_gate_results` | wie im ClipCandidate |
| `assessment_uncertainties` | wie im ClipCandidate |
| `removed_spans` | wie im ClipCandidate |
| `calibration` | `uncalibrated` |

`editorial_subscores` und `rubric_points` stehen nicht in der Teilmenge: die Rubrik trägt sie schon als
`rubric.anchor_subscores` (AP9) und `rubric.rubric_points`; ein zweiter Schlüssel würde sie doppeln oder
überschreiben.

`candidates.policy_version` bleibt im `rubric`-JSON (`rubric.policy_version`); es gibt keine Migration.
Rollback: unter Fassung 1 schreibt der Adapter nichts in die Rubrik und keinen Bericht (Plan AP8).
