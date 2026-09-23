# @chopstr/prompts

Alle LLM-Prompts sind versioniert (`<name>_v<N>.md`). Der Worker lädt sie per Name und Version; die
Version wandert in `candidates.prompt_version`, `hook_versions.prompt_version` und in den LLM-Cache-Key
`(provider, model, prompt_version, input_hash)`.

Regeln:
- Eine Änderung am Prompt = neue Datei mit erhöhter Version. Alte Versionen bleiben (Reproduzierbarkeit).
- Jede Änderung läuft gegen den Testdatensatz (`workers/eval`), getrennt nach Dialekt.
- Was einen guten Clip ausmacht, steht nicht im Prompt, sondern in `packages/editorial/clip_policy_v<N>.yaml`.
  Bewertende Prompts tragen dafür den Platzhalter `{policy}` und im Frontmatter `policy: clip_policy_v<N>`.
  Gewichte im Frontmatter sind nur eine Kopie zur Ansicht; bei Abweichung gewinnt die Grundlage (Warnung im Log).
- Kein Prompt erzeugt finale Videos. Ausgabe sind immer strukturierte Vorschläge mit Belegen.
- Code-Bezeichner Englisch, Prompt-Texte Deutsch.

| Datei | Zweck | Ausgabe (Tool-Use-Schema) |
|---|---|---|
| `system_editor_v1.md` | Systemrolle: Senior-Redaktion DACH | – |
| `propose_moments_v1.md` | Stufe 2: Momente pro Kapitel als Satz-Spannen | `propose_moments` |
| `score_clip_v1.md` | Stufe 3, Bestand: eigene Rubrik (5 Kriterien, 0 bis 10) | `score_clip` |
| `score_clip_v2.md` | Stufe 3, aktuell: Rubrik aus der redaktionellen Grundlage (7 Kriterien, 0 bis 2) | `score_clip` |
| `story_graph_confirm_v1.md` | Stufe 4: relativiert ein späterer Satz den Clip? | `confirm_qualification` |
| `hooks_v1.md` | Copy: 5 Hook-Varianten nach Muster | `write_hooks` |
| `post_caption_v1.md` | Copy: Post-Text pro Plattform | `write_post_caption` |
