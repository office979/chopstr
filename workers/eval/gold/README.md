# Gold-Set `gold_clip_v1`

Veröffentlichte Shorts, die als Vorbild gelten, mit ihrer Fundstelle in der Langform und einer redaktionellen
Zerlegung (Hook, Ein- und Ausstieg, Payoff, Struktur, Schnitt, Copy). Grundlage für `python -m eval.train compare`
und für spätere Ranking- und Fine-Tuning-Daten.

- **Nur Metadaten und URLs.** Keine Video-, Audio- oder Bilddateien im Repo (`rights` ist immer `metadata_only`).
  Heruntergeladene Medien liegen nur im Cache `.local/eval-cache/` (gitignored).
- Schema: `gold_clip_v1.schema.json`. Unbekannte Felder sind `null`.
- Prüfen: `python -m eval.train gold validate --gold eval/gold/<datei>.json`, Übersicht mit `gold stats`.
- `fixtures/synthetic_v1.json` ist synthetisch und nur für Tests. Echte Daten kommen nach `dach_v1.json`.

Ein Clip taugt für den Vergleich (`ready_for_compare`), wenn er gültig ist und `source.url`, `source.start_s` und
`source.end_s` trägt. Die Vollständigkeit (Anteil gefüllter Felder) und die fehlenden Kernfelder meldet der Validator
je Clip; sie sind Kennzahl, kein Fehler.
