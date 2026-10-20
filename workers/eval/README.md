# Eval: ASR-Qualität und Clip-Auswahl, getrennt nach Dialekt

Werkzeuge, alle ohne GPU lauffähig:

| Skript | Frage | Aufruf |
|---|---|---|
| `wer_eval.py` | Wie gut hört der Worker Deutsch (DE/AT/CH)? | `python -m eval.wer_eval gold/ hyp/ --lexicon names.txt --json wer.json` |
| `eval_harness.py` | Wie nah kommen die Kandidaten an die Redaktion? | `python -m eval.eval_harness gold_clips/ preds/ --k 10 --json clips.json` |
| `referenzsatz.py` | Mit welchen Dateien wurde gemessen, und sind es noch dieselben? | `python -m eval.referenzsatz pruefen --positiv "…" --negativ "…"` |
| `clip_eval.py` | Wie sauber schneiden die Vorschläge einer Quelle, unter welcher Richtlinie? | `python -m eval.clip_eval --titel "…" --policy-version 2 --json messung.json` |
| `blind_compare.py` | Ist Fassung 2 bei gleicher Ausgabemenge redaktionell besser als Fassung 1? Schlägt chopstr ein Wettbewerbstool? | `python -m eval.blind_compare --out blind/` und `--auswerten blind/ [--bewerter a.json b.json]`; Wettbewerb `--extern clips/ --vergleichsart voller_output` |
| `data_loader.py` | Ist der Referenzdatensatz in `eval/data` gültig? | `python -m eval.data_loader eval/data` |
| `eval_harness.py --daten` | Findet die Pipeline die Referenzmomente, und wo verliert sie sie (Pool, Gates, Ranking)? | `python -m eval.eval_harness --daten eval/data --berichte berichte/ --teil entwicklung --json h.json` |
| `speaker_eval.py` | Stimmt der Sprecher je Wort, auch in Überlappung? cpWER, DER? | `python -m eval.speaker_eval --referenz ref.json --hypothese transkript.json --json s.json` |
| `alignment_eval.py` | Wie weit liegen Wortanfang und Wortende neben dem Audio? | `python -m eval.alignment_eval --anker anker.json --transkript transkript.json --json a.json` |
| `repro_eval.py` | Kommt bei gleichem Video dieselbe Top-5? | `python -m eval.repro_eval lauf1.json lauf2.json ... [--art gespeichert] --json r.json` |
| `cost_eval.py` | Was kostet eine Quellstunde, wie lange dauert sie? | `python -m eval.cost_eval --export kosten.json --json k.json` oder `--database-url ... --quelle <uuid>` |
| `sinnfehler.py` | Wie viele Clips haben einen bestätigten kritischen Sinnfehler, mit welcher Unsicherheit? | `python -m eval.sinnfehler --bogen-aus clips.json --out bogen.json`, dann `--auswerten bogen.json --json f.json` |
| `baseline.py` | Ist eine Änderung schlechter als die Baseline, über der Toleranz? | `python -m eval.baseline --vergleich h.json s.json ... --aenderung kurzname` |

Alle laufen aus `workers/` mit dem Interpreter der venv (`.venv/bin/python -m eval.wer_eval ...`).

**Regel für alle Werkzeuge:** Ein fehlender Messwert ist nie 0 und nie bestanden. Im JSON steht `None` mit
`ursache`, im Bericht „nicht messbar: <Ursache>“. Jedes Werkzeug schreibt mit `--json` einen Block
`"metriken": {name: {"wert", "stichprobe", "ursache"}}`, den `baseline.py` liest.

## Messsystem für den Launch (Auftrag Abschnitt 6)

### Referenzdatensatz und Split

Datenvertrag, Beispiele und Validierung stehen in `eval/data/README.md`. `eval/data/split.json` teilt jede
vollständige Quelle in `entwicklung`, `kalibrierung` oder `abschluss`; Ausschnitte derselben Aufnahme müssen im
selben Teil liegen. Der Abschlussteil wird nur mit `--abschluss-bestaetigt` ausgewertet. Heute ist alles
vorhandene Material `entwicklung` und `abschluss` leer.

### Momentfindung (`eval_harness.py --daten`)

Eingaben: `eval/data` (Spannen, Redakteurs-Top-10, Schnittpunkte) und je Quelle ein DetectReport-JSON
`berichte/<quelle>.json`. Abdeckung der Referenzmomente (IoU >= 0,5) an drei Stellen aus
`report["funnel"]` (`pool`, `after_gates`, `offered`). Fehlt `funnel`, kommt der Pool aus
`search.chapters[*].proposals` (nur mit Zeiten), angeboten aus `candidates`, und „nach Gates“ ist nicht
messbar. Recall@20 gegen alle Referenzmomente und gegen Gold getrennt; Precision@5 und @10 je Redakteur und
gemittelt (Treffer durch Zahl der angebotenen, weniger als k sind zulässig); Grenzfehler Start und Ende
getrennt, der Gesamtwert gewichtet den Start doppelt; angebotene Momente ohne jede Referenz zählen als „neu
entdeckt“ (Prüfauftrag, kein Fehler). Über Quellen werden Treffer und Nenner addiert. Dazu
Schnitt-Natürlichkeit aus `schnittpunkte/` (`cut_quality`): ein abgehackter Punkt macht den Clip unbrauchbar.
Tests: `tests/test_launch_eval_harness.py`, `tests/test_launch_eval_data_loader.py`.

### Sprecher (`speaker_eval.py`)

Referenz: `transkript_referenz/<quelle>.json` (Wörter mit Sprecher und Zeit), RTTM (nur DER) oder
`sprecherwechsel.json` des Testmaterials (Turns und Sätze, Wortzeiten interpoliert). Hypothese:
Transkript-JSON mit `speaker` je Wort oder RTTM. Je Referenzwort genau eines von korrekt, falsch, nicht
zugeordnet (Hypothese ohne Sprecher), nicht erkannt; gesamt und in Überlappung. cpWER mit bester
Sprecherzuordnung (exakt bis zwölf Sprecher). DER ohne Collar mit Überlappung, verpasst, Fehlalarm und
Verwechslung getrennt. Ohne jiwer und ohne pyannote.metrics. Tests: `tests/test_launch_eval_speaker.py`.

### Wortzeiten (`alignment_eval.py`)

Versatz in ms gegen `audioanker/<quelle>.json`: Median und 95. Perzentil (nächster Rang) für Wortanfang und
Wortende, Median mit Vorzeichen, fehlende Alignments getrennt (nicht gefunden, ohne Zeit), alles auch je
Kategorie. Mit `sprecherwechsel.json` als `--anker` entstehen synthetische Anker aus den Satzgrenzen der
Montage; das ist ein Regressionssignal, kein Launch-Messwert. Tests: `tests/test_launch_eval_alignment.py`.

### Reproduzierbarkeit (`repro_eval.py`)

n DetectReports desselben Videos und Briefings. Top-5 aus `funnel.offered` (sonst `candidates` nach `total`),
Spannen auf 0,1 s gerundet (`--iou` erlaubt unscharfen Abgleich). Jeder Lauf gegen Lauf 1: Jaccard, Rang 1
gleich, bestanden bei Jaccard >= 0,8 und gleichem Rang 1; dazu Jaccard paarweise gemittelt. Frische Läufe
brauchen `CHOPSTR_ANALYZE_NO_CACHE=1` beim Worker; gespeicherte Wiederholungen mit `--art gespeichert` (müssen
identisch sein). Tests: `tests/test_launch_eval_repro.py`.

### Kosten und Laufzeit (`cost_eval.py`)

`job_costs` als JSON-Export (`{"job_costs": [...], "sources": [...], "laufzeiten": [...]}`) oder aus Postgres
nur über `--database-url`. EUR, Rechenzeit (CPU plus GPU) und Wartezeit je Quellstunde, je Quelle und gesamt,
je Job-Typ. Die EUR stammen aus der Preistabelle in `costlog.py` (Standardwerte sind Platzhalter). Tests:
`tests/test_launch_eval_cost.py`.

### Sinnfehler (`sinnfehler.py`)

Bogen je Clip mit `geprueft` und kritischen Sinnfehlern (`attribution`, `negation`, `certainty`, `condition`,
`number`, `time`, `context`; `bestaetigt` true oder false). Auswertung: Clips mit bestätigtem Fehler,
Stichprobe, beobachteter Anteil, einseitige obere 95-%-Grenze nach Clopper-Pearson (0 von 20 ergibt 13,9 %,
1 von 20 ergibt 21,6 %), Verteilung je Quelle und Kategorie, gesperrte Clips, Warnung unter 20 Clips oder
drei Quellen. Tests: `tests/test_launch_eval_sinnfehler.py`.

### Baseline und Vergleich (`baseline.py`)

`eval/results/baseline.json` hält je Metrik Wert oder `None` mit Ursache, Einheit, Richtung, Toleranz,
Stichprobe sowie Provider, Policy und Hardware. Die Messungen, aus denen sie entstand, liegen daneben in
`eval/results/2026-10-20-baseline-messungen/`. Neue Läufe:

```bash
.venv/bin/python -m eval.baseline --vergleich h.json s.json a.json --aenderung satzregel-at
```

schreibt `eval/results/<datum>-satzregel-at.md` (Metrik, Baseline, neu, Differenz, Toleranz, Urteil ok,
verschlechtert oder nicht messbar) und endet mit Exit-Code 1, wenn eine Metrik über die Toleranz schlechter ist.
Metriken, Einheiten, Richtungen und Toleranzen stehen in `METRICS`; eine Messung mit unbekannter Metrik bricht
ab. Die Baseline vom 20.10.2026 misst nur drei Werte (WER und Wortzeiten des synthetischen Testmaterials):
`.venv/bin/python -m eval.baseline --messen-testmaterial eval/runs/testmaterial --out m.json`.
`eval/results/` ist versioniert. Tests: `tests/test_launch_eval_baseline.py`.

Ausbeute: `.venv/bin/python -m eval.baseline --messen-ausbeute berichte/*.json --out ausbeute.json` liest je
DetectReport `yield` (`offered`, `distinct`, `source_hours`) und rechnet angebotene, verwendbare und verschiedene
Clips je Quellstunde über alle Quellen. Verwendbar heißt `rubric.review_state == "passed"`; fehlt
`review_state` an einem Kandidaten, ist der Wert nicht messbar. Verwerfungsquoten je Grund kommen aus
`funnel_counts.pool_reasons` geteilt durch `funnel_counts.pool`, sonst aus `discarded` (ohne Laufereignisse)
geteilt durch Verwerfungen plus angebotene; sie heißen `verwerfungsquote_<grund>`, dazu
`verwerfungsquote_gesamt`, und sind reine Information ohne Toleranz.

### Was ohne Menschen oder echtes Material nicht messbar ist

| Metrik | Was fehlt |
|---|---|
| Abdeckung, Recall@20, Grenzfehler | menschlich gewählte Spannen (`spannen/`) zu echten Langvideos; dazu DetectReports mit `funnel` |
| Precision@5 und @10 | drei Redakteure, die unabhängig ihre Top-10 markieren (`redakteure/`) |
| WER DE, AT, CH | manuell korrigiertes Transkript eigenen Materials je Sprachvariante (`transkript_referenz/`) |
| Sprecher je Wort in Überlappung, cpWER, DER | 20 Minuten Debatte mit manueller Sprecherreferenz; das Testmaterial ist synthetisch montiert und ohne Überlappung |
| Highlight-Versatz | manuell am Audio kontrollierte Anker (`audioanker/`); Whisper ist keine Referenz |
| Schnitt-Natürlichkeit, Urteil je Clip | 50 Schnittpunkte mit drei Hörern (`schnittpunkte/`) |
| Sinnfehler | Prüfung von mindestens 20 Clips aus mindestens drei Quellen gegen den Vollkontext |
| Blindvergleich und Wettbewerb | drei Bewerter; Wettbewerbs-Clips mit geklärten Rechten, gleiches Briefing und Ausgabebudget |
| Verwendbarkeit (würde posten) | Redaktionsurteil über den fertigen Export |
| Reproduzierbarkeit, Kosten, Laufzeit | kein Mensch, aber echte Läufe: fünf frische Läufe je Video, ein `job_costs`-Export, Wanduhrzeiten |

Bis diese Daten vorliegen, steht jede dieser Metriken in der Baseline als nicht messbar mit Ursache. Eine
Launch-Freigabe ist dann ausgeschlossen (Auftrag Abschnitt 1).

## Gold-Format ASR (`wer_eval`)

Ein Eintrag pro Aufnahme im Gold-Ordner:

```json
{
  "dialect": "AT",
  "text": "Wir haben damals 40.000 Euro verloren, weil wir z. B. keine Rücklagen hatten.",
  "names": ["chopstr", "Placemedia"]
}
```

Alternativ eine `.txt` mit dem Referenztext; der Dialekt kommt dann aus dem Dateinamen
(`ep01_AT.txt`). `names` sind Eigennamen der Aufnahme, zusätzlich zur globalen `--lexicon`-Datei
(eine Zeile pro Name; typischerweise das `brand_vocab` des Markenprofils).

Hypothese im Hyp-Ordner mit gleichem Stamm (`ep01.json`): entweder direkt `transcript_versions.words`
(`{"words": [{"text": "..."}]}`) oder `{"text": "..."}`.

Normalisierung: Kleinschreibung, Satzzeichen weg, Whitespace zusammengefasst, Zahlen bleiben
Token („40.000" bleibt „40.000"). Bei Dialekt CH (oder `--ch`) werden ß und ss gleichgesetzt.

Ausgabe: Tabelle pro Dialekt (WER, Eigennamen-Fehlerrate) und optional JSON mit Werten pro Datei.

## Gold-Format Clips (`eval_harness`)

```json
{"episode": "ep01.mp4", "dialect": "AT",
 "clips": [{"start": 812.4, "end": 861.0, "rating": 3}]}
```

`rating`: 3 = sofort posten, 2 = mit Nacharbeit, 1 = Notlösung (zählt nicht als Treffer).
Vorhersage: `{"episode": "ep01.mp4", "clips": [{"start": ..., "end": ..., "total": ...}]}`.
Treffer = IoU >= 0,5. Boundary-Error misst, wie weit Anfang/Ende vom Redaktionsschnitt abweichen; getrennt
stehen `boundary_start_s`, `boundary_end_s` und `boundary_weighted_s` (Start doppelt). Leere Eingaben ergeben
`None` (Tabelle: „n. m.“), nicht 0. Dieses alte Format kennt keine Personen; für den Launch gilt `--daten`.

Die Vorhersage-Datei erzeugt `export_predictions.py` aus den Kandidaten einer Quelle (Phase 2):

```bash
python -m eval.export_predictions --source-id <uuid> --episode ep01.mp4 --out preds/ep01.json      # aus Postgres
python -m eval.export_predictions --json <ergebnis.json> --episode ep01.mp4 --out preds/ep01.json   # aus dem Storage-JSON
```

Standard: alle Kandidaten außer abgelehnte, sortiert nach `total`; `--only-gate-passed` und
`--include-rejected` ändern die Auswahl. Der Blindtest läuft mit `LLM_PROVIDER=local-heuristic` nur
als Rauchtest; belastbare Werte brauchen einen echten Provider.

## Zielwerte

| Metrik | Ziel | Hinweis |
|---|---|---|
| WER Studio-Audio (DE/AT) | < 5 % | Podcast-Mikro, kein Übersprechen |
| WER Studio-Audio (CH, Beta) | < 15 % | Dialekt zu Hochdeutsch, Modell aus `ASR_MODEL_CH` |
| Eigennamen-Fehlerrate | < 2 % | mit gepflegtem `brand_vocab` |
| Precision@10 | > 0,5 | Phase 2 |
| Boundary-Error | < 2 s | Phase 2, misst Satzgrenzen-Treue |

Jede Prompt- oder Modelländerung läuft gegen denselben Testdatensatz, getrennt nach Dialekt.
Testdaten liegen nicht im Repo (Persönlichkeitsrechte, Rechte am Material).

## Der Referenzsatz (`referenzsatz.py`)

Zwei Läufe gegeneinander zu halten geht nur, wenn dieselben Dateien drin waren. Sonst kann eine
geänderte Zahl alles heissen: die Pipeline ist besser geworden, oder es lagen drei Dateien mehr im
Ordner.

`eval/clips/referenzsatz_v1.json` hält deshalb je Beispieldatei ihren SHA-256 und ihre Grösse fest,
dazu die zusammengefassten Zahlen des Laufs. Die Videos selbst und ihr Text bleiben draussen: es
sind Aufnahmen von Kunden, sie gehören nicht in ein Repository. Wer die Messung nachvollziehen
will, braucht die Dateien und bekommt sie von dem, dem sie gehören.

Erfassen (nach einem Lauf von `learn_from_examples`):

```
.venv/bin/python -m eval.referenzsatz erfassen \
    --positiv "/pfad/Positive Beispiele" --negativ "/pfad/Negative Beispiele" \
    --messung messung.json --out eval/clips/referenzsatz_v1.json
```

Prüfen, bevor man Zahlen vergleicht:

```
.venv/bin/python -m eval.referenzsatz pruefen \
    --positiv "/pfad/Positive Beispiele" --negativ "/pfad/Negative Beispiele"
```

### Was der heutige Satz trägt, und was nicht

Der erfasste Satz hat vier gute und zwölf schlechte Beispiele. Das Manifest schreibt
`"belastbar": false`, und das ist keine Formalie: bei dieser Grösse liegen die gemessenen
Merkmale bis auf die Länge (Median 43,5 s gegen 57,5 s) ineinander. Wer daraus eine Regel für die
Clip-Auswahl ableitet, leitet sie aus Rauschen ab.

Für eine belastbare Aussage fehlen zwei Dinge, und beide kann nur die Redaktion liefern:

1. **Mehr Beispiele.** Zwanzig je Gruppe ist die Untergrenze, ab der ein Unterschied im Median
   überhaupt etwas heissen kann (`MINDESTGROESSE_JE_GRUPPE`).
2. **Lange Quellvideos mit markierten Stellen.** Die vorliegenden Beispiele sind fertige Clips.
   Damit lässt sich messen, wie ein guter Clip aussieht, aber nicht, ob die Pipeline die richtige
   Stelle in einem einstündigen Video findet. Dafür braucht es Dateien im Format von
   `eval/clips/*.json`: ein langes Video und die Zeitmarken, die ein Mensch genommen hätte.

## Grenzmessung je Richtlinie (`clip_eval.py --policy-version`)

`--policy-version 1` oder `2` setzt `CHOPSTR_POLICY_VERSION` für die Messung der Schnittgrenzen; ohne
Angabe gilt die aktive Fassung. Die gemessene Richtlinie steht im Ergebnis unter `richtlinie`. Unter
Fassung 2 kommt `grenze_nur_aus_pause` je Vorschlag und `grenze_nur_aus_pause_anteil` in der
Zusammenfassung dazu: Grenzen ohne Satzzeichen, nur aus einer Pause abgeleitet. Der Median der Länge ist
bei gerader Anzahl das Mittel der beiden mittleren Werte. Die Vorschläge selbst
kommen aus der Datenbank; wer beide Fassungen vergleichen will, lässt die Analyse je Fassung laufen
oder nimmt den Blindvergleich.

## Blindvergleich alt gegen neu (`blind_compare.py`, AP11)

Frage: Findet chopstr mit Fassung 2 bei gleicher Ausgabemenge bessere Clips als mit Fassung 1? Das
Ergebnis ist beobachtend, kein A/B-Test, kein Viralitätsmaß.

### Ablauf

1. Vorab festlegen: Erfolgskriterium, Mindestverbesserung und Auswertungsplan. Das Werkzeug schreibt
   das Kriterium aus Plan Abschnitt 8 Punkt 5 beim Erzeugen in den Schlüssel (Fassung 2 ist in
   Quellentreue und Eigenständigkeit nicht schlechter als Fassung 1, abzüglich `--toleranz`, Standard 0;
   die Verwerfungsquote wird berichtet). Nach dem Bewerten wird es nicht mehr geändert.
2. Rechnen:

   ```bash
   .venv/bin/python -m eval.blind_compare --out blind/                       # Fixtures (Demo und editorial_v1)
   .venv/bin/python -m eval.blind_compare --out blind/ --transkripte transkripte/ --ohne-fixtures
   .venv/bin/python -m eval.blind_compare --out blind/ --quelle <uuid>       # aus Postgres, braucht DATABASE_URL
   ```

   Je Quelle läuft `story_engine.run` mit Fassung 1 und mit Fassung 2, mit demselben Provider
   (`--provider`, Standard `local-heuristic`), demselben Brief (`--brief`) und derselben Obergrenze
   (`--k`, Standard 5). Für jeden angebotenen Kandidaten entsteht der Hook wie im Produkt
   (`copy_engine.write_copy` für `brief.platform`, ohne LanguageTool). Je Quelle zählen die besten n
   Kandidaten beider Fassungen, n ist die kleinere Ausgabemenge; der Überhang steht im Schlüssel unter
   `nicht_gepaart`. Gepaart wird innerhalb einer Quelle nach größter Überdeckung (`--paarung
   ueberdeckung`, Standard) oder nach Rang (`--paarung rang`).
3. Dateien im Ordner:

   | Datei | Für wen | Inhalt |
   |---|---|---|
   | `bewertung.json` | Bewertende | Clip-Paare `A` und `B`: Text, Zeiten, Dauer, `ausgabe` (welche Clips aus derselben Ausgabe stammen), `kontext` (Satzbereich in `quellen.json`). Kein Hook, keine Version, kein Score, keine Begründung; Quellen heißen `Q01`, `Q02` … |
   | `hooks_bewertung.json` | Bewertende, am besten andere Personen | Hook-Paare in eigener Reihenfolge und eigener A/B-Zuordnung: gesprochener Hook, Overlay-Text (`null` heißt keiner), Clip-Text zum Abgleich |
   | `quellen.json` | Bewertende | je Quelle das Transkript (bis 40 Sätze) oder plus/minus 5 Sätze um beide Clips jedes Paares, für beide Seiten gleich; bei Datenbankquellen der Medienverweis (`storage_key`) |
   | `raster.json` | Bewertende | Kriterien für Clips und Hooks mit Ankern 0 bis 4 |
   | `schluessel.json` | nur Auswertung | Zuordnung `A`/`B` zu Fassung für beide Bögen, echte Quellnamen, Seed, Paarung, Überhang, Erfolgskriterium |
   | `lauf.json` | nur Auswertung | je Quelle und Variante: Vorschläge, Verwerfungen je Grund, Modellaufrufe, Laufzeit, Hook-Kennzahlen, editorial_v1-Ergebnis, ClipCandidates; dazu die Stil-Leck-Prüfung |

   Reihenfolge der Paare und Seite A oder B sind zufällig mit festem Seed (`--seed`, Standard 1729);
   derselbe Seed ergibt dieselben Dateien. `schluessel.json` und `lauf.json` nicht an die Bewertenden
   geben.
4. Bewerten: je Paar beide Seiten nach dem Raster (ganze Zahlen 0 bis 4, leer heißt nicht bewertet),
   dann `praeferenz` `A`, `B`, `gleich` oder `beide_unbrauchbar`; eine Präferenz A, B oder gleich ohne
   Kriterienwerte gilt als Fehler, `beide_unbrauchbar` darf ohne Werte stehen. Unter `rater` (oben im Bogen)
   steht die Bewerter-ID. Je Paar zusätzlich `mangel`: `{"kategorie": einstieg|ende|kontext|ton|untertitel|inhalt|keine,
   "text": "..."}` (Frage 6.4 „Was stimmt an dem anderen nicht?“). Der Bericht zählt die Kategorien je Fassung: bei
   A oder B für die nicht gewählte Seite, bei „beide unbrauchbar“ für beide, bei „gleich“ ohne Fassung.
   Quellentreue mit `quellen.json`, Natürlichkeit am Audio der Quelle prüfen. Clips und Hooks getrennt
   bewerten, damit der Stil eines Hooks die Clip-Bewertung nicht verrät.
5. Auswerten: `.venv/bin/python -m eval.blind_compare --auswerten blind/` schreibt `blind/bericht.md`.
   Fehlt ein Paar im Schlüssel, steht ein unbekanntes Kriterium oder ein Wert außerhalb 0 bis 4 im
   Bogen, bricht die Auswertung mit einer Meldung ab, die das Paar nennt.

### Bewertungsseite (`bewertung.html`)

Die Redaktion füllt die Bögen in einer einzelnen Datei aus, ohne Build, Server oder Installation:
`eval/bewertung.html` im Browser öffnen (Doppelklick genügt), dann den Ordner des Laufs auf die Fläche
ziehen oder über „Dateien wählen“ beziehungsweise „Ordner wählen“ laden. Gelesen werden nur
`bewertung.json`, `hooks_bewertung.json`, `quellen.json` und `raster.json`; `schluessel.json` und
`lauf.json` bleiben ungeöffnet, damit die Verblindung hält. Alles läuft lokal im Browser.

Der Reiter Clips zeigt je Paar Seite A und Seite B nebeneinander (Text, Dauer, Segmentzahl, Zeiten) und
darunter den Quellkontext aus `quellen.json` mit Markierung, welche Sätze zu A und zu B gehören. Hook,
Versionskennung und Score erscheinen dort nicht. Der Reiter Hooks zeigt gesprochenen Hook, Overlay-Text
und den Clip-Text zur Deckung. Je Kriterium aus `raster.json` stehen die Anker 0 bis 4 mit Text, dazu
Präferenz (A, B, gleich, beide unbrauchbar), die Frage „Was stimmt an dem anderen nicht?“ (Kategorie
Einstieg, Ende, Kontext, Ton, Untertitel, Inhalt oder nichts, dazu ein kurzer Freitext) und ein Freitextfeld. Oben steht das Feld „Bewerter-ID“; sie geht als
`rater` in den Export.

Tastatur: `0` bis `4` setzen den Wert am Cursor und rücken vor (erst alle Kriterien von Seite A, dann
von Seite B), Pfeiltasten bewegen den Cursor, `Entf` löscht den Wert, `A`, `B`, `G` und `U` (beide
unbrauchbar) setzen die Präferenz, `W` und `Z` blättern. Der Fortschritt liegt im `localStorage` des Browsers, getrennt je Bogen
und Inhalt; „Lokalen Stand verwerfen“ setzt auf den Stand der geladenen Dateien zurück.

„Bewertung exportieren“ lädt `bewertung.json` und `hooks_bewertung.json` im Format des Erzeugers
herunter (gleiche Dateinamen, gleiche Schlüsselfolge, Werte als ganze Zahlen 0 bis 4 oder `null`). Beide
Dateien in den Ordner des Laufs legen, die Originale ersetzen, und mit `--auswerten` rechnen. Sind
Paare unvollständig, warnt die Seite und exportiert trotzdem: solche Paare tragen `"offen": true`, die
Liste steht in `offene_paare`; die Auswertung ignoriert beides und zählt ein Paar ohne Präferenz als
„offen“. Eine Präferenz ohne einen einzigen Kriterienwert wird nicht exportiert (sie ließe die
Auswertung abbrechen) und in der Warnung genannt. Clips und Hooks am besten von verschiedenen Personen
bewerten lassen; jede Person exportiert ihren Bogen mit eigener Bewerter-ID.

### Mehrere Bewerter (`--bewerter`)

```bash
.venv/bin/python -m eval.blind_compare --auswerten blind/ --bewerter bewertung_r1.json bewertung_r2.json hooks_r3.json
```

Clip- und Hook-Bögen werden an den Paar-IDs erkannt und ersetzen die Bögen im Ordner. Jeder Bogen braucht eine
eigene `rater`-ID. Die Kennzahlen zählen alle Urteile zusammen; der Bericht nennt die Bewerter und je
Bewerterpaar die gemeinsam entschiedenen Paare, den Anteil gleicher Präferenzen und Cohen-Kappa (nicht
berechenbar, wenn beide immer dieselbe eine Kategorie wählen). Urteile derselben Paare sind nicht unabhängig;
der Vorzeichentest ist dann nur ein Hinweis.

### Wettbewerbsmodus (`--extern`)

```bash
.venv/bin/python -m eval.blind_compare --out wett/ --extern opus_clips/ --eigene chopstr_clips/ --vergleichsart voller_output
.venv/bin/python -m eval.blind_compare --out wett/ --extern opus_clips/ --transkripte transkripte/ --vergleichsart momentwahl
```

Je Unterordner von `--extern` (und `--eigene`) ein `clip.json` mit `start_s`, `end_s`, `text`, `quelle`
(optional `rang`, `id`) und genau eine `.mp4`. Ohne `--eigene` rechnet die Engine (Fassung 2) die chopstr-Seite
aus den Quellen (`--transkripte` oder `--quelle`, Namen gleich `quelle`). `--vergleichsart` ist Pflicht und vorab
festgelegt: `voller_output` (Momentwahl, Schnitt, Untertitel, Bildausschnitt), `momentwahl` oder `schnitt`
(nur Paare desselben Moments, Überdeckung mindestens die Hälfte). Gepaart wird je Quelle nach Überdeckung bei
gleicher Ausgabemenge, der Überhang steht im Schlüssel. Die Videos liegen neutral benannt unter `medien/`. Die
Auswertung meldet die Gewinnrate von chopstr unter den entschiedenen Urteilen (Schwelle mindestens 60 %) und
den Anteil „beide unbrauchbar“ unter allen Urteilen (höchstens 20 %). Rechte am Material und an fremden
Clips vorab klären.

### Raster (Master-Prompt Abschnitte 19 und 26)

Anker für alle Kriterien: 0 nicht vorhanden oder kritisch verletzt, 1 schwach, 2 brauchbar, 3 stark
und begründet, 4 besonders überzeugend. Höher ist immer besser.

| Clip-Kriterium | Frage |
|---|---|
| Quellentreue | Gibt der Clip wieder, was die Quelle sagt, ohne Sinnumkehr, verlorene Bedingung oder falsche Zuordnung? |
| Eigenständigkeit | Versteht man den Clip ohne Vorwissen? |
| Einstieg | Ist der Anfang klar, und trägt er bis zum Kern? |
| Aufbau | Führt der Verlauf zum Kern, ohne Ballast und ohne Sprünge? |
| Abschluss | Endet der Clip mit eingelöstem Versprechen? |
| Natürlichkeit | Klingt der Schnitt natürlich (Sprachfluss, Atem, Pausen)? |
| Duplikate | Wiederholt der Clip einen anderen Clip derselben Ausgabe? |
| Manuelle Nacharbeit | Wie viel müsste die Redaktion am Schnitt ändern, bevor sie veröffentlicht? |

| Hook-Kriterium | Frage |
|---|---|
| Deckung durch den Clip | Behauptet der Hook nicht mehr, als der Clip sagt? |
| Klarheit | Versteht man den Hook beim ersten Lesen oder Hören? |
| Einstieg in den Clip | Führt der Hook in den Clip, ohne etwas anderes zu versprechen? |
| Ton | Klingt der Hook natürlich, ohne Floskel und Übertreibung? |

Die Anker je Kriterium stehen in `raster.json`.

### Bericht

`bericht.md` beginnt mit den Quellen ohne Vorschlag und ohne angebotenen Kandidaten je Fassung und dem
Urteil zum vorab festgelegten Erfolgskriterium (Erfüllt, Nicht erfüllt oder Nicht bewertet). Danach:
Material und Ausgabemenge, Stil-Leck-Prüfung, Clip- und Hook-Bewertung (Mittel, Streuung und Anzahl je
Kriterium, Präferenz mit zweiseitigem Vorzeichentest), Verwerfungsquote je Grund und Fassung (deutsche
Bezeichnung mit Code in Klammern), Dubletten und Laufereignisse getrennt, Modellaufrufe und Laufzeit je
Quellstunde (jeder strukturierte Aufruf am Provider gezählt, auch Hooks), editorial_v1-Bestehensquote
je Fassung und Fall (geprüft mit `tests/editorial_v1/harness.py`) und getrennt die einzelnen Schalter.

Stil-Leck-Prüfung: Segmente je Clip, Anteil mit Teaser, Dauer, Anteil der Hooks ohne Overlay-Text und
die häufigsten Hook-Anfänge je Fassung. Weicht ein Merkmal deutlich ab (Anteile um mehr als 25
Prozentpunkte, Dauer um mehr als 25 Prozent, ein Hook-Anfang bei mindestens der Hälfte einer Fassung
und unter 20 Prozent der anderen), warnt der Bericht: Bewertende könnten die Fassung erkennen.

Verwerfungsquote: Zähler sind die Verwerfungen aus `DetectReport.discarded`, Nenner alle Vorschläge der
Stufe 2 mit Ergebnis (verworfen oder angeboten), bei Fassung 1 vom Modell, bei Fassung 2 von der Suche,
ohne Dubletten. `DetectReport.proposals` steht zum Vergleich daneben. Dubletten sind derselbe Moment,
mehrfach gefunden; ab Fassung 2 stehen sie nicht in `discarded`, sondern in `report.search["duplicates"]`
und je Art in `report.search["duplicate_counts"]` (`duplicate_payoff`, `same_span`, `same_opening`,
`same_statement`, `chapter_overlap`, `same_result`), unter Fassung 1 als `duplicate` in `discarded`. Sie
stehen in einer eigenen Tabelle und zählen weder im Zähler noch im Nenner. Laufereignisse
(`budget_exhausted`, `clip_candidate_error`, `llm_budget` beim Vorschlag) betreffen keinen einzelnen
Vorschlag und stehen ebenfalls getrennt. Ein Eintrag ohne Grund heißt nach seiner Stufe
(`ohne_grund/search`).

editorial_v1 im Blindvergleich: geprüft wird jeder angebotene Kandidat mit dem Harness, Schnittplan und
entfernte Stellen der Kürzung (`rubric.removed_spans`) zusammen, damit eine lokale Naht (technische Pause,
Füllwort, Einwurf) nicht als Naht mitten im Satz zählt.

Schalter: Fassung 2 mit allen Gruppenschaltern aus (Basis), je eine Gruppe an (Auswahl:
`gates.discard_hard`, `search.payoff_first`; Hooks: `hook.native_spoken`; Kürzung: `trim.enabled`)
und alle zusammen (Kombination), je mit Kandidaten, Verwerfungsquote, Modellaufrufen und den
Hook-Kennzahlen (Anteil native, ohne Overlay, gesprochener Hook als ganzer Satz, mit Claim-Befund).
Kürzung und Kombination setzen zusätzlich die Regel `trim.enabled: true`, weil sie in der Richtlinie bis
zur Abnahme aus steht; nur der Schalter allein ergäbe die Basis. Die Varianten entstehen über eine Kopie
der Richtlinie, auf die `EDITORIAL_DIR` für die Dauer des Laufs zeigt. Eigene Overrides mit `--override`
(mehrfach) oder `CHOPSTR_BLIND_OVERRIDES` (durch Komma getrennt): Schalter als `pfad=true|false` (Pfade
aus `editorial.V2_SWITCHES`), Regeln als `regel:pfad=wert`, erlaubt nur `regel:trim.enabled`,
`regel:gates.discard_hard`, `regel:hook.allow_partial_opening` (je `true` oder `false`) und
`regel:bewertung.modus_v2` (`sortieren` oder `sperren`). Beispiel:
`CHOPSTR_BLIND_OVERRIDES="cut.padding=true,regel:trim.enabled=true"`. Ob ein Schalter laut
`editorial.V2_IMPLEMENTED_SWITCHES` gebaut ist, steht in Klammern, gesetzte Regeln stehen dahinter.
`--ohne-schalter` rechnet nur Fassung 1 und 2.

### Was der Vergleich nicht leistet

* Organische Veröffentlichungen sind kein A/B-Test. Reichweite nach dem Posten hängt an Zeitpunkt,
  Thema, Konto und Plattform; sie belegt keine der beiden Fassungen.
* Mit `local-heuristic` sind alle Werte unkalibriert und die Fixtures sind klein (14 Fälle plus Demo).
  Das Werkzeug zeigt den Ablauf; belastbar wird es mit einem echten Provider und echtem Material.
* Unsicherheit und negative Ergebnisse gehören in den Bericht wie positive.
* Kein Kundenmaterial bei Wettbewerbern hochladen. Ein Vergleich mit anderen Werkzeugen gehört nicht
  zu diesem Paket und braucht die Rechte am Material.
