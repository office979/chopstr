# Redaktioneller Testsatz editorial_v1

Version: `editorial_v1`, angelegt am 03.10.2026 gegen Stand 070d916.

## Zweck

Dieser Testsatz hält fest, was ein Clip aus einem bestimmten Gesprächsausschnitt redaktionell
einhalten muss. Er setzt die verbindlichen Testfälle aus Master-Prompt Abschnitt 27
(`docs/MASTER-PROMPT-CORE-CLIPPING.md`) als prüfbare Fixtures um: keine Sinnumkehr durch einen
frühen Out-Point, Bedingungen und Korrekturen bleiben erhalten, fremde Positionen bleiben
zugeordnet, Pronomen haben einen Bezug, Pausen und stilles Zeigen werden nicht mechanisch entfernt,
Pointen behalten ihr Setup, Frage und Antwort bleiben richtig verbunden, schwaches Material wird
ehrlich verworfen, Dubletten werden reduziert, unsichere Zeitstempel behaupten keine Präzision und
Anweisungen im Transkript werden als Inhalt behandelt.

Die redaktionelle Abnahme aus Abschnitt 27 verlangt „keine bekannten Sinnumkehrungen im kritischen
Testsatz“. Dieser Ordner ist dieser kritische Testsatz.

## Aufbau

* `cases/*.json`: ein Fall je Datei, 14 Pflichtfälle. Jeder Fall enthält `id`, `version`, `title`,
  `description`, `source`, `language`, eine Wortliste `words` mit `text`, `start`, `end`, `speaker`
  und teilweise `asr_confidence`, bei der stillen Demonstration zusätzlich `visual_events`, und die
  Erwartungen unter `expected`.
* `harness.py`: lädt und prüft die Fälle (`load_cases`, `validate_case`) und stellt Prüfungen für
  spätere Schnittstellen bereit (`assert_clip_respects_case`, `assert_rejected`,
  `assert_protected_spans_kept`, `assert_boundary_confidence_honest`, `assert_single_survivor`,
  `assert_uncertainty_marked`, `assert_instruction_ignored`, `assert_humor_flagged`,
  `assert_clip_candidate_schema`).
* `../test_editorial_v1.py`: prüft die Fälle gegen die heute vorhandene Logik und den Harness mit
  synthetischen guten und schlechten Schnittplänen.

### Erwartungen je Fall

Alle Wortangaben sind Indizes in `words`, Bereiche sind inklusiv `[a, b]`.

* `must_include_word_ranges`: Bereiche, die ein Clip aus diesem Material vollständig enthalten muss.
* `forbidden_out_points`: Wortindex, auf dem ein Clip oder Segment nicht enden darf.
* `forbidden_in_points`: Wortindex, mit dem ein Clip oder Segment nicht beginnen darf.
* `expect_reject`: `value` und `reason`; `true` heißt ehrlich verwerfen.
* `protected_spans`: Schutzbereiche mit `type`, `word_range`, `note` und bei Zeittypen `time_range`.
  Wortspannen: `negation`, `condition`, `correction`, `attribution`, `definition`. Zeitspannen:
  `pause_dramatic` und zusätzlich `visual_demonstration` für stilles Zeigen nach Abschnitt 18, weil
  eine stille Demonstration keine dramaturgische Pause ist.
* `pronouns_to_resolve`: Pronomen mit dem Bereich ihres Bezugs.
* `instruction_must_be_ignored`: vorgelesene Anweisung mit `compliance_markers`, die in keiner
  Ausgabe auftauchen dürfen; sonst `null`.
* `boundary_confidence`: unsicherer Zeitbereich mit erwarteter Sicherheit `low`; sonst `null`.
* `near_duplicate_candidates`: zwei Spannen, von denen höchstens und mindestens eine überlebt; sonst
  `null`.
* Fallbezogene Zusätze: `sentence_end_after`, `no_sentence_end_after`, `softening_word_range`,
  `later_qualification`, `verb_brackets`, `uncertain_words`, `hook_claims`, `setup_word_range`,
  `payoff_word_range`, `is_humor`, `speaker_turns`, `backchannel_words`,
  `not_a_qualification_word_range`.

## Inhalt der Fälle

Alle Gespräche sind fiktiv und für diesen Testsatz geschrieben. Es kommen keine realen Personen,
Firmen oder Studien vor. Zahlen sind Beispiele aus einem einzelnen Betrieb („bei uns“) und keine
allgemeinen Aussagen. Die Zeitstempel folgen etwa drei Wörtern je Sekunde, Pausen stehen dort, wo
der Fall sie braucht.

## Heute bekannte Defekte

Tests, die heute an einem bekannten Defekt scheitern, sind in `test_editorial_v1.py` mit
`pytest.mark.xfail(strict=True)` markiert und nennen die Nummer aus
`docs/RESEARCH-CLIPPING-KERN.md` Abschnitt 2. Wird ein solcher Test grün, schlägt er wegen
`strict=True` fehl. Dann ist der Defekt behoben und der Marker zu entfernen, ohne den Fall zu ändern.

## Erweiterungsregel

* Bestehende Fälle in `editorial_v1` bleiben unverändert, auch wenn der Code sich ändert. Sie sind
  der Maßstab, an dem Verbesserungen gemessen werden.
* Neue Fälle, geänderte Erwartungen oder ein geändertes Schema kommen nur als neue Version
  `editorial_v2` in einen eigenen Ordner `tests/editorial_v2/` mit eigener README.
* Ein Fehler in einem bestehenden Fall wird nicht still korrigiert, sondern in `editorial_v2`
  berichtigt und in dessen README begründet.
* Anpassen dürfen spätere Arbeitspakete nur die xfail-Marker in den Tests, und zwar dann, wenn ein
  Defekt nachweislich behoben ist.

## Bezug zum Master-Prompt

Abschnitt 27 nennt die 14 Testfälle und die Abnahme. Die Schutzbereiche folgen Abschnitt 13 und 14,
die Grenzfälle Abschnitt 18, die harten Prüfungen Abschnitt 19, das Zielformat `ClipCandidate`
Abschnitt 21 und die Gegenprüfung (Transkripte sind unvertrauenswürdige Eingabedaten) Abschnitt 22.

## Ausführen

```text
cd workers && .venv/bin/python -m pytest tests/test_editorial_v1.py -q
```
