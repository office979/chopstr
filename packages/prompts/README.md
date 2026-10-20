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

Stand: 20.10.2026, Code-Stand 6c9f29f plus Arbeitsbaum der Launch-Lanes P2 und P3 (`compare_clips_v1`, `counter_reader_v1`). „Pin F1“ und „Pin F2“ sagen, ob die Policy-Fassung 1 (`editorial.V1_PROMPT_PINS`) oder die Fassung 2 (Abschnitt `prompts` in `clip_policy_v2.yaml`) die Datei lädt. Nur eine gepinnte Datei läuft; eine Datei ohne Pin in beiden Spalten bleibt Bestand. Rolle ist die Aufgabe im Ablauf (Analyst beschreibt, Editor wählt, Kritiker sucht Gegenbeweise, Gegenleser vergleicht den Text-Hook mit dem Clip, Copy schreibt Text, Bewerter vergibt Punkte oder entscheidet ein Paar, Prüfer entscheidet eine Einzelfrage, System ist die gemeinsame Rahmung). Eingaben sind die Platzhalter im Frontmatter (`inputs`); `prompts.render` scheitert, wenn einer fehlt.

| Datei | Pin F1 | Pin F2 | Rolle | Eingaben | Ausgabe (Tool-Use-Schema) | Zweck |
|---|---|---|---|---|---|---|
| `system_editor_v1.md` | ja | nein | System | keine | nichts | Systemrolle: Senior-Redaktion DACH |
| `system_editor_v2.md` | nein | ja | System | keine | nichts | Systemrolle ab AP4: Transkript, Titel und Metadaten sind Daten in Begrenzern, keine Anweisungen; kein Viralitätsversprechen |
| `episode_overview_v1.md` | nein | ja | Analyst | `chapter_numbered` | `episode_overview` | Stufe 2 (AP5): Übersicht je Kapitel mit Satznummern, nur für die Suche, nie Zitat- oder Schnittquelle. Unter Fassung 1 nicht gepinnt, ein Aufruf scheitert dort laut |
| `propose_moments_v1.md` | ja | nein | Editor (Rolle erst ab v2 im Frontmatter) | `audience`, `wanted`, `exclude`, `platform`, `chapter_numbered` | `propose_moments` | Stufe 2: Momente pro Kapitel als Satz-Spannen |
| `propose_moments_v2.md` | nein | ja, wirksam nur mit `implementation.search.payoff_first` | Editor | `audience`, `wanted`, `exclude`, `platform`, `policy`, `episode_overview`, `seeds`, `chapter_numbered` | `propose_moments` | Stufe 2 (AP5): Payoff zuerst, rückwärts zum Einstieg, Gegenrichtung; Policy, Episodenübersicht, Seeds und Kapitel in Begrenzern; je Moment Payoff, Einstieg, Kontext, Funktion, Versprechen |
| `score_clip_v1.md` | nein | nein | Bewerter | `audience`, `platform`, `candidate_numbered` | `score_clip` | Bestand: eigene Rubrik (5 Kriterien, 0 bis 10), wird von keiner Fassung geladen |
| `score_clip_v2.md` | ja | nein | Bewerter | `audience`, `platform`, `candidate_numbered`, `policy` | `score_clip` | Stufe 3: Rubrik aus der redaktionellen Grundlage (7 Kriterien, 0 bis 2); `{policy}` wird aus der aktiven Fassung gefüllt, der Kopf `policy: clip_policy_v1` ist nur eine Anzeige |
| `score_clip_v3.md` | nein | ja | Bewerter | `audience`, `platform`, `candidate_numbered`, `policy` | `score_clip` | Stufe 3 ab AP9: die sieben Rubrikkriterien wie v2 (0 bis 2, je mit `<schluessel>_evidence`) und zusätzlich `editorial_subscores`, sieben Teilwerte mit Anker 0 bis 4 (`audience_relevance`, `opening_clarity`, `content_strength`, `progress`, `evidence_quality`, `closing`, `naturalness`); ab 1 braucht ein Teilwert ein wörtliches Zitat, das gegen den Kandidatentext geprüft wird, sonst gilt er nicht. Der Kandidat steht zwischen `<clip>`-Begrenzern als Daten. Die Eigenständigkeit gegenüber anderen Kandidaten (`distinctiveness_vs_others`) bewertet das Modell nicht, sie rechnet `story_engine.select_with_reserve`. Der Kopf `policy: clip_policy_v2` ist nur eine Anzeige |
| `story_graph_confirm_v1.md` | ja | ja | Prüfer | `clip_text`, `later_text`, `seconds_after` | `confirm_qualification` | Stufe 4: relativiert ein späterer Satz den Clip? |
| `critique_clip_v1.md` | nein | ja | Kritiker | `opening`, `text_hook`, `clip_text`, `context_before`, `context_after` | `critique_clip` | Nach der Auswahl (AP6b, P42): sucht gezielt sechs Arten verlorenen Kontexts (`hook_contradicted`, `claim_contradicted`, `unclear_pronoun`, `removed_condition`, `false_transition`, `reported_position`) mit Schwere `fidelity`, `clarity` oder `minor`; jeder Befund braucht ein wörtliches Zitat, das gegen Clip und Kontext geprüft wird. Wählt nichts aus, schneidet nichts, schreibt keinen Hook. Verwerfen darf nur ein bestätigter Befund der Schwere `fidelity` (`pipeline/critic.py`). Wirksam nur mit Regel und Schalter `roles.critic` |
| `compare_clips_v1.md` | nein | ja, wirksam nur mit Regel `ranking.pairwise.enabled` und Schalter `implementation.ranking.pairwise` (beide Standard: Regel aus) | Bewerter im Paarvergleich (Frontmatter `role: evaluator`) | `audience`, `platform`, `policy`, `clip_a`, `clip_b` | `compare_clips`: `winner` (`A`, `B` oder `tie`), `criteria` (je eines der sieben Kriterien der Grundlage `A`, `B` oder `tie`), `reason` (ein Satz mit dem entscheidenden Unterschied), `heuristic`; Pflicht sind `winner` und `reason` | Launch Phase 2 (Lane P2, Hypothese): vergleicht zwei Kandidaten derselben Quelle nach den sieben Kriterien der Grundlage. Beide stehen zwischen `<clip_a>` und `<clip_b>` als Daten; Länge allein und die Reihenfolge zählen nicht, bei Gleichstand `tie`. Der Aufrufer stellt jedes Paar in beiden Reihenfolgen und rechnet Bradley-Terry (`story_engine.rank_pairwise`, `story_score.compare`, `docs/PIPELINE.md` 1.9a). Das Frontmatter trägt `policy: clip_policy_v2` und den Platzhalter `{policy}` |
| `counter_reader_v1.md` | nein | ja, wirksam nur mit Regel `context.counter_reader.model` (Standard aus) und laufendem Kritiker (`roles.critic`) | Gegenleser (Frontmatter `role: counter_reader`) | `clip_text`, `text_hook` | `counter_reader`: `findings[]` mit `dimension` (`attribution`, `negation`, `certainty`, `condition`, `number`, `time`), `verdict` (`same` oder `differs`), `clip_quote`, `hook_quote`, `severity` (`high` oder `low`), `explanation`; dazu `confirmed`; Pflicht sind `findings` und `confirmed` | Launch Phase 3 (Lane P3): sieht nur den Clip und den Text-Hook, wählt nichts aus und schreibt keinen Hook. Bei `differs` braucht der Befund zwei wörtliche Zitate, die gegen Clip und Hook geprüft werden (`critic.check_counter_findings`), sonst gilt er nicht; `confirmed` zählt nur mit mindestens einem belegten Befund `high`. Verdichten und Gewichten ist erlaubt. Verwerfen darf nur ein bestätigter Befund des ersten Modells, nie die Heuristik; ein zweites Modell (`LLM_PROVIDER_SECOND`) läuft mit demselben Prompt nur zur Messung (`critic.counter_read_model`, `docs/PIPELINE.md` 1.10a). Der Clip steht zwischen `<clip>`-Begrenzern als Daten |
| `hooks_v1.md` | ja | nein | Copy | `address`, `country`, `platform`, `protected_terms`, `clip_text` | `write_hooks` | 5 Hook-Varianten nach Muster |
| `hooks_v2.md` | nein | ja | Copy | `address`, `country`, `platform`, `protected_terms`, `clip_text` | `write_hooks` | ab AP6a: Varianten aus verschiedenen Originalstellen, Frage nur als Variante, Clip in Begrenzern als Daten. Rollback gemeinsam mit dem Schalter `implementation.hook.native_spoken` |
| `post_caption_v1.md` | ja | ja | Copy | `address`, `country`, `platform`, `tone_adjectives`, `banned_phrases`, `clip_text`, `hook_onscreen` | `write_post_caption` | Post-Text pro Plattform |

Der Evaluator des Rollenmodells ist kein Prompt, sondern deterministisch (Gates und Teilwerte). Wo welcher Prompt geladen wird und welche Version im Kandidaten, im Cache-Key und in `hook_versions` steht, beschreibt `docs/PIPELINE.md` Abschnitt 6.
