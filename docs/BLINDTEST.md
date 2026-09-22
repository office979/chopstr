# Blindtest Phase 2 (Abnahme: Precision@10 > 0,5 für DE/AT)

Ziel: Zeigen, dass die Story-Engine auf echtem DACH-Material näher an der Redaktion liegt als ein
US-Tool. Der Test läuft auf denselben Dateien, verblindet, mit fünf Redakteur:innen oder Creatorn.

## Material

| Dialekt | Dateien | Anforderung |
|---|---|---|
| DE | 20 | Podcasts, Interviews, Keynotes, mindestens 5 mit zwei oder mehr Sprechern |
| AT | 5 | davon 2 Debattenformate |
| CH | 2 | nur als Beta-Beobachtung, zählt nicht für die Abnahme |

Pro Datei: Rechte geklärt (`rights_status`), Redaktions-Briefing ausgefüllt (Zielgruppe, gewünschte
Momente, Ausschlüsse), Markenprofil zugeordnet.

## Gold-Standard

Jede Redakteur:in markiert pro Datei die Clips, die sie posten würde, mit Rating
(3 = sofort postbar, 2 = mit Nacharbeit, 1 = Notlösung). Format siehe `workers/eval/README.md`:

```json
{"episode": "ep01.mp4", "dialect": "AT", "clips": [{"start": 812.4, "end": 861.0, "rating": 3}]}
```

Gold-Clips werden **vor** dem Blick auf die Maschinenvorschläge erfasst.

## Ablauf

1. Dateien durch chopstr laufen lassen (`detect_candidates`), Vorhersagen exportieren:
   `python -m eval.export_predictions --source <id> --out preds/ep01.json`.
2. Dieselben Dateien durch das Vergleichstool laufen lassen; Vorschläge im selben Format ablegen.
3. Bewertung: `python -m eval.eval_harness gold/ preds/ --k 10` (Precision@10, Recall, Grenzfehler
   pro Dialekt). Zusätzlich manuell: Anteil der Top-5, die eine Redakteur:in ohne Änderung annimmt.
4. Auswertung getrennt nach Dialekt und nach Sprecherzahl (Talking Head vs. Mehrsprecher).

## Kill-Kriterien (aus der Research)

- Top-5-Acceptance nach zwei Iterationen unter 35 %: Fokus von automatischer Auswahl auf Suche und
  Assistenz verschieben.
- Reviewzeit sinkt nicht um mindestens 30 %: keine Distributionserweiterung priorisieren.
- Dialektkorrekturen betreffen mehr als 10 % der Wörter: Dialektabdeckung vor Go-to-Market ausbauen.

## Was gemessen wird, was nicht

Gemessen: Precision@10, Recall, Grenzfehler in Sekunden, Anteil Kandidaten mit erfüllten
Pflichtkriterien, Anteil bestätigter Story-Graph-Warnungen, Reviewminuten pro angenommenem Clip.
Nicht gemessen: Viralität. Reichweitenprognosen sind zu verrauscht für eine Abnahme.
