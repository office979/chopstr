# Gold-Set `gold_clip_v1`

Veröffentlichte Shorts, die als Vorbild gelten, mit ihrer Fundstelle in der Langform und einer redaktionellen
Zerlegung (Hook, Ein- und Ausstieg, Payoff, Struktur, Schnitt, Copy). Grundlage für `python -m eval.train compare`
und für spätere Ranking- und Fine-Tuning-Daten.

- **Nur Metadaten und URLs.** Keine Video-, Audio- oder Bilddateien im Repo (`rights` ist immer `metadata_only`).
  Heruntergeladene Medien liegen nur im Cache `.local/eval-cache/` (gitignored).
- Schema: `gold_clip_v1.schema.json`. Unbekannte Felder sind `null`.
- Prüfen: `python -m eval.train gold validate --gold eval/gold/<datei>.json`, Übersicht mit `gold stats`.
- `fixtures/synthetic_v1.json` ist synthetisch und nur für Tests.
- `dach_v1.json` ist das echte DACH-Set: 25 Shorts (Podcasts, Streamer, Formate), 7 davon mit Fundstelle.

Ein Clip taugt für den Vergleich (`ready_for_compare`), wenn er gültig ist und `source.url`, `source.start_s` und
`source.end_s` trägt. Die Vollständigkeit (Anteil gefüllter Felder) und die fehlenden Kernfelder meldet der Validator
je Clip; sie sind Kennzahl, kein Fehler.

Verdichtete Clips (optional, `null` erlaubt):

- `source.segments`: Quellstellen `[start_s, end_s]` in Clip-Reihenfolge. Je Stelle Start vor Ende, Zahlen ab 0.
  Eine Stelle außerhalb von `start_s` bis `end_s` meldet der Validator als Hinweis (`warnings`), nicht als Fehler.
- `breakdown.edits.n_source_segments`: Zahl der Stellen; muss zu `segments` passen, wenn beide gesetzt sind.
- `breakdown.edits.compression`: Quellspanne geteilt durch Cliplänge.

`compare` wertet einen Vorschlag als Treffer gegen die Gesamtspanne oder gegen die Vereinigung der Quellstellen und
weist `multi_segment_gold` aus (Anteil Gold mit mehr als einer Stelle). In `dach_v1.json` sind 5 der 7 ausgerichteten
Clips aus 2 bis 6 Stellen verdichtet.
