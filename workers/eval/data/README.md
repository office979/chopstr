# Referenzdatensatz (`eval/data`)

Hier liegen die menschlichen Referenzen, gegen die chopstr gemessen wird (Launch-Auftrag Abschnitt 6.1). Die
Videos selbst liegen nicht im Repository (Rechte am Material, Persönlichkeitsrechte); hier stehen nur Zeiten,
Urteile und Texte, die die Redaktion freigegeben hat.

Prüfen: `.venv/bin/python -m eval.data_loader eval/data` (aus `workers/`). Der Loader meldet jede ungültige
Datei mit Datei, Stelle und Problem, zum Beispiel
`spannen/ep01.json: spannen[3]: start_s 40 und end_s 12: Ende muss nach dem Anfang liegen, Anfang ab 0.`

Beispiele für jedes Format liegen unter `beispiel/` (fiktiv). Dort auch `beispiel/berichte/`, ein gekürzter
DetectReport mit `funnel`, damit `eval_harness --daten eval/data/beispiel --berichte eval/data/beispiel/berichte`
ohne echtes Material durchläuft.

## Datenvertrag

`<quelle>` ist die `id` aus `split.json` (sonst der `dateiname`). Zeiten sind Sekunden ab Dateibeginn.

### `split.json`: Entwicklung, Kalibrierung, Abschluss

```json
{"version": 1,
 "quellen": [
   {"id": "ep12", "dateiname": "debatte_folge12.mp4", "aufnahme": "debatte_folge12", "teil": "entwicklung",
    "format": "debatte", "sprachvariante": "AT", "dauer_s": 3540.0, "herkunft": "PLACEMedia, Rechte geklärt am ..."}
 ]}
```

* `teil`: `entwicklung` (Fehlersuche, jede Änderung), `kalibrierung` (Gewichte und Schwellen einstellen) oder
  `abschluss` (unangetastet bis zur Abnahme).
* `format`: `debatte`, `podcast`, `interview`, `keynote`, `webinar`, `erklaerformat`, `monolog` oder `fixture`.
* `sprachvariante`: `DE`, `AT`, `CH` oder `gemischt`. `dauer_s`: positive Zahl.
* `aufnahme`: Kennung der Aufnahme (Standard: die `id`). Ausschnitte derselben Aufnahme müssen im selben Teil
  liegen, sonst bricht der Loader ab. Zwei Clips aus derselben Debatte sind keine unabhängigen Belege.
* Der Abschlussteil ist gesperrt: `eval_harness --teil abschluss` läuft nur mit `--abschluss-bestaetigt`, und das
  erst, wenn Bewertungsregeln und Schwellen festgeschrieben sind.

`split.json` in diesem Ordner beschreibt das heute vorhandene Material, alles `entwicklung`: das Demo-Skript und
die 14 Fixture-Fälle aus `tests/editorial_v1` (nur Wortlisten), die zwei kurzen Quellen aus der lokalen
Datenbank (`quelle_16982bb5...`, `quelle_c958814e...`, Dauer aus der Wortliste) und die drei synthetischen
Gespräche aus `eval/runs/testmaterial` (Sprachsynthese, nicht versioniert). `abschluss` ist leer, weil es noch
kein echtes Langvideo mit Rechteklärung gibt.

### `spannen/<quelle>.json`: menschlich gewählte Spannen

```json
{"quelle": "ep12", "spannen": [
  {"person": "clipper_a", "start_s": 120.0, "end_s": 165.0, "platform": "tiktok", "views": 12400}]}
```

`platform`: `tiktok`, `reels`, `shorts`, `linkedin`, `youtube` oder `andere`; `views` ist optional (ganze Zahl
oder `null`). `data_loader.gold_silver(spannen)` bildet daraus Referenzmomente: Spannen verschiedener Personen
mit IoU >= 0,5 sind ein Moment; **Gold** heißt von mindestens zwei Personen gewählt, **Silber** einmal. Der Moment
reicht vom Median der Anfänge bis zum Median der Enden. Gold ist ein Übereinstimmungssignal, keine
Korrektheitsgarantie (Review 2B): ob der fertige Clip korrekt und postbar ist, messen Sinnfehler-Bogen und
Redaktionsurteil getrennt.

### `redakteure/<quelle>.json`: Top-10 je Redakteur

```json
{"quelle": "ep12", "redakteure": [
  {"person": "red_1", "top10": [{"rang": 1, "start_s": 119.0, "end_s": 164.0}]}]}
```

Jede Person unabhängig, Rang 1 bis 10 je Person einmal, höchstens zehn Einträge.

### `transkript_referenz/<quelle>.json` oder `<quelle>.rttm`

```json
{"quelle": "ep12", "sprachvariante": "AT", "bereich": {"start_s": 600.0, "end_s": 1800.0},
 "woerter": [{"wort": "Doch,", "start": 601.70, "end": 602.05, "sprecher": "S2"}],
 "segmente": [{"sprecher": "S2", "start": 601.70, "end": 602.90}]}
```

Für WER, cpWER und Sprecherzuordnung je Wort. `segmente` ist optional; fehlt es, entstehen Segmente aus den
Wörtern. Eine RTTM-Datei (`SPEAKER <datei> 1 <start> <dauer> <NA> <NA> <sprecher> <NA> <NA>`) liefert nur
Segmente, damit nur DER. Überlappung entsteht aus Segmenten, die sich zeitlich überschneiden.

### `audioanker/<quelle>.json`

```json
{"quelle": "ep12", "pruefer": "anker_1", "anker": [
  {"wort": "Wien", "anker_start": 602.16, "anker_ende": 602.47, "kategorie": "name"}]}
```

Wortanfang und Wortende am Audio kontrolliert (Wellenform), nie aus Whisper übernommen. `kategorie`: `name`,
`betrag`, `prozent`, `verneinung`, `einschraenkung` oder `sonstiges`.

### `schnittpunkte/<quelle>.json`

```json
{"quelle": "ep12",
 "schnittpunkte": [{"clip_id": "clip_01", "zeit_s": 120.0, "urteil": "natuerlich", "hoerer": "h1"}],
 "clip_urteile": [{"clip_id": "clip_01", "hoerer": "h1", "urteil": "brauchbar"}]}
```

`urteil` je Punkt: `natuerlich`, `abgehackt` oder `zu_lang`; je Clip `brauchbar` oder `unbrauchbar`. Ein Clip mit
einem abgehackten Schnitt zählt als unbrauchbar, auch wenn die übrigen Punkte sauber sind
(`eval_harness.cut_quality`).

## Was fehlt (Stand 20.10.2026)

Keine der Dateiarten außer `split.json` hat heute echte Einträge. Alle Werte, die menschliche Referenzen
brauchen, sind deshalb nicht messbar; die Ursache steht in `eval/results/baseline.json`.
