# 020: Kapitel an Themenwechseln statt fester 240 Sekunden

Stand 20.10.2026, Lane P2 (Launch Phase 2, Momentfindung). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 3
Nr. 4 und Abschnitt 8 Phase 2; Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 8.

**Problem.** `segment.chapterize` schließt ein Kapitel, sobald es 240 s erreicht (`story_engine.CHAPTER_SECONDS`);
unter Fassung 2 mit Suche beginnt jedes folgende Kapitel zusätzlich mit den letzten 30 s des vorigen. Eine
Themenerkennung gibt es nicht. Ein Argument, das bei 3:50 beginnt, wird zerschnitten oder nur über die
Überlappung gerettet; ein Thema von 4:30 Länge landet in zwei Kapiteln mit je eigener Übersicht.

**Alternativen.** (a) Feste Kapitel lassen und nur die Überlappung vergrößern. (b) TextTiling-artige Grenzen aus
der Wortüberlappung benachbarter Zeitfenster, ohne Embeddings, plus Sprecherwechsel. (c) Embedding-Segmentierung
(neue Abhängigkeit, Modell im Image, nicht deterministisch über Versionen). (d) Kapitelgrenzen vom Sprachmodell
(Kosten je Quelle, Prompt-Injektion aus dem Transkript, nicht reproduzierbar mit der Heuristik).

**Evidenz.** Synthetische Transkripte in `workers/tests/test_launch_p2_chapters.py`: Themenwechsel nach 150 s wird
genau getroffen (feste Kapitel schneiden bei Satz 24 mitten ins zweite Thema), ein durchgehendes Thema von 280 s
bleibt ein Kapitel (fest: zwei), ein Einschub von 20 s erzeugt kein Kapitel, die Obergrenze erzwingt einen
Schnitt und meldet ihn als `max_length`. Echtes Langmaterial mit Redakteursgrenzen gibt es im Repo nicht.

**Unsicherheit.** Die Wortüberlappung kennt keine Synonyme und keine Lemmata (Endungskürzung wie
`story_graph._stem`); in echten Gesprächen mit wechselndem Vokabular kann die relative Tiefe rauschen. Die
Schwelle 0,5, das Fenster 60 s, Mindest- und Höchstlänge 120 und 300 s sowie das Sprechergewicht 0,25 sind
Startwerte (origin H). Ob bessere Kapitel bessere Clips ergeben, ist nicht gemessen.

**Entscheidung.** (b) hinter Schalter `implementation.chapters.topic_shift` (gebaut, an) und Regel
`chapters.topic_shift.enabled` (Standard aus). `segment.topic_boundary_scores` bewertet jede Lücke,
`segment.chapterize_topic_shift` wählt im Bereich zwischen `min_s` und `max_s` ab Kapitelbeginn die beste Lücke,
wenn sie `min_boundary_score` erreicht, sonst schneidet es erst, wenn der Rest länger als `max_s` ist. Die
Überlappung `search.chapter_overlap_s` bleibt. Jedes Kapitel trägt `topic_boundary_score` und `boundary`
(`start`, `topic_shift`, `max_length`) in `report.chapter_meta`.

**Konsequenzen.** Mit der Regel ändern sich Kapitelzahl, Kapitelreihenfolge nach Seeds, Übersichten und damit der
Kandidaten-Key (Policy-Hash). Das Modellbudget rechnet weiter je Quellstunde; bei Kapiteln zwischen 120 und 300 s
liegt die Kapitelzahl in derselben Größenordnung wie heute. Rollback: Regel auf false.

**Produkt.** Ein Kapitel, das einem Thema folgt, lässt ein Argument nicht an einer Uhrzeitgrenze zerfallen; das
ist für Gesprächsformate (Interview, Podcast) die häufigste Form eines guten Clips. Sichtbar wird es für den
Kunden nicht direkt, nur über weniger zerschnittene Kandidaten. Eingeschaltet wird erst nach einem Vergleich mit
Abdeckung im Pool (Trichter, `report.funnel`) gegen die feste Kapitelung.

**Redaktion.** Ein kurzer Einschub (Anekdote, Rückfrage) bleibt Teil seines Themas; ein Thema bis fünf Minuten
bleibt ganz. Die Grenze ist eine Vermutung aus Wortwiederholung, kein inhaltliches Urteil; ein Thema, das mit
anderen Wörtern weitergeführt wird, kann fälschlich geteilt werden. Die Überlappung bleibt deshalb bestehen.

**Engineering.** Deterministisch, ohne neue Abhängigkeit, ohne Modellaufruf, linear in der Satzzahl. Keine
Mengeniteration über Zeichenketten im Ergebnis (geprüft mit zwei Prozessen und verschiedenem `PYTHONHASHSEED`,
`tests/test_launch_p2_repro.py`). Fassung 1 bleibt byte-gleich, weil der Leser `story_engine.topic_shift_settings`
dort `None` liefert.
