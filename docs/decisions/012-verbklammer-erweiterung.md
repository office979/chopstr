# 012: Verbklammer-Erweiterung (zu-Infinitiv, Korrelate, Partikel ohne Satzzeichen)

Stand 20.10.2026, Lane P1. Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Regel 1 und Phase 1 („Verbklammer-Erweiterung
… Unit-Tests je Konstruktion mit zulässigen Gegenbeispielen“).

**Problem.** Regel 1 verbietet Schnitte in der Verbklammer, in trennbaren Verben, in Korrelaten und zwischen
Nebensatz-Einleitung und Verb. Die Heuristik ohne spaCy (`dach_nlp.bracket_heuristic`) kannte drei Signale:
Partikel nur mit Satzzeichen danach („an.“), Nebensatz ohne Verb, Hilfs- oder Modalverb ohne Partizip oder
Infinitiv. Es fehlten zu-Infinitive („um mehr | zu investieren“, „Wir haben beschlossen | das Projekt zu
stoppen“), Korrelate („zwar … | aber“, „entweder … oder“, „nicht nur … sondern“, „weder … noch“, „je … desto“,
„sowohl … als auch“) und Partikeln ohne Satzzeichen, wie sie Whisper oft liefert („Wir fangen morgen | an und …“).

**Alternativen.** (a) `SUBORDINATORS` um „um, ohne, statt, anstatt“ ergänzen. (b) Eine eigene Liste
`INFINITIVE_INTRODUCERS`, die nur zusammen mit einem folgenden zu-Infinitiv zählt. (c) Nur spaCy.
(d) Die Erweiterung als `rule = "v2"` an `bracket_heuristic` und `forbidden_cut_ranges`, Standard unverändert.

**Evidenz.** `SUBORDINATORS` speist die Satzgrenzen (`PAUSE_OPEN_END_WORDS`, `_comma_boundary`) und ist in
`apps/web/lib/transcript/sentences.ts` gespiegelt (Parität P5, Falldatei `sentence_end_v1.json`). (a) hätte die
Satzzerlegung in Worker und Web geändert und „um 8 Uhr“ als offenen Nebensatz gewertet. spaCy ist im Image (P50),
aber lokal nicht installiert; der Rückfall entscheidet im Entwicklungsweg. 20 Tests mit Gegenbeispielen in
`tests/test_launch_p1_verb_bracket.py`, alle Fälle konstruiert, kein echtes Material gemessen.

**Unsicherheit.** Die Listen sind ohne Messung. „nicht nur … auch“ ohne „sondern“ wird als geschlossen gewertet;
„je“ zählt nur vor einem Komparativ (Wort auf -er, „mehr“); ein Korrelat über zwei Sätze erkennt der Schnittcheck
nicht, nur `open_correlates` über die Clip-Spanne. Adjektive auf -en nach „zu“ („zu offen“) sind nur als kleine
Liste ausgenommen.

**Entscheidung.** (b) und (d). `bracket_heuristic(..., rule="v2")` prüft nach den drei alten Signalen zusätzlich
`bracket_extensions`: zu-Infinitiv im selben Teilsatz rechts (mit Einleitung links im Detail genannt), Schnitt
zwischen „zu“ und Infinitiv, Korrelat ohne zweiten Teil links, Partikel aus `SEPARABLE_PARTICLES_V2`, wenn danach
der Text endet oder ein neuer Teilsatz beginnt. `forbidden_cut_ranges(..., rule="v2")` liefert zusätzlich die
Bereiche von der Einleitung bis zum Infinitiv und vom ersten bis zum zweiten Korrelatteil, auch ohne spaCy.
`open_correlates(words)` prüft eine Clip-Spanne. `SUBORDINATORS` bleibt unverändert, `SUBORDINATORS_V2` ist die
erweiterte Liste.

**Konsequenzen.** Ohne `rule` verhält sich alles wie vorher; die Satzgrenzen, der Web-Port und Fassung 1 sind
unberührt. Wirksam wird die Erweiterung erst, wenn der Aufrufer sie anfordert: das Verbklammer-Tor ruft
`dach_nlp.bracket_open_at_cut` (`story_engine._verb_bracket_gate`), und diese Funktion reicht `rule` nicht weiter.
Die Verdrahtung (eine Zeile in `bracket_open_at_cut`: `rule="v2"` an `bracket_heuristic` und
`forbidden_cut_ranges` unter Fassung 2, plus `open_correlates` über die Spanne im Tor) liegt außerhalb dieser Lane.
Unter Fassung 1 prüft das Tor weiterhin nur innerhalb des ersten und letzten Satzes (`_verb_bracket_gate_v1`).

**Perspektive Produkt.** Ein Clip, der mit „zwar ist das teuer“ endet oder „um mehr“ abbricht, kehrt die Aussage
um oder lässt sie hängen. Das ist genau der Fehler, den Redakteure sofort sehen und der Vertrauen kostet.

**Perspektive Redaktion.** Die Gegenbeispiele sind so gewählt, dass gute Schnitte durchgehen: „um 8 Uhr“,
„ohne Zucker“, „zu meinen Eltern“, „und zwar“, „je Person“, „an der Kasse“, „mit dem Auto“. Eine offene Klammer ist
ein Prüfgrund mit Detail („„zwar“ ohne „aber“ vor dem Schnitt“), keine stille Ablehnung.

**Perspektive Engineering.** Die Erweiterung ist eine reine Funktion ohne Modell, deterministisch und unter
einem Parameter mit altem Standard. Die Listen sind Konstanten in `dach_nlp`; wenn sie in die Policy wandern,
gehören sie zu `verb_bracket` und brauchen Herkunft. Nicht messbar: Rate falscher Treffer an echtem Material.
