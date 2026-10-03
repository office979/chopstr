# Eval: ASR-Qualität und Clip-Auswahl, getrennt nach Dialekt

Werkzeuge, alle ohne GPU lauffähig:

| Skript | Frage | Aufruf |
|---|---|---|
| `wer_eval.py` | Wie gut hört der Worker Deutsch (DE/AT/CH)? | `python -m eval.wer_eval gold/ hyp/ --lexicon names.txt --json wer.json` |
| `eval_harness.py` | Wie nah kommen die Kandidaten an die Redaktion? | `python -m eval.eval_harness gold_clips/ preds/ --k 10 --json clips.json` |
| `referenzsatz.py` | Mit welchen Dateien wurde gemessen, und sind es noch dieselben? | `python -m eval.referenzsatz pruefen --positiv "…" --negativ "…"` |
| `clip_eval.py` | Wie sauber schneiden die Vorschläge einer Quelle, unter welcher Richtlinie? | `python -m eval.clip_eval --titel "…" --policy-version 2 --json messung.json` |
| `blind_compare.py` | Ist Fassung 2 bei gleicher Ausgabemenge redaktionell besser als Fassung 1? | `python -m eval.blind_compare --out blind/` und `--auswerten blind/` |

Beide laufen aus `workers/` mit aktivierter venv (`.venv/bin/python -m eval.wer_eval ...`).

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
Treffer = IoU >= 0,5. Boundary-Error misst, wie weit Anfang/Ende vom Redaktionsschnitt abweichen.

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
Zusammenfassung dazu: Grenzen ohne Satzzeichen, nur aus einer Pause abgeleitet. Die Vorschläge selbst
kommen aus der Datenbank; wer beide Fassungen vergleichen will, lässt die Analyse je Fassung laufen
oder nimmt den Blindvergleich.

## Blindvergleich alt gegen neu (`blind_compare.py`, AP11)

Frage: Findet chopstr mit Fassung 2 bei gleicher Ausgabemenge bessere Clips als mit Fassung 1? Das
Ergebnis ist beobachtend, kein A/B-Test, kein Viralitätsmaß.

### Ablauf

1. Vorab festhalten: Erfolgskriterium (Fassung 2 ist in Quellentreue und Eigenständigkeit nicht
   schlechter, Plan Abschnitt 8 Punkt 5), Mindestverbesserung und Auswertungsplan. Erst danach rechnen.
2. Rechnen:

   ```bash
   .venv/bin/python -m eval.blind_compare --out blind/                       # Fixtures (Demo und editorial_v1)
   .venv/bin/python -m eval.blind_compare --out blind/ --transkripte transkripte/ --ohne-fixtures
   .venv/bin/python -m eval.blind_compare --out blind/ --quelle <uuid>       # aus Postgres, braucht DATABASE_URL
   ```

   Je Quelle läuft `story_engine.run` mit Fassung 1 und mit Fassung 2, mit demselben Provider
   (`--provider`, Standard `local-heuristic`), demselben Brief (`--brief`) und derselben Obergrenze
   (`--k`, Standard 5). Für jeden angebotenen Kandidaten entsteht der Hook wie im Produkt
   (`copy_engine.write_copy`, ohne LanguageTool). Je Quelle wird die Ausgabemenge auf die kleinere der
   beiden gekürzt (Top-k nach Gesamtwert); der Überhang steht im Schlüssel unter `nicht_gepaart`.
3. Dateien im Ordner:

   | Datei | Für wen | Inhalt |
   |---|---|---|
   | `bewertung.json` | Bewertende | Paare `A` und `B` mit Text, Zeiten, Hook und `ausgabe` (welche Clips aus derselben Ausgabe stammen); keine Version, kein Score, keine Begründung |
   | `raster.json` | Bewertende | Kriterien mit Ankern 0 bis 4 |
   | `schluessel.json` | nur Auswertung | Zuordnung `A`/`B` zu Fassung, Seed, Überhang |
   | `lauf.json` | nur Auswertung | je Quelle und Variante: Vorschläge, Verwerfungen je Grund, Modellaufrufe, Laufzeit, editorial_v1-Ergebnis, ClipCandidates |

   Reihenfolge der Paare und Seite A oder B sind zufällig mit festem Seed (`--seed`, Standard 1729);
   derselbe Seed ergibt dieselben Dateien. `schluessel.json` und `lauf.json` nicht an die Bewertenden
   geben.
4. Bewerten: je Paar beide Seiten nach dem Raster (ganze Zahlen 0 bis 4, leer heißt nicht bewertet),
   dann `praeferenz` `A`, `B` oder `gleich`. Natürlichkeit am Audio der Quelle mit den Zeiten prüfen.
   Bewertende kennen die Herkunft nicht und erraten sie nicht.
5. Auswerten: `.venv/bin/python -m eval.blind_compare --auswerten blind/` schreibt `blind/bericht.md`.

### Raster (Master-Prompt Abschnitte 19 und 26)

Anker für alle Kriterien: 0 nicht vorhanden oder kritisch verletzt, 1 schwach, 2 brauchbar, 3 stark
und begründet, 4 besonders überzeugend. Höher ist immer besser.

| Kriterium | Frage |
|---|---|
| Quellentreue | Gibt der Clip wieder, was die Quelle sagt, ohne Sinnumkehr, verlorene Bedingung oder falsche Zuordnung? |
| Eigenständigkeit | Versteht man den Clip ohne Vorwissen? |
| Einstieg | Ist der Anfang klar, und trägt er bis zum Kern? |
| Aufbau | Führt der Verlauf zum Kern, ohne Ballast und ohne Sprünge? |
| Abschluss | Endet der Clip mit eingelöstem Versprechen? |
| Natürlichkeit | Klingt der Schnitt natürlich (Sprachfluss, Atem, Pausen)? |
| Duplikate | Wiederholt der Clip einen anderen Clip derselben Ausgabe? |
| Manuelle Nacharbeit | Wie viel müsste die Redaktion ändern, bevor sie veröffentlicht? |

Die Anker je Kriterium stehen in `raster.json`.

### Bericht

`bericht.md` enthält: Mittel je Kriterium und Fassung (mit Anzahl), Präferenz, Verwerfungsquote je
Grund und Fassung (Anteil an allen Vorschlägen der Stufe 2), Modellaufrufe und Laufzeit je
Quellstunde (jeder strukturierte Aufruf am Provider gezählt, auch Hooks), editorial_v1-Bestehensquote
je Fassung und Fall (geprüft mit `tests/editorial_v1/harness.py`) und getrennt die einzelnen Schalter.

Schalter: Fassung 2 mit allen Gruppenschaltern aus (Basis), je eine Gruppe an (Auswahl:
`gates.discard_hard`, `search.payoff_first`; Hooks: `hook.native_spoken`; Kürzung: `trim.enabled`)
und alle zusammen (Kombination). Die Varianten entstehen über eine Kopie der Richtlinie mit geänderten
Schaltern, auf die `EDITORIAL_DIR` für die Dauer des Laufs zeigt. Eigene Overrides:
`--override trim.enabled=true` (mehrfach) oder `CHOPSTR_BLIND_OVERRIDES="trim.enabled=true,cut.padding=false"`.
Ein Schalter ohne Code ändert nichts; der Bericht weist aus, welche gebaut sind
(`editorial.V2_IMPLEMENTED_SWITCHES`). `--ohne-schalter` rechnet nur Fassung 1 und 2.

### Was der Vergleich nicht leistet

* Organische Veröffentlichungen sind kein A/B-Test. Reichweite nach dem Posten hängt an Zeitpunkt,
  Thema, Konto und Plattform; sie belegt keine der beiden Fassungen.
* Mit `local-heuristic` sind alle Werte unkalibriert und die Fixtures sind klein (14 Fälle plus Demo).
  Das Werkzeug zeigt den Ablauf; belastbar wird es mit einem echten Provider und echtem Material.
* Unsicherheit und negative Ergebnisse gehören in den Bericht wie positive.
* Kein Kundenmaterial bei Wettbewerbern hochladen. Ein Vergleich mit anderen Werkzeugen gehört nicht
  zu diesem Paket und braucht die Rechte am Material.
