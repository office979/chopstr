# 030: Claim-Index über das ganze Video

Stand 20.10.2026, Lane P3 (Launch Phase 3, Kontexttreue). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 8
Phase 3 und Regeln 2 und 12; Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 8.

**Problem.** Der Story-Graph sucht eine spätere Einschränkung nur im Fenster von 60 s nach dem Clip
(`story_graph.LOOKAHEAD_S`). Er erkennt nur Kontrast- und Korrekturmarker und kennt keinen Sprecherbezug. Eine
Relativierung zehn Minuten später, eine stille Korrektur mit anderer Zahl („es waren eigentlich 30“) oder ein
Widerspruch des Gegenübers bleiben unsichtbar. Das Gate `later_correction` erbt diese Grenze.

**Alternativen.** (a) Das Fenster von 60 s nur vergrößern. (b) Embeddings über alle Sätze, was ein neues Modell
und eine neue Abhängigkeit braucht. (c) Ein deterministischer Index aller Sätze mit Zahl, Verneinung, Bedingung,
Einschränkung, Zeitbezug oder Zuschreibung, Suche über Lemma-Jaccard, gleiche Zahl oder gleichen Namen,
Einordnung mit Sprecherbezug. (d) Die ganze Quelle an das Modell geben, was Budget und Kontextlänge sprengt.

**Evidenz.** Synthetische Fälle in `workers/tests/test_launch_p3_claim_index.py`. Gefunden werden eine
Relativierung gut zehn Minuten später, eine Eigenkorrektur mit anderer Zahl nach drei Minuten und ein Widerspruch
des anderen Sprechers. Ein unverwandter Satz mit gleicher Zahl bleibt `unrelated`, eine Wiederholung derselben
Aussage `addition`. Echtes Langmaterial mit annotierten Bezügen gibt es nicht. Eine Trefferquote ist deshalb
nicht gemessen.

**Unsicherheit.** Die Wortlisten und die Schwellen `max_hits` 5 und `min_overlap` 0,2 sind Startwerte ohne
Messung (Herkunft H). Lemma-Jaccard ohne spaCy vergleicht Wortstämme, und Umschreibungen ohne gemeinsame Wörter
bleiben unentdeckt. Ein nicht gefundener Bezug ist kein Beleg, dass keiner existiert (Regel 12). Das steht als
`note` in jedem Bericht.

**Entscheidung.** (c), hinter Schalter `implementation.context.claim_index` (gebaut, an) und Regel
`context.claim_index.enabled` (aus). Die Reaktion hängt von der Klasse ab:

- Eine Eigenkorrektur mit Korrekturmarker, anderer Zahl oder umgekehrter Verneinung trifft das bestehende Gate
  `later_correction`. In Reichweite setzt sie `heal_to_sentence_idx`, sonst bleibt der Treffer unheilbar.
- Eine Relativierung desselben Sprechers geht als Prüfgrund in den Story-Graph und wird dort per Modell bestätigt.
- Eine Ergänzung ist nur ein Hinweis.
- Ein Widerspruch eines anderen Sprechers setzt das Flag `debate_contradiction` mit Belegstelle und verwirft
  nicht.

**Konsequenzen.**

- *Produkt:* Kandidaten mit einer späteren Relativierung oder einem Widerspruch erscheinen als unsicher, mit
  der Quellstelle. Der Mensch sieht, wo er nachhören muss. Weniger Clips werden automatisch angenommen.
- *Redaktion:* Die Quellstelle steht in `rubric.context_hits` und in `review_state.reasons`. Ein unheilbarer
  Treffer wird nur berichtet, solange die Regel `gates.discard_hard` aus ist.
- *Engineering:* Eingeschaltet kostet der Index je Kandidat einen Durchlauf über alle Sätze; die Lemmata sind
  zwischengespeichert. Dazu kommt je zusätzlichem Story-Graph-Treffer ein Bestätigungsaufruf im Modellbudget
  (P41), höchstens `max_hits` je Kandidat. Ein unheilbarer Treffer verhindert in `heal_gates` die Heilung anderer
  Gates desselben Kandidaten. Einschalten erst nach einem Lauf an echtem Material mit Stichprobe der Treffer je
  Klasse.
