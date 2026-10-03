# Schnittplan — Aufbau

Eine Datei unter `schnittplaene/<name>.json`. Nachvollziehbar, prüfbar, versioniert.

```json
{
  "quelle": "schnitte/tipp1.mp4",
  "originalaufnahme": "aufnahmen/roh-2026-09-26.mp4",
  "quelleOffsetZumOriginal": 45.0,
  "transkript": "schnitte/tipp1.transcript.json",
  "schnittgefuehl": "kompakt",
  "erstelltAm": "2026-09-26",

  "behalten": [
    {
      "start": 2.41,
      "ende": 18.70,
      "grund": "Kernaussage: die drei Schritte werden benannt",
      "unsicherheit": "keine"
    }
  ],

  "entfernt": [
    {
      "start": 0.0,
      "ende": 2.41,
      "grund": "Fehlstart — Satz wird danach neu begonnen",
      "beleg": "w0–w5: \"Also, äh, heute geht es um\"",
      "unsicherheit": "keine"
    }
  ],

  "zurPruefung": [
    {
      "zeit": 12.30,
      "frage": "Pause von 0,9 s vor der Zahl. Wirkt wie Betonung. Stehen lassen?",
      "vorschlag": "stehen lassen"
    }
  ]
}
```

## Felder

| Feld | Bedeutung |
|---|---|
| `quelle` | Datei, auf die sich **alle** Zeiten beziehen. Genau eine. |
| `quelleOffsetZumOriginal` | Sekunden, die `quelle` im Original später beginnt. `0`, wenn `quelle` das Original ist. |
| `behalten` | Was ins fertige Video kommt, in zeitlicher Reihenfolge. Darf sich nicht überlappen. |
| `entfernt` | Was wegfällt — **mit Beleg**. Nur zur Nachvollziehbarkeit, das Werkzeug liest es nicht. |
| `zurPruefung` | Unsichere Stellen. Nicht automatisch geschnitten. Der Mensch entscheidet. |
| `unsicherheit` | `"keine"`, `"gering"` oder `"hoch"`. Bei `"hoch"` gehört die Stelle zusätzlich in `zurPruefung`. |

## Regeln

- Zeiten in Sekunden mit bis zu drei Nachkommastellen, immer bezogen auf `quelle`.
- **Niemals** Zeiten aus verschiedenen Dateien in einem Plan mischen.
- `entfernt` braucht immer einen `beleg` aus dem Transkript. Ohne Beleg wird nicht geschnitten.
- Reihenfolge der Aussagen bleibt. Der Plan sortiert Inhalte nicht um.
