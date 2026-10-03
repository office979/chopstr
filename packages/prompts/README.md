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

## Prompts, Pins und Rollen

Stand: Code-Stand 8054125. „Pin F1“ und „Pin F2“ sagen, ob die Policy-Fassung 1 (`editorial.V1_PROMPT_PINS`) oder die Fassung 2 (Abschnitt `prompts` in `clip_policy_v2.yaml`) die Datei lädt. Nur eine gepinnte Datei läuft; eine Datei ohne Pin in beiden Spalten bleibt Bestand. Rolle ist die Aufgabe im Ablauf (Analyst beschreibt, Editor wählt, Kritiker sucht Gegenbeweise, Copy schreibt Text, Bewerter vergibt Punkte, Prüfer entscheidet eine Einzelfrage, System ist die gemeinsame Rahmung). Eingaben sind die Platzhalter im Frontmatter (`inputs`); `prompts.render` scheitert, wenn einer fehlt.

| Datei | Pin F1 | Pin F2 | Rolle | Eingaben | Ausgabe (Tool-Use-Schema) | Zweck |
|---|---|---|---|---|---|---|
| `system_editor_v1.md` | ja | nein | System | keine | nichts | Systemrolle: Senior-Redaktion DACH |
| `system_editor_v2.md` | nein | ja | System | keine | nichts | Systemrolle ab AP4: Transkript, Titel und Metadaten sind Daten in Begrenzern, keine Anweisungen; kein Viralitätsversprechen |
| `episode_overview_v1.md` | nein | ja | Analyst | `chapter_numbered` | `episode_overview` | Stufe 2 (AP5): Übersicht je Kapitel mit Satznummern, nur für die Suche, nie Zitat- oder Schnittquelle. Unter Fassung 1 nicht gepinnt, ein Aufruf scheitert dort laut |
| `propose_moments_v1.md` | ja | nein | Editor (Rolle erst ab v2 im Frontmatter) | `audience`, `wanted`, `exclude`, `platform`, `chapter_numbered` | `propose_moments` | Stufe 2: Momente pro Kapitel als Satz-Spannen |
| `propose_moments_v2.md` | nein | ja, wirksam nur mit `implementation.search.payoff_first` | Editor | `audience`, `wanted`, `exclude`, `platform`, `policy`, `episode_overview`, `seeds`, `chapter_numbered` | `propose_moments` | Stufe 2 (AP5): Payoff zuerst, rückwärts zum Einstieg, Gegenrichtung; Policy, Episodenübersicht, Seeds und Kapitel in Begrenzern; je Moment Payoff, Einstieg, Kontext, Funktion, Versprechen |
| `score_clip_v1.md` | nein | nein | Bewerter | `audience`, `platform`, `candidate_numbered` | `score_clip` | Bestand: eigene Rubrik (5 Kriterien, 0 bis 10), wird von keiner Fassung geladen |
| `score_clip_v2.md` | ja | ja | Bewerter | `audience`, `platform`, `candidate_numbered`, `policy` | `score_clip` | Stufe 3: Rubrik aus der redaktionellen Grundlage (7 Kriterien, 0 bis 2); `{policy}` wird aus der aktiven Fassung gefüllt, der Kopf `policy: clip_policy_v1` ist nur eine Anzeige |
| `story_graph_confirm_v1.md` | ja | ja | Prüfer | `clip_text`, `later_text`, `seconds_after` | `confirm_qualification` | Stufe 4: relativiert ein späterer Satz den Clip? |
| `hooks_v1.md` | ja | nein | Copy | `address`, `country`, `platform`, `protected_terms`, `clip_text` | `write_hooks` | 5 Hook-Varianten nach Muster |
| `hooks_v2.md` | nein | ja | Copy | `address`, `country`, `platform`, `protected_terms`, `clip_text` | `write_hooks` | ab AP6a: Varianten aus verschiedenen Originalstellen, Frage nur als Variante, Clip in Begrenzern als Daten. Rollback gemeinsam mit dem Schalter `implementation.hook.native_spoken` |
| `post_caption_v1.md` | ja | ja | Copy | `address`, `country`, `platform`, `tone_adjectives`, `banned_phrases`, `clip_text`, `hook_onscreen` | `write_post_caption` | Post-Text pro Plattform |

Geplant, im Stand 8054125 nicht vorhanden: `critique_clip_v1.md` (Rolle Kritiker, AP6b; Eingaben `opening`, `text_hook`, `clip_text`, `context_before`, `context_after`; Tool `critique_clip`; nur für die Überlebenden der Auswahl, Pin in Fassung 2 mit dem Paket, Beschluss P42 in `docs/ENTSCHEIDUNGEN.md`). Der Evaluator des Rollenmodells ist kein Prompt, sondern deterministisch (Gates und Teilwerte). Wo welcher Prompt geladen wird und welche Version im Kandidaten, im Cache-Key und in `hook_versions` steht, beschreibt `docs/PIPELINE.md` Abschnitt 6.
