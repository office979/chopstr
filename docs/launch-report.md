# Launch-Bericht chopstr (Phase 6 des Launch-Auftrags)

Stand 20.10.2026. Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` (gültige Fassung nach Review). Entscheidungsnotizen:
`docs/decisions/000` bis `060`. Inventur und Gate 0: `docs/decisions/001-inventur.md`. Messwerte:
`workers/eval/results/`. Alle Zahlen stammen vom Heuristik-Provider (`local-heuristic`, unkalibriert) auf
einem Apple-Silicon-Mac (CPU, int8, keine Diarisierung) und von synthetischem Material; kein Wert ist ein
Qualitätsnachweis für echtes Langmaterial.

## 1. Entscheidung: Launch nein, Pilot mit Freigabepflicht ja

**Launch-ready im Sinn von Abschnitt 1 ist chopstr nicht.** Von acht Schwellen ist eine erreicht
(Laufzeit auf CPU), eine teilweise (Untertitel-WER Hochdeutsch), vier sind ohne Menschen oder fremdes
Material nicht messbar (Verwendbarkeit, Sinnfehler, Schnittqualität, Wettbewerbsvergleich), zwei ohne
Modelle oder Referenzen nicht messbar (Debatten-Sprecherzuordnung, Reproduzierbarkeit mit Sprachmodell).
Nach der Regel des Auftrags gilt: nicht messbar ist nicht bestanden.

Was belegt ist: Die Pipeline läuft von Upload bis Export durch, ein gefundener Transkript-Defekt mit
Sinnfehlerwirkung ist behoben, jede Clip-Regel aus Abschnitt 5 hat Tests mit Verletzung und Gegenbeispiel,
jeder Kandidat trägt Begründung, Belegstellen und eine Ergebnisklasse, und die Oberfläche ist eine Freigabe
ohne Timeline. Das genügt für einen Pilot mit PLACEMedia, in dem jeder Clip von einem Menschen freigegeben
wird, und für die Messungen, die der Launch braucht.

| Perspektive | Urteil |
|---|---|
| Produkt und Entwicklung | Technisch vorzeigbar: Export als Abnahmeobjekt, Freigabe statt Editor, Tests 3084 Worker und 758 Web grün. Nicht vorzeigbar als Nachweis: kein echtes Langvideo im Repo. |
| Redaktionelle Qualität | Kein Clip wurde von einem Redakteur beurteilt; 9 von 10 Kandidaten unter Fassung 2 sind „Bewertung unsicher“, das ist ehrlich, aber für einen Launch zu viel Prüfarbeit. |
| AI Engineering | Alle Verfahren der Phasen 1 bis 4 sind gebaut, hinter Schaltern, mit Startwerten ohne Messung. Die Hypothesen (Paarvergleich, Prosodie, Claim-Index, zweites Modell) brauchen die Baseline an echtem Material. |

## 2. Schwellen aus Abschnitt 1

| Kriterium | Schwelle | Ergebnis | Status | Was fehlt, was es kostet |
|---|---|---|---|---|
| Verwendbarkeit | 60 % der Kandidaten ohne Änderung postbar, 3 verschiedene je Quellstunde | nicht messbar: keine Redakteure, kein echtes Langmaterial. Ausbeute Fassung 2 auf 0,22 Quellstunden (`v2_ausbeute.json`): 46 angeboten je Quellstunde, 9,2 mit Ergebnisklasse `passed`, Verwerfungsquote im Pool 75 % (same_opening 28 %, duplicate_payoff 17 %, chapter_limit 15 %, overlap 10 %); 10 angeboten, 1 `passed`, 9 `uncertain`, 0 `blocked` | nicht messbar | 5 Langvideos mit Rechten, 3 Redakteure, je Video rund 2 Stunden Bewertung; Bögen liegen bereit (`workers/eval/bewertung.html`) |
| Sinnfehler | kein bestätigter kritischer Fehler in freigegebenen Clips; Bericht mit Stichprobe und Unsicherheit | nicht messbar: keine manuelle Prüfung. Automatisch: Testsatz editorial_v1 Fassung 2 14 von 14; Regeltests 44 bestanden, 5 xfail mit Grund; ein Dropout-Defekt behoben (P58) | nicht messbar | 20 Clips aus 3 Quellen manuell prüfen (`workers/eval/sinnfehler.py`); 0 von 20 ergäbe obere 95-%-Grenze 13,9 % |
| Schnittqualität | 90 % natürlich, Urteil je Clip | nicht messbar: keine Hörer. Automatische Grenzqualität aus `clip_eval` vorhanden; Prosodie gebaut, Regel aus | nicht messbar | Hörtest 50 Schnittpunkte, 3 Hörer, Padding gegen Prosodie (`cut.prosody.enabled`) |
| Untertitel | WER unter 4 % DE, unter 8 % AT; Versatz Median unter 60 ms, p95 unter 120 ms gegen Audioanker | WER synthetisch DE: 1,3 / 1,4 / 0,4 % (Fassung 2, nach P58; vorher 2,3 / 1,1 / 8,8 %); AT nicht messbar; Versatz nicht messbar (keine Anker); Hinweis aus Lane E: Wortanfänge liegen im Median 357 ms vor der Montage-Grenze | teilweise | AT-Material; 50 manuell gesetzte Audioanker (`workers/eval/alignment_eval.py`) |
| Debatten | 85 % der Wörter bei Überlappung richtig; cpWER und DER berichtet | nicht messbar: Diarisierung lokal nicht lauffähig (torch, pyannote, Token); Werkzeug `speaker_eval` fertig, Referenzformat vorhanden | nicht messbar | HF-Token und GPU-Umgebung oder Docker-Lauf; 20 Minuten Debatte mit Sprecherreferenz |
| Vergleich | 60 % der entschiedenen Paare gegen Wettbewerbstool | nicht messbar: kein Wettbewerbsmaterial, keine Bewerter; Modus `--extern` fertig | nicht messbar | Zugang zum Wettbewerbstool, dieselben 5 Quellen, 3 Bewerter |
| Reproduzierbarkeit | Top-5 Jaccard mindestens 0,8 und Rang 1 gleich in 4 von 5 frischen Läufen | mit Heuristik deterministisch (Tests, zwei Prozesse mit verschiedenen Hash-Seeds identisch); mit Sprachmodell nicht messbar | teilweise | Provider; 5 Läufe mit `CHOPSTR_ANALYZE_NO_CACHE=1`, Auswertung `repro_eval` |
| Laufzeit | unter 20 Minuten je Quellstunde bis zur Kandidatenliste; Bedienzeit unter 10 Minuten | Fassung 1: 23,1 min/h; Fassung 2 nach P58: 18,2 min/h (CPU, ASR 61 bis 96 s je Quelle, Analyse unter 1 s, Render 7 bis 14 s je Clip); Bedienzeit nicht gemessen | erreicht (CPU, 0,22 h Material) | Messung an 60-Minuten-Material und auf GPU; Gate 5 mit einem Redakteur |

## 3. Was in dieser Sitzung gebaut wurde (Phasen 0 bis 5)

| Phase | Ergebnis | Nachweis |
|---|---|---|
| 0 Inventur | Vier Inventur-Lanes, Baseline-Lauf an drei Quellen bis zum Export, `ingest_local.py`, Defekt ASR-Dropout gefunden | `001-inventur.md`, `workers/eval/results/2026-10-20-launch-laeufe/` |
| 1 Transkript und Sprecher | Hotwords nur noch Nachkorrektur (Defekt behoben, Messung in `010`), Routing nach erkannter Variante (`ASR_AUTO_ROUTE`), Austriazismen-Liste (83 Wörter mit Quelle), Datenvertrag `route` (verbatim, time_source), Überlappung je Wort, Mehrspur-Sprecher aus Spurenergie (`SPEAKERS_MULTITRACK`, Migration 0018), Verbklammer-Erweiterung (zu-Infinitiv, Korrelate, Partikel) unter Fassung 2 verdrahtet | `010` bis `012`, 50 Tests, davon 2 mit echter ASR |
| 2 Momentfindung | Trichter `funnel` (Pool, nach Gates, angeboten) mit Gründen, Ausbeute `yield`, Themenkapitel, Text-Heatmap v2 (normiert, acht Markerlisten), Paarvergleich mit Bradley-Terry und Positionsbias-Messung (Hypothese, Regel aus), Determinismus über Prozesse | `020` bis `022`, 44 Tests |
| 3 Kontexttreue | Claim-Index über das ganze Video (Eigenkorrektur, Ergänzung, Widerspruch durch Dritte), Gegenleser nach sechs Dimensionen mit optionalem zweitem Modell (`LLM_PROVIDER_SECOND`), Ergebnisklassen `review_state`, Titelkarte als geprüfte Reparatur, Regel 3 und 6 präzisiert, Regeltests für alle 16 Regeln | `030` bis `032`, `tests/test_launch_rules.py` |
| 4 Schnitt und Export | Prosodische Kanten (RMS-Minimum, Atem), Hook gegen Ton mit Vorgeplänkel-Verschiebung, Lesetempo und Du/Sie-Hinweis in Untertiteln, Split-Screen nur mit Sprecher-Bild-Bindung, Export als Abnahmeobjekt (`export.strict`), Titelkarte aus `repair_applied` im Render | `040` bis `043`, 59 Tests, Render-Tests mit libass-ffmpeg |
| 5 Oberfläche | Timeline entfernt, Karte mit Begründung, Belegstellen, Flags, Ergebnisklasse, Haltegrund, einer Qualitätszahl; Annehmen, Ablehnen, An Redaktion; Annehmen trotz Befund nur mit Begründung; Briefing beim Upload | `050` bis `052`, 758 Web-Tests, Sichtprüfung im Browser |
| Messsystem | Datenvertrag `workers/eval/data/` mit Split, Harness mit Abdeckung an drei Stellen, `speaker_eval` (Zuordnung je Wort, cpWER, DER), `alignment_eval`, `repro_eval`, `cost_eval`, `sinnfehler` (Clopper-Pearson), `baseline` mit Toleranzen, Blindvergleich mit Bewerter-ID, „beide unbrauchbar“, Mängelkategorien und Wettbewerbsmodus | `060`, `workers/eval/README.md` |

Alles Neue liegt unter Fassung 2 und hinter Schaltern; Fassung 1 ist byteidentisch (Snapshot-Test). Der
Standard bleibt Fassung 1, bis die Messungen aus Abschnitt 2 vorliegen (Decision 004 steht aus).

## 4. Vergleich Fassung 1 gegen Fassung 2 an den drei Baseline-Quellen

| Kennzahl | Fassung 1 (Baseline, vor P58) | Fassung 2 (nach P58) |
|---|---|---|
| WER gegen Skript (A / B / C) | 2,3 / 1,1 / 8,8 % | 1,3 / 1,4 / 0,4 % |
| Lücken über 2 s im Transkript | 2 / 2 / 5, darunter 12,8 s Ausfall in C | 2 / 2 / 2 (Pausen der Montage) |
| Vorschläge im Pool | 9 (3 je Quelle) | 40 (17 / 12 / 11) |
| angeboten | 8 | 10 (4 / 4 / 2) |
| Verwerfungsgründe | 1 too_long | chapter_limit 6, same_opening 11, duplicate_payoff 7, overlap 4, too_short 1, no_viable_moment 1 |
| automatisch angenommen und gerendert | 1 (7 mit Claim-Flag zurückgehalten) | 1 (9 `uncertain`, Gates im Berichtsmodus) |
| Laufzeit je Quellstunde (CPU) | 23,1 min | 18,2 min |

Beobachtung ohne Wertung: Fassung 2 findet mehr Momente und verwirft sie nachvollziehbar; die
Ergebnisklasse `uncertain` trifft fast alles, weil die Gates im Berichtsmodus jeden Hinweis melden. Das ist
die gewollte Vorsicht ohne Sprachmodell, aber für die Prüfarbeit zu grob; welche Hinweise bündelbar sind,
zeigt erst echtes Material (P59, Revisit-Trigger).

## 5. Status der 15 Schwachstellen nach den Phasen 1 bis 5

| Nr. | Schwachstelle | Status | Beleg |
|---|---|---|---|
| 1 | Referenzdaten | bewusst offen: Werkzeuge, Vertrag und Split fertig, Daten fehlen (keine Rechte, keine Redakteure) | `workers/eval/data/README.md`, `060` |
| 2 | Gewichte gesetzt | bewusst offen: ohne Redakteursurteile keine Kalibrierung; gelernte Gewichte bleiben ausgesetzt (P14, P25); die These zum Hook-Gewicht ist verworfen, weil unbelegt (Review 8) | `story_score.py`, `021` |
| 3 | Ein Aufruf je Kapitel, absolute Scores | teilweise behoben: Paarvergleich über das ganze Video mit Bradley-Terry gebaut (Regel aus, Budget muss erweitert werden); zweites Modell als Gegenleser (Env) | `022`, `031` |
| 4 | Kapitel 4 Minuten | behoben plus Test: Themenwechsel-Kapitel (Regel aus bis Gate 2), Überlappung 30 s | `020`, `test_launch_p2_chapters.py` |
| 5 | Heatmap audio-lastig | behoben plus Test: Text-Heatmap v2 normiert, Stakes und Überraschung; Lachen weiter nicht berechnet | `021`, `test_launch_p2_heat.py` |
| 6 | Story-Graph 60 s | behoben plus Test: Claim-Index ohne Grenze mit drei Klassen und Schnittreaktion (Regel aus) | `030`, `test_launch_p3_claim_index.py` |
| 7 | Exklusive Diarisierung | teilweise: nicht exklusive Ausgabe und Überlappung je Wort gebaut, Mehrspur-Energie als Quelle; an echter Aufnahme nicht gelaufen (pyannote fehlt) | `011`, `test_launch_p1_speakers.py` |
| 8 | Schnitt nur Text | behoben plus Test: Prosodie (RMS-Minimum, Atem) und Hook gegen Ton (Regeln aus bis Hörtest) | `040`, `042` |
| 9 | Füllwort-Kürzen | behoben im Code (geschützte Spannen), Regel `trim.enabled` bleibt aus bis Hörtest | P39 |
| 10 | Humor, Lachen | bewusst offen: Flag und Sperre bleiben; Lachen bleibt Hinweis ohne Daten (Widerspruch B nicht messbar) | `001` Abschnitt 5 |
| 11 | CH und AT | teilweise: Routing nach erkannter Variante, Austriazismen, Datenvertrag verbatim; CH-Modell fehlt, AT-Material fehlt | `010` |
| 12 | Verbklammer | behoben plus Test: zu-Infinitiv, Korrelate, Partikel ohne Satzzeichen, unter Fassung 2 im Tor verdrahtet | `012`, `test_launch_p1_bracket_wiring.py` |
| 13 | Eigenständigkeit | behoben plus Test: deterministische Hinweise getrennt von Modell und bestätigten Fehlern; Regel 3 mit zulässigen Einstiegen | `032`, `test_launch_rules.py` |
| 14 | Visuelle Analyse | bewusst offen (Auftrag Abschnitt 7); Split-Screen nur mit Bindung, ohne Detektor konservativ | `043` |
| 15 | Zwei Zahlen im UI | behoben: eine Qualitätszahl, keine Reichweite, Liste nach Ergebnisklasse und Qualität | `052` |

## 6. Gates

| Gate | Stand |
|---|---|
| 0 | bestanden als Inventur plus messbare Baselines (`001`) |
| 1 | nicht bestanden: WER DE erreicht (synthetisch), Sprecherzuordnung, cpWER, DER, Versatz nicht messbar |
| 2 | nicht bestanden: Abdeckung und Precision@5 ohne Referenzmomente nicht messbar; Reproduzierbarkeit nur mit Heuristik |
| 3 | teilweise: alle Regeln haben Tests mit Verletzung und Gegenbeispiel (5 xfail mit Grund: Stille beidseitig beim Füller, ß/ss in Untertiteln, Prüfung verbotener Filter ohne `export.strict`, Dokumentation je Route, Doppelfreigabe im Workflow); Sinnfehler-Rate nicht messbar |
| 4 | teilweise: Export-Abnahme und Untertitel-Stichprobe gebaut; Natürlichkeit nicht messbar; Laufzeit erreicht (CPU, kurzes Material) |
| 5 | gebaut, Bedienzeit nicht gemessen |
| 6 | Blindvergleich nicht messbar; diese Entscheidung |

## 7. Grenzen und Risiken

- Synthetisches Material (TTS, keine Überlappung, kein Dialekt) ist Entwicklungsmaterial; jede Zahl kann an
  echten Aufnahmen kippen. Das Abschlussmaterial in `split.json` ist leer und bleibt bis zur ersten Auswertung
  unangetastet.
- Alle Schwellen und Wortlisten der neuen Verfahren sind Startwerte (Herkunft H, Quelle je Schlüssel in der
  Policy). Kein Verfahren ist gegen die Baseline nachgewiesen; deshalb stehen alle Regeln auf aus.
- Der Paarvergleich sprengt mit `top_n` 8 das Modellbudget (56 Aufrufe je Quelle); vor dem Einschalten
  Budget oder `top_n` anpassen (`022`).
- Zwei Env-Schalter (`ASR_AUTO_ROUTE`, `SPEAKERS_MULTITRACK`) kosten Rechenzeit (rund 90 s je Quelle für
  das Routing) und sind nur mit Fakes geprüft.
- 7 Baseline-Kandidaten warten in der App auf eine Prüferentscheidung; die Freigabe hat die Sitzung nicht
  ausgeführt, weil sie die Entscheidung des Menschen ist.
- Auf GitHub lag während der Arbeit ein fremder Commit (`c54a10a`, Video-Agent); die Launch-Arbeit wurde
  darauf rebased, nicht darüber geschrieben.

## 8. Nächste Schritte in Reihenfolge

1. Fünf Langvideos von PLACEMedia mit Rechten nach `workers/eval/data/README.md` eintragen, Split festlegen.
2. Sprachmodell-Provider und HF-Token in einer Umgebung mit GPU oder Docker; einen Lauf je Fassung.
3. Drei Redakteure: Top-10 je Video, Clip- und Hook-Bogen (`bewertung.html`), Sinnfehler-Bogen für 20 Clips.
4. Drei Hörer: 50 Schnittpunkte, Padding gegen Prosodie.
5. `eval.baseline --vergleich` je Änderung; danach Regeln einzeln einschalten (Gates scharf, Kürzung,
   Prosodie, Themenkapitel, Claim-Index, Paarvergleich) und Decision 004 (Standard Fassung 2).
6. Wettbewerbsvergleich mit `blind_compare --extern`, wenn Material und Zugang vorliegen.

## 9. Präsentationsskript (10 Minuten, drei echte Videos)

Voraussetzung: drei Quellen mit Rechten sind vorher durch den Worker gelaufen (Fassung 2), die Karten sind
offen, ein Export liegt vor.

1. **Problem (2 Minuten).** Ein Redakteur findet in 60 Minuten Gespräch drei gute Clips, das kostet einen
   halben Tag. Maschinen scheitern an denselben Stellen: Einstieg zu spät, Relativierung weggeschnitten,
   Schnitt in der Verbklammer, Hook, der im Ton nicht hält. Beispiel aus der Baseline: ein verschlucktes
   „nur, wenn“ im Transkript macht aus einer Bedingung eine Behauptung, bevor ein Clip entsteht.
2. **Ansatz (3 Minuten).** Upload, drei Briefing-Felder, Kandidaten mit Begründung und Belegstellen, keine
   Timeline. Zeigen an Video 1: die Karte, „Warum dieser Clip?“, die Belegstelle anklicken, die
   Ergebnisklasse mit Grund und Quellstelle, die eine Qualitätszahl. Zeigen an Video 2 (Debatte): Widerspruch
   durch den Gegenüber als Flag mit Belegstelle, keine stille Entscheidung. Zeigen an Video 3: ein Kandidat
   „nicht freigabefähig“ und warum Annehmen eine Begründung verlangt.
3. **Beweis (3 Minuten).** Was gemessen ist: Transkript-Defekt gefunden und behoben (8,8 auf 0,4 % WER),
   Laufzeit 18 Minuten je Quellstunde auf CPU, jede der 16 Clip-Regeln mit Test und Gegenbeispiel,
   Fassung 1 unverändert als Rollback. Was nicht gemessen ist, offen sagen: kein Redakteursurteil, kein
   Hörtest, kein Wettbewerbsvergleich, Diarisierung nicht gelaufen. Die Bögen zeigen, mit denen das in zwei
   Wochen messbar wird.
4. **Grenzen und nächster Schritt (2 Minuten).** Pilot mit Freigabepflicht, fünf Videos, drei Redakteure,
   dann Launch-Entscheidung auf Zahlen. Keine Reichweitenprognose, keine Autoveröffentlichung.
