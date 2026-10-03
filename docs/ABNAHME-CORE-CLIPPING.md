# Abnahmebericht: Core Clipping Intelligence (Master-Prompt Abschnitt 30)

Stand 03.10.2026, Codebasis `main` nach den Wellen 1 bis 4 (Commits 651da29 bis zum Abschlusscommit dieser
Datei). Auftrag: `docs/MASTER-PROMPT-CORE-CLIPPING.md`. Grundlage: `docs/RESEARCH-CLIPPING-KERN.md`. Ist-Pipeline:
`docs/PIPELINE.md`. Entscheidungen: `docs/ENTSCHEIDUNGEN.md` P25 bis P56. Evidenz: unabhängiger
Verifikationslauf auf Commit 42bc092 plus Nachkorrekturen (Abschnitt 6).

Getrennt berichtet, wie Abschnitt 30 verlangt: Bestandsanalyse, eingegrenzte Änderungen, implementierte
Prüfungen, Vorher-nachher-Beispiele, ausgeführte Tests, bestandene Tests, verbleibende Probleme, ungeprüfte
Performance-Annahmen.

## 1. Bestandsanalyse (Phase 1)

Der Code-Audit (Research Abschnitt 2, am 03.10. gegen HEAD neu geprüft) fand 13 Befunde. Wurzelursache:
Syntax, Kontext und Pacing waren als nachträgliche Prüfungen gebaut, nicht als Bedingungen der Erzeugung;
mehrere deutsche Schutzregeln existierten, wirkten aber nicht im Datenfluss (Pausen als Satzgrenzen, ein
Verbklammer-Gate, das per Konstruktion nie anschlug, Gate-Verletzer in der Liste, nie angewendete Füllwort-
und Pausenschnitte, Heatmap ohne Wirkung, Hook vom Clip entkoppelt, Claim-Check per Teilstring). Dazu kam
eine Policy-Schicht, die mehr beschrieb, als der Code las, und die im Worker-Image fehlte.

Drei Problemarten nach Abschnitt 3: Auswahl (Befunde 3, 4, 11), Redaktion (5, 6, 7, 12), Ausführung
(1, 2, 8, 9, 10, 13). Die Zuordnung je Befund steht in `docs/PIPELINE.md` Abschnitt 7.

## 2. Eingegrenzte Änderungen

Alle Änderungen wirken nur unter `CHOPSTR_POLICY_VERSION=2` (Datei `packages/editorial/clip_policy_v2.yaml`)
und dort je Schalter unter `implementation.*`. Fassung 1 bleibt Standard und ist byte-gleich: Der
Golden-Snapshot (`workers/tests/test_policy_snapshot_v1.py`, 16 Szenarien) und 43.660 Satzende-Entscheidungen
ohne Abweichung belegen das. Kein Layout, keine Farbe, keine Schrift, keine Animation, kein Caption-Stil wurde
geändert (Scope-Prüfung des Verifizierers: unter `apps/web/components` und `packages/design` keine Änderung,
unter `apps/web/app` nur drei API-Routen).

| Paket | Änderung | Schalter heute |
|---|---|---|
| AP0 | Policy, Schriften, Ausgaberegeln im Worker-Image; Startprüfung; keine automatische Freigabe bei Humor, sensiblem Thema oder freigaberelevanter Behauptung (`release_gate`); „Video clippen“ an einem zurückgehaltenen Clip ist die menschliche Annahme (bedingtes Urteil) | immer (Produktregel) |
| AP2/AP3 | Satzende-Funktion v2 (Satzzeichen primär, Pause nur Grenzkandidat, Längenobergrenze, Rückfall ohne Satzzeichen), Anfang heilen, Ende nie auf Abschwächung, Verbklammer über die Grenze mit heuristischem Rückfall ohne spaCy, Web-Port und Paritätsdatei | an (`sentence_rule`) |
| AP4 | Zehn harte Gates mit Heilen vor Verwerfen, Story-Graph mit Wortgrenzen, `system_editor_v2`, Modus sperren nur mit Sprachmodell | Gates laufen im Berichtsmodus (Schalter an, Regel `gates.discard_hard` aus) |
| AP5 | Episodenübersicht, Payoff-first und Einstieg-first mit Abgleich, Kapitelüberlappung, Seeds im Prompt, Modellbudget, stilles Zeigen als Payoff-Art | an (`search.payoff_first`) |
| AP6a | Gesprochener Hook ist der wörtliche Einstieg; Text-Hook ist ganzer Originalsatz oder kein Overlay (Teilsatz nur Opt-in); Claim-Check v2 auf Zahlentoken, Geltungsbereich, Zahlwörter; Hyperbel-Liste; keine zurückgenommene oder fremde Aussage als Overlay | an (`hook.native_spoken`) |
| AP6b | Kritiker-Rolle mit deterministischer Belegprüfung, Einstiegsvergleich mit Alternativen, Nachrücken aus der Reserve | an (`roles.critic`) |
| AP7 | Kürzung: Schutzbereiche, Pausenklassen, Füllwort- und Rückmeldeschnitte, Reward-Ende, Mehrsegment-Komposition, Splice-Limit zwei, Debatten nie umordnen | Code an, Regel `trim.enabled` aus |
| AP8 | ClipCandidate-Schema (Abschnitt 21) als Adapter im DetectReport | an (nur v2) |
| AP9 | Höchstens zehn Kandidaten, inhaltliche Dubletten, Register aller Policy-Schlüssel, Teilwerte 0 bis 4 mit Beleg (`score_clip_v3`), Länge nur als Abzug | an (`output.max_candidates`) |
| AP10a | Caption-Ereignisse bis zum nächsten Wort, Brücke zwischen Karten, Zahl plus Einheit, Bindestrich- und Morphemtrennung, Komma-Bruch nur bei Überlauf; kein Stilwechsel | an (`captions.word_bridge`) |
| AP10b | Vor- und Nachlauf an Wortgrenzen, `boundary_confidence`, Übergangsprüfung, `render_v2` mit Timeline und Zeitbasis, gepaddete Segmente zurück in die Clip-Komposition | an (`cut.padding`) |
| AP11 | Blindvergleich v1 gegen v2 mit getrennten Bögen für Clip und Hook, Quellkontext, Stil-Leck-Test, Erfolgskriterium | Werkzeug |
| AP12 | `docs/PIPELINE.md`, Register P25 bis P54, Prompt-Tabelle, Schema-Verträge | Dokumentation |

Umfang: 147 geänderte Dateien seit d58d35e, davon 67 neue, 43 neue Testdateien; etwa 728 neue Python-Tests
und 62 neue TypeScript-Tests.

## 3. Implementierte Prüfungen

- Versionierter Testsatz `workers/tests/editorial_v1` mit den 14 Pflichtfällen aus Abschnitt 27 als Fixtures
  mit Wortzeitstempeln, Harness (`assert_clip_respects_case`, `assert_rejected`, `assert_protected_spans_kept`,
  `assert_boundary_confidence_honest`, `assert_instruction_ignored`, `assert_humor_flagged`); unter Fassung 1
  stehen 24 strikte xfail-Marker für die dokumentierten Defekte, unter Fassung 2 weist
  `test_editorial_v1_policy_v2.py` die Fälle grün nach.
- Paritätsdateien Python gegen TypeScript (`packages/editorial/parity/*.json`) für Satzende, Claim-Check und
  Caption-Karten; Fuzz-Tests mit 2.500 Fällen ohne Abweichung.
- Schema- und Zeitachsentests (`test_clip_candidate` 202, `test_transitions` 30, `test_render_plan` 23).
- Reale Renderprüfung (AP10b): zwei Quellen, je Fassung 1 und 2, ffprobe-Dauer gleich Plan, Caption-Ereignis
  für jedes Wort, Energie an den Schnittkanten: Fassung 1 1,03 und 0,77 des Wortmedians (Schnitt im Auslaut),
  Fassung 2 0,07 und 0,13 (Schnitt in der Stille). Nicht geprüft: Abhören durch einen Menschen,
  Lippensynchronität mit echtem Gesicht, variable Frameraten, Render mit Teaser oder vielen lokalen Schnitten.
- Blindvergleich `workers/eval/blind_compare.py` mit festem Seed, anonymisierten Paaren, Bewertungsraster
  0 bis 4, Verwerfungsquote je Grund, Dubletten getrennt, Modellaufrufe je Quellstunde, Vorzeichentest.
- Register `editorial.key_register`: 142 Policy-Schlüssel, 121 umgesetzt, 9 teilweise, 12 nicht umgesetzt mit
  Grund (unter anderem Lachen und Applaus in der Heatmap, `max_gedanken`, `question_as_variant`).

## 4. Vorher-nachher-Beispiele (dieselben Quellen, Heuristik-Provider, Fassung 1 gegen Fassung 2)

Alle Texte sind fiktive Fixtures aus `workers/tests/editorial_v1/cases`.

### Demo-Skript (133 Wörter, 86 s), das klarste Beispiel für den Fortschritt

Originalpassage (Auszug): „… und das gilt für jede Firma. Das heißt aber nicht, dass das für jede Branche
gilt. …“

- Fassung 1: Kandidat 0,00 bis 32,98 s, endet auf „Heute machen wir es genau andersrum.“ und isoliert damit
  die Verallgemeinerung; die spätere Relativierung ist nur als „story_graph_unconfirmed“ vermerkt.
- Fassung 2: Kandidat 0,00 bis 38,78 s schließt „Das heißt aber nicht, dass das für jede Branche gilt.“ ein.
  Hook gesprochen und im Bild: „Ehrlich gesagt war das der teuerste Fehler meiner Karriere.“ Zweiter Kandidat
  29,00 bis 74,38 s mit Text-Hook „Was würdest du heute anders machen?“. Verworfen: ein Einstieg ohne
  Einlösung, zwei Überdeckungen.
- Grund: Reward-Ende und Heilung nach hinten, Relativierung gilt als nötige Nuance (Abschnitt 12, 13).

### later_self_correction

Originalpassage: „Wir haben im Frühjahr komplett auf bezahlte Werbung verzichtet, und der Umsatz ist
trotzdem gestiegen. Werbung braucht man also eigentlich gar nicht. … Moment, das muss ich korrigieren. Das
heißt aber nicht, dass Werbung überflüssig ist. …“

- Fassung 1: Text-Hook „Kennst du das: Wir haben im Frühjahr komplett auf“ (erfundene Rahmung, mitten im Satz
  abgeschnitten).
- Fassung 2 vor der Korrektur: Text-Hook „Werbung braucht man also eigentlich gar nicht.“, also genau die
  zurückgenommene Aussage. Der Verifizierer hat das als Blocker gemeldet.
- Fassung 2 nach der Korrektur: kein Overlay (Herkunft `none_retracted`), gesprochener Hook bleibt der
  wörtliche Einstieg; generierte Varianten mit der zurückgenommenen Aussage werden mit Befund verworfen.
- Grund: Abschnitt 8 und 13, Testfall „Spätere Selbstkorrektur“.

### conditional_recommendation

Originalpassage: „Sollte ein kleiner Betrieb auf die Vier-Tage-Woche umstellen? Meine Antwort ist: Ja, aber
nur, wenn ihr vorher eure Abläufe … sauber dokumentiert habt. … Wobei ich dazusagen muss: In der Werkstatt
hätte das so nicht geklappt …“

- Fassung 1: Hook gesprochen „Du kennst das sicher: Sollte ein kleiner Betrieb auf die Vier-Tage-Woche
  umstellen“, im Bild „Kennst du das: Sollte ein kleiner Betrieb auf die“ (abgeschnitten). Die Heilung des
  Endes hängte unter Fassung 1 den „Wobei“-Satz an und endete darauf.
- Fassung 2: Hook gesprochen und im Bild „Sollte ein kleiner Betrieb auf die Vier-Tage-Woche umstellen?“;
  Bedingung („nur, wenn …“) ist Schutzbereich; ein Clip, der auf dem „Wobei“-Satz endet, wird mit
  `ends_on_qualification` verworfen; der Einstieg „nur, wenn“ ohne Einlösung wird mit `promise_unfulfilled`
  verworfen.

### misrecognized_number_or_name

Originalpassage: „… Das war Frau Meier, das schreibt man mit a i. … Bei uns hat das im ersten Jahr rund
40.000 Euro gespart. …“ (ASR-Sicherheit 0,38 für „Meier“, 0,46 für „40.000“)

- Fassung 1: Hook „Kennst du das: Wer hat bei euch den Einkauf“; die Unsicherheiten erscheinen nirgends.
- Fassung 2: Hook „Wer hat bei euch den Einkauf neu aufgestellt?“; Varianten mit der unsicheren Zahl werden
  verworfen; im ClipCandidate stehen „Name oder Begriff „Meier,“ unsicher erkannt (Sicherheit 0,38 unter 0,50),
  am Audio prüfen“ und „Zahl „40.000“ unsicher erkannt (Sicherheit 0,46 unter 0,50)“. Eine Audioprüfung selbst
  gibt es nicht; der Hinweis geht an die Redaktion.

### speaker_turn_attribution mit aktivierter Kürzungsregel (Policy-Kopie)

Originalpassage: „Hast du jemals überlegt, die Firma zu verkaufen? Nein, nie ernsthaft. Und wenn morgen jemand
mit einem wirklich guten Angebot kommt, würdest du dann verkaufen? Dann ja, sofort. Ich bin da ganz ehrlich,
Okay. ich hänge nicht an der Firma, ich hänge an den Leuten. Wenn die gut versorgt sind, unterschreibe ich am
selben Tag.“

- Ohne Kürzung: ein Segment 0,35 bis 20,87 s.
- Mit Kürzung: drei Segmente; entfernt werden eine technische Pause 4,735 bis 4,985 s und der Einwurf „Okay.“
  des Gastgebers 13,14 bis 13,86 s; die Antwort „Nein, nie ernsthaft.“ zwischen zwei Fragen bleibt, beide
  Bedingungen („wenn morgen …“, „Wenn die gut versorgt sind …“) sind Schutzbereiche, die Pausen nach den
  Fragen gelten als Reaktionspausen. Schnittkanten liegen durch Vor- und Nachlauf nie im Nachbarwort.

### silent_demonstration

- Fassung 1 und Fassung 2 vor der Korrektur: kein Kandidat, weil der Payoff nur im Bild liegt.
- Fassung 2 nach der Korrektur: Payoff-Art „demonstration“ (Demonstrations-Marker, Stille ab 1,5 s über die
  Wortzeiten oder ein Bildereignis, Auflösung im Satz nach der Stille); ein Kandidat 3,48 bis 25,52 s, der die
  Stille enthält, besteht den Harness.

### punchline_setup

- Fassung 1: Kandidat ohne Humor-Markierung, obwohl Setup und Pointe erkannt sind.
- Fassung 2 nach der Korrektur: Kandidat trägt `humor` in den Risikoflags (Pointe mit Setup oder Lachen des
  Gegenübers), wird also nicht automatisch angenommen und geht an die menschliche Prüfung (P27).

## 5. Ausgeführte und bestandene Tests

Letzter vollständiger Lauf auf dem Abschlussstand (Zahlen wörtlich):

| Suite | Befehl | Ergebnis |
|---|---|---|
| Worker | `cd workers && .venv/bin/python -m pytest -q --ignore=tests/test_render_media.py -m "not network"` | 2655 passed, 3 skipped, 11 deselected, 24 xfailed |
| Worker Medien (ffmpeg mit libass) | `pytest -q tests/test_render_media.py` | 8 passed |
| Snapshot v1 | `pytest -q tests/test_policy_snapshot_v1.py` | 5 passed |
| Lint | `ruff check chopstr_worker tests eval` | All checks passed |
| Web | `cd apps/web && npx vitest run` | 749 passed in 31 Dateien |
| Web Typen | `npx tsc --noEmit` | 0 Fehler außerhalb der generierten `.next`-Dateien (dort 2 veraltete Verweise) |
| MCP-Server | `npm test` | 53 passed |

Ausgelassen mit Grund: 11 Netzwerk-Tests (Marker `network`), 1 Test ohne PIL, 2 Tests ohne spaCy.
Kein `skip` ohne Begründung, kein `.only`, kein Platzhalter, kein TODO im neuen Code. 24 strikte xfail-Marker
in `test_editorial_v1.py` dokumentieren die Defekte der Fassung 1.

Die 14 Pflichtfälle über `story_engine.run` mit Heuristik-Provider, Stand nach den Nachkorrekturen:

| Testfall | Fassung 1 | Fassung 2 |
|---|---|---|
| Negation am Satzende | erfüllt | erfüllt |
| Bedingte Empfehlung | erfüllt | erfüllt, Verwerfen des Einstiegs ohne Einlösung sichtbar |
| Spätere Selbstkorrektur | erfüllt (Clip enthält Korrektur), Hook abgeschnitten | erfüllt, kein Overlay statt der zurückgenommenen Aussage |
| Fremde Position im Zitat | erfüllt | erfüllt, Zitat nie als Overlay |
| Ungeklärtes Pronomen | teilweise (Gate v1 fehlt) | erfüllt (Gate v2 und Heilung nach vorn) |
| Zahl oder Name falsch transkribiert | nicht erfüllt (keine Markierung) | erfüllt (Markierung, keine unsichere Zahl im Hook) |
| Demonstration ohne Sprache | nicht erfüllt (kein Kandidat) | erfüllt nach Nachkorrektur |
| Emotionale Pause | erfüllt (keine Kürzung aktiv) | erfüllt, Pausenklasse dramatic |
| Pointen-Setup | nicht erfüllt (kein Humor-Flag) | erfüllt nach Nachkorrektur |
| Sprecherwechsel | erfüllt | erfüllt, auch mit Kürzung |
| Sehr schwaches Material | nicht erfüllt (Kandidat angeboten) | erfüllt (`no_viable_moment` mit Grund) |
| Fast identische Kandidaten | erfüllt (zeitliche Überdeckung) | erfüllt, Dublette gemeldet |
| Ungenaue Zeitstempel | nicht aussagekräftig | erfüllt (`boundary_confidence`, konservative Kante) |
| Anweisung im Transkript | erfüllt | erfüllt |

Einschränkung des Verifizierers: Die Fixtures sind kurz (19 bis 29 s), deshalb bietet die Engine fast immer die
ganze Fixture an; die Schnittkantenlogik ist über die Modultests belegt, nicht über diese Läufe. Längere Fälle
mit Material vor und nach der Stelle gehören in `editorial_v2`.

Blindvergleich auf den 15 Fixture-Quellen (Heuristik, k = 5):

| Kennzahl | Fassung 1 | Fassung 2 |
|---|---|---|
| editorial_v1 bestanden | 11 von 14 | 14 von 14 (12 von 14 vor den Nachkorrekturen) |
| Verwerfungsquote ohne Dubletten | 0 Prozent | 28,6 Prozent (Überdeckung, Versprechen nicht eingelöst, zu kurz) |
| Dubletten getrennt | 0 | 10 (gleicher Payoff 2, gleiche Spanne 8) |
| Modellaufrufe je Quellstunde | 520 | 654 (plus 26 Prozent, Heuristik hochgerechnet auf kurze Fixtures) |
| Kürzungsvariante bestanden (Regel an, Suche aus) | | 12 von 14; Kombination aller Schalter mit Kürzungsregel 14 von 14 |
| Urteil | | nicht bewertet, weil 0 von 14 Paaren von Menschen bewertet |

## 6. Verbleibende Probleme

Behoben nach dem Verifikationslauf (Nachkorrekturen auf dem Abschlussstand): Text-Hook isoliert keine
zurückgenommene oder fremde Aussage mehr; stilles Zeigen hat eine Payoff-Art; Pointe setzt das Humor-Flag;
schwaches Material wird mit Grund verworfen; der Sperrmodus verwirft nur mit Regel, Schalter und Sprachmodell;
die Web-Revision räumt spannenbezogene Rubrik-Schlüssel ab; Kontext nach dem Clip fließt in die Hook-Sperre.

Offen, in Reihenfolge der Dringlichkeit:

1. Es gibt keine menschliche Bewertung. Der Blindvergleich ist als Werkzeug fertig, das Urteil lautet „nicht
   bewertet“. Vor dem Umschalten des Standards auf Fassung 2 braucht es echtes Material, einen echten
   Sprachmodell-Provider und Bewerter ohne Anbieterkennung (Abschnitt 26). Der Hook-Bogen bleibt erkennbar,
   solange Fassung 1 jeden Hook mit „Du kennst das sicher:“ beginnt; der Clip-Bogen ist davon nicht betroffen.
2. Gates und Kürzung sind absichtlich nicht scharf: Gates im Berichtsmodus, Kürzungsregel aus. Beide Reviews
   haben die Aktivierung von einem Blindvergleich an echtem Material abhängig gemacht; Fehlalarmquoten der
   Gates (0 von 87) stammen von regelnahen Proben.
3. Die Heuristik bleibt unkalibriert: Rubrikwerte, Teilwerte, Kritiker und Hook-Qualität sind ohne
   Sprachmodell nicht aussagekräftig; der Report sagt das (`heuristic_only`, `calibration: uncalibrated`).
4. Kein spaCy im lokalen venv (Verbklammer nur heuristisch), kein Docker-Lauf, kein OpenCV (Reframing bleibt
   Mittelcrop, außerhalb dieses Auftrags).
5. Lachen und Applaus werden nicht berechnet (`laughter_values` leer); Payoff-Art Lachen und Reaktionspause
   nach Lachen sind damit tot.
6. Das Web kennt keine Policy-Fassung: manuelle Hooks prüft es weiter mit dem Claim-Check v1, die
   Caption-Vorschau wendet Zahl plus Einheit und Bindestrichregel unabhängig von der Fassung an.
7. Nach dem Render stehen gepaddete Segmente in der Clip-Komposition; ein Rollback von `cut.padding` wirkt
   für schon gerenderte Clips nicht rückwärts.
8. Bestandsdaten: Unter Fassung 2 ändert sich der Cache-Schlüssel, jede Quelle rechnet einmal neu.

## 7. Ungeprüfte Performance-Annahmen

- 94 der 142 Policy-Regeln tragen Herkunft H (Hypothese), darunter das Längenfenster 18 bis 70 s mit Ziel
  41 s, die Schwellen 7 und 10, das Audiogewicht 0,15, Vor- und Nachlauf 0,06 und 0,18 s, Pausenziel 0,25 s,
  lange Stille 1,5 s, Teaser höchstens 6 s, Redundanzschwelle 0,6, alle Markerlisten.
- Keine Regel in diesem Auftrag ist eine gelernte Entscheidung (G). Es gibt keine Ergebnisdaten; der
  Qualitätsscore ist keine Viralitätsprognose und wird nicht so ausgegeben (Abschnitt 4.8).
- Modellbudget 400 Aufrufe je Quellstunde ist gesetzt, nicht gemessen; mit Heuristik wird nur gezählt.
- Alle Fixture-Zahlen stammen aus 15 kurzen, fiktiven Quellen. Wie oft die Gates, die Kürzung und der
  Einstiegsvergleich an echten Gesprächen anschlagen, ist unbekannt.

## 8. Nächste Schritte

1. Zehn bis zwanzig echte Quellen (eigenes Material mit Freigabe) mit echtem Sprachmodell-Provider durch
   `workers/eval/blind_compare.py` laufen lassen, Bögen von zwei Redakteuren ausfüllen lassen, Bericht auswerten.
2. Erst danach entscheiden: Regel `gates.discard_hard`, Regel `trim.enabled`, Standard
   `CHOPSTR_POLICY_VERSION=2`.
3. `editorial_v2`: längere Fälle mit Material vor und nach der Stelle, damit Schnittkanten über
   `story_engine.run` prüfbar werden.
4. Lachen und Applaus in der Heatmap berechnen oder die Payoff-Art entfernen.
5. Policy-Fassung ins Web geben, damit Claim-Check v2 und Caption-Regeln auch in der Vorschau gelten.

## 9. Blindvergleich mit Testmaterial (Lauf B, 03.10.2026)

Nachtrag zu Abschnitt 8 Punkt 1. Lauf `workers/eval/blind_compare.py --k 5` auf 20 Quellen: Demo, die 14
`editorial_v1`-Fixtures, zwei echte Quellen aus der lokalen Datenbank (ein Interview zu Preisen, 22 s
Whisper-Transkript; eine Werbeanzeige, 44 s) und drei synthetische Gespräche von 4 bis 5 Minuten
(Interview Handwerk, Monolog Gründerin, Debatte Viertagewoche), die als Sprachaufnahme erzeugt und durch die
echte ASR des Workers transkribiert wurden. Provider: `local-heuristic`, kein Sprachmodell. Ablage:
`workers/eval/runs/2026-10-03-b-testmaterial/` (nicht versioniert, `workers/eval/runs/` steht in
`.gitignore`); Skripte und Erwartungen unter `workers/eval/runs/testmaterial/`.

### 9.1 Zwei Defekte am echten Material, in diesem Lauf behoben

Ein erster Lauf (A) mit denselben Quellen lieferte unter Fassung 2 für beide echten Quellen keinen
einzigen Kandidaten, Fassung 1 je einen. Ursachen und Korrekturen:

1. **Kommagetrennte ASR ohne Pausen.** Das echte Whisper-Transkript enthält über 22 s kein einziges
   Satzende-Zeichen, nur Kommas, und keine Wortlücke über 0,25 s. Die Satzregel v2 fand damit kein
   Satzende und die Suche kein Fenster. Neu: Satzende-Art `v2_comma_heavy` (Satzregel v2, erkennbar im
   Report), die bei kommalastigen Transkripten ein Komma nach mindestens sechs Wörtern als Satzgrenze
   zulässt, plus eine pausenfreie Längenobergrenze. Web (`sentences.ts`) und Parität
   (`packages/editorial/parity/sentence_end_v1.json`) sind mitgezogen; Fassung 1 bleibt byteidentisch
   (Snapshot bestanden). Eine Fehlmeldung der Verbklammer bei Hilfsverb am Satzende ist dabei mit korrigiert.
2. **Payoff-Marker fanden gesprochene Sprache nicht.** Die Marker standen nur am Satzanfang und ohne
   Normalisierung von ß und ss; die Werbeanzeige löst ohne Frage davor auf („die Lösung heißt“) und endet
   mit Handlungsaufforderung. Neu: Marker auch an Teilsatzgrenzen, ß/ss-Normalisierung, Markergruppen
   `search.payoff_markers.resolution` und `search.cta_markers` (beide Herkunft H, Quelle in der Policy),
   und ein ehrlicher Suchbefund `diagnosis`, den `no_viable_moment` als Grund durchreicht statt „nur
   Organisatorisches“ zu raten. Fixtures `real_preise.json` und `real_werbeanzeige.json` halten beide
   Transkripte als Regressionstests fest.

Dazu ein Fehler im Vergleichswerkzeug: Für Datenbankquellen wurden die unter Fassung 1 gespeicherten
Satzindizes mitgeladen, so dass Fassung 2 mit fremden Satzgrenzen rechnete. Das Werkzeug streicht
`sentence_idx` jetzt vor der Übergabe, jede Fassung segmentiert selbst.

Testlauf auf diesem Stand: Worker `pytest -q` 2746 passed, 3 skipped, 24 xfailed; `ruff check` ohne
Befund; Web `vitest run` 807 passed in 31 Dateien. Snapshot v1 und Paritätstests sind enthalten.

### 9.2 Ergebnis Lauf B (Zahlen wörtlich aus `bericht.md`)

| Kennzahl | v1 | v2 |
|---|---|---|
| Clip-Paare bei gleicher Ausgabemenge | 24 | 24 |
| nicht gepaart (Überhang) | 2 | 3 |
| angebotene Kandidaten | 26 | 27 |
| Verwerfungsquote (Stufe 2) | 0 von 26 (0,0 %) | 19 von 46 (41,3 %) |
| Dubletten (nicht in der Quote) | 0 | 34 |
| Modellaufrufe je Quellstunde | 304,2 | 399,9 |
| Laufzeit je Quellstunde (s) | 0,4 | 9,3 |
| editorial_v1 Bestehensquote | 11 von 14 | 14 von 14 |
| Hooks ohne Overlay-Text | 0,0 % | 29,2 % |

Verwerfungsgründe v2: Überdeckung 6, Kapitelgrenze 5, zu kurz 4, Versprechen nicht eingelöst 2,
kein tragfähiger Moment 2. Variantenlauf: Auswahl (Gates scharf, Payoff zuerst) bringt 14 von 14, Basis und
Kürzung 12 von 14; Hooks nativ bei 7 von 26 Kandidaten, davon 1 mit Claim-Befund.

Beobachtungen an den echten und synthetischen Quellen, ohne Bewertung: Fassung 2 wählt kürzere Spannen
(Mittel 30,3 s gegen 33,6 s) und setzt beim Preis-Interview einen Teaser („alle sagen, du brauchst mehr
Reichweite“) vor den Körper; Fassung 1 beginnt dort und bei der Debatte mit organisatorischem Vorlauf
(„Die nächste Folge erscheint wegen der Feiertage erst in drei Wochen.“), was Fassung 2 wegschneidet.
Fassung 2 bietet bei der Gründerin den Veranstaltungsvorspann („Willkommen zurück zum zweiten Teil des
Abends“) als Kandidaten an; das ist ein offener Punkt für die Einstiegsbewertung mit Sprachmodell.

**Urteil weiterhin: nicht bewertet.** Es gibt keine menschlichen Bewertungen (0 von 24 Paaren), und die
Stil-Leck-Prüfung warnt: Im Hook-Bogen beginnt jeder v1-Hook mit „Du kennst das“ und jeder v1-Overlay-Text
mit „Kennst du das“, Fassung 2 nie. Der Clip-Bogen zeigt keine Hooks und bleibt verblindet.

### 9.3 Bewerten und auswerten

1. `workers/eval/bewertung.html` im Browser öffnen, die Dateien `bewertung.json`, `hooks_bewertung.json`,
   `quellen.json` und `raster.json` aus dem Laufordner laden, Clip-Bogen und Hook-Bogen ausfüllen, exportieren
   (die Seite schreibt dieselben Dateinamen zurück in den Laufordner).
2. `cd workers && .venv/bin/python -m eval.blind_compare --auswerten eval/runs/2026-10-03-b-testmaterial`
   erzeugt `bericht.md` mit Urteil, Streuung und Vorzeichentest.
3. Für eine belastbare Aussage: echter Sprachmodell-Provider (`LLM_PROVIDER`), zehn bis zwanzig echte
   Quellen, zwei Bewertende; erst dann über `gates.discard_hard`, `trim.enabled` und
   `CHOPSTR_POLICY_VERSION=2` entscheiden (Abschnitt 8 Punkt 2).
