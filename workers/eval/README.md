# Eval: ASR-Qualität und Clip-Auswahl, getrennt nach Dialekt

Zwei Werkzeuge, beide ohne GPU lauffähig:

| Skript | Frage | Aufruf |
|---|---|---|
| `wer_eval.py` | Wie gut hört der Worker Deutsch (DE/AT/CH)? | `python -m eval.wer_eval gold/ hyp/ --lexicon names.txt --json wer.json` |
| `eval_harness.py` | Wie nah kommen die Kandidaten an die Redaktion? | `python -m eval.eval_harness gold_clips/ preds/ --k 10 --json clips.json` |
| `referenzsatz.py` | Mit welchen Dateien wurde gemessen, und sind es noch dieselben? | `python -m eval.referenzsatz pruefen --positiv "…" --negativ "…"` |

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
