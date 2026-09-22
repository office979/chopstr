# Eval: ASR-Qualität und Clip-Auswahl, getrennt nach Dialekt

Zwei Werkzeuge, beide ohne GPU lauffähig:

| Skript | Frage | Aufruf |
|---|---|---|
| `wer_eval.py` | Wie gut hört der Worker Deutsch (DE/AT/CH)? | `python -m eval.wer_eval gold/ hyp/ --lexicon names.txt --json wer.json` |
| `eval_harness.py` | Wie nah kommen die Kandidaten an die Redaktion? | `python -m eval.eval_harness gold_clips/ preds/ --k 10 --json clips.json` |

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
