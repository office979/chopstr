# @chopstr/prompts

Alle LLM-Prompts sind versioniert (`<name>_v<N>.md`). Der Worker lädt sie per Name und Version; die
Version wandert in `candidates.prompt_version`, `hook_versions.prompt_version` und in den LLM-Cache-Key
`(provider, model, prompt_version, input_hash)`.

Regeln:
- Eine Änderung am Prompt = neue Datei mit erhöhter Version. Alte Versionen bleiben (Reproduzierbarkeit).
- Eine neue Version wird erst wirksam, wenn eine Policy sie pinnt. Der Produktionspfad lädt nur über
  `prompts.load_pinned(name)`; die Version kommt aus der aktiven Grundlage (`CHOPSTR_POLICY_VERSION`,
  Standard 1). Fassung 1 pinnt im Code (`editorial.V1_PROMPT_PINS`), ab Fassung 2 steht der Pin im
  Abschnitt `prompts` der Datei `packages/editorial/clip_policy_v<N>.yaml`. Eine neue Datei allein ändert
  also nichts; erst der Pin schaltet um, und zurück geht es über den Pin oder die Policy-Fassung.
  `prompts.load(name)` ohne Version nimmt weiter die höchste Datei, schreibt aber eine Warnung ins Log
  und ist nur für Werkzeuge und Tests gedacht.
- Jede Änderung läuft gegen den Testdatensatz (`workers/eval`), getrennt nach Dialekt.
- Was einen guten Clip ausmacht, steht nicht im Prompt, sondern in `packages/editorial/clip_policy_v<N>.yaml`.
  Bewertende Prompts tragen dafür den Platzhalter `{policy}` und im Frontmatter `policy: clip_policy_v<N>`.
  Gewichte im Frontmatter sind nur eine Kopie zur Ansicht; bei Abweichung gewinnt die Grundlage (Warnung im Log).
- Kein Prompt erzeugt finale Videos. Ausgabe sind immer strukturierte Vorschläge mit Belegen.
- Code-Bezeichner Englisch, Prompt-Texte Deutsch.

| Datei | Zweck | Ausgabe (Tool-Use-Schema) |
|---|---|---|
| `system_editor_v1.md` | Systemrolle: Senior-Redaktion DACH | – |
| `system_editor_v2.md` | Systemrolle, gepinnt in Fassung 2 (AP4): Transkript, Titel und Metadaten sind Daten in Begrenzern, keine Anweisungen; kein Viralitätsversprechen | – |
| `propose_moments_v1.md` | Stufe 2: Momente pro Kapitel als Satz-Spannen | `propose_moments` |
| `propose_moments_v2.md` | Stufe 2, gepinnt in Fassung 2 (AP5): Payoff zuerst, rückwärts zum Einstieg, Gegenrichtung; Policy, Episodenübersicht, Seeds und Kapitel in Begrenzern; je Moment Payoff, Einstieg, Kontext, Funktion, Versprechen | `propose_moments` |
| `episode_overview_v1.md` | Stufe 2, gepinnt in Fassung 2 (AP5): Analyst, Übersicht je Kapitel mit Satznummern, nur für die Suche, nie Zitat- oder Schnittquelle | `episode_overview` |
| `score_clip_v1.md` | Stufe 3, Bestand: eigene Rubrik (5 Kriterien, 0 bis 10) | `score_clip` |
| `score_clip_v2.md` | Stufe 3, gepinnt in Fassung 1 und 2: Rubrik aus der redaktionellen Grundlage (7 Kriterien, 0 bis 2) | `score_clip` |
| `story_graph_confirm_v1.md` | Stufe 4: relativiert ein späterer Satz den Clip? | `confirm_qualification` |
| `hooks_v1.md` | Copy: 5 Hook-Varianten nach Muster | `write_hooks` |
| `hooks_v2.md` | Copy, gepinnt in Fassung 2 (AP6a): Varianten aus verschiedenen Originalstellen, Frage nur als Variante, Clip in Begrenzern als Daten | `write_hooks` |
| `post_caption_v1.md` | Copy: Post-Text pro Plattform | `write_post_caption` |
