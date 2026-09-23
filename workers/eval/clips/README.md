# Referenzstellen für die Clip-Messung

Hier liegt je Referenzvideo eine JSON-Datei mit den Stellen, die eine Redaktion von Hand
markiert hat. Sie beantworten die Frage: findet die Pipeline das, was ein Mensch genommen hätte?

Ohne diese Dateien läuft die Messung trotzdem. Sie prüft dann nur die Schnittgrenzen, also ob ein
Clip sauber anfängt und aufhört. Das ist der Teil, der keine Referenz braucht.

## Format

Eine Datei je Video, Name frei wählbar, Endung `.json`:

```json
{
  "video": "podcast-folge-13.mp4",
  "stellen": [
    {
      "start_s": 812.4,
      "end_s": 861.0,
      "grund": "Klare Zahl mit Beleg, funktioniert ohne Vorwissen"
    },
    {
      "start_s": 1240.0,
      "end_s": 1272.5,
      "grund": "Pointe sitzt am Ende, kein Rückverweis"
    }
  ]
}
```

| Feld | Bedeutung |
|---|---|
| `video` | Dateiname oder Titel der Quelle. Dient nur der Zuordnung, wird nicht zum Suchen benutzt. |
| `start_s` | Sekunde, an der die Stelle beginnt |
| `end_s` | Sekunde, an der die Stelle endet |
| `grund` | Warum diese Stelle gut ist. Freier Text, nur für Menschen. |

Die Zeiten beziehen sich auf das Original, nicht auf einen geschnittenen Clip.

## Was als Treffer zählt

Ein Vorschlag der Pipeline gilt als Treffer für eine Referenzstelle, wenn er mindestens die Hälfte
dieser Stelle abdeckt:

    Überlappung in Sekunden / Länge der Referenzstelle >= 0,5

Diese Richtung ist bewusst gewählt. Ein Vorschlag, der die markierte Stelle vollständig enthält und
noch etwas Anlauf mitnimmt, ist brauchbar. Ein Vorschlag, der nur den Schluss erwischt, ist es
nicht. Zusätzlich steht in der Ausgabe die Schnittmenge über die Vereinigung (IoU), damit man
erkennt, wie viel zu viel mitgenommen wurde.

## Aufruf

    .venv/bin/python -m eval.clip_eval --titel "Jakob Test" --referenzen eval/clips --json messung.json

Die Messung liest die Kandidaten aus der Datenbank. Das Video muss also vorher durch die Analyse
gelaufen sein.
