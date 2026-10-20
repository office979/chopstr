# 022: Paarvergleich mit Bradley-Terry über das ganze Video (Hypothese)

Stand 20.10.2026, Lane P2 (Launch Phase 2, Momentfindung). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 3
Nr. 3, Abschnitt 4 und Abschnitt 8 Phase 2; Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 8.

**Dies ist eine Hypothese.** Der Positionsbias wird gemessen, nicht angenommen. Übernommen wird der Paarvergleich
erst mit Nachweis gegen die Baseline (Rangfolge nach `total`), gemessen als Precision@5 gegen Redakteurs-Top-10 und
Abdeckung nach dem Ranking im Trichter (`report.funnel.offered`), mit geprüften Regressionen.

**Problem.** Je Kapitel bewertet ein Modellaufruf jede Spanne absolut; über Kapitel hinweg wird nur nach `total`
sortiert (`select_with_reserve`). Absolute Scores verschiedener Aufrufe sind nicht kalibriert, ein Kandidat aus
einem starken Kapitel kann gegen einen aus einem schwachen verlieren, ohne dass beide je nebeneinander standen.

**Alternativen.** (a) Rangfolge nach `total` wie heute. (b) Paarvergleich der Top-N mit Positionsrotation und
Bradley-Terry. (c) Listenweises Ranking in einem Aufruf (Positions- und Längenbias schwer messbar). (d)
Mehrfach-Sampling der absoluten Scores (teurer, löst die fehlende Gegenüberstellung nicht). (e) Logistische
Regression der Gewichte (braucht Redakteursurteile, die fehlen).

**Evidenz.** `workers/tests/test_launch_p2_pairwise.py`: Bradley-Terry (eigene MM-Iteration nach Hunter 2004)
reproduziert eine bekannte Stärkeordnung aus verrauschten Siegen; ein Modell, das immer „A“ sagt, ergibt lauter
`inconsistent` und `a_share` 1,0 und ändert die Rangfolge nicht; ein knappes Budget lässt die Rangfolge nach
`total`; ohne Regel bleibt alles wie heute. Literatur: Paarvergleiche mit Sprachmodellen zeigen Positionsbias
(arxiv.org/abs/2406.07791). Eine Messung an echtem Material mit Redakteursurteil gibt es nicht.

**Unsicherheit.** Ob paarweise Urteile eines Modells besser mit Redakteuren übereinstimmen als absolute, ist offen.
Kosten: `top_n` 8 ergibt 28 Paare und 56 Aufrufe je Quelle; die Budgetrechnung der Policy (387 von 400 je
Quellstunde) hat dafür keinen Platz; nach dieser Rechnung bliebe der Vergleich bei einer einstündigen Quelle unvollständig und würde nicht angewandt. Die Heuristik
antwortet aus Rubrikpunkten und Markern und ist unkalibriert; ihre Rangfolge belegt nichts.

**Entscheidung.** (b) gebaut hinter Schalter `implementation.ranking.pairwise` (an) und Regel
`ranking.pairwise.enabled` (Standard aus), `ranking.pairwise.top_n` 8. Prompt `compare_clips_v1` (Fassung 2
gepinnt, wirksam nur mit der Regel). Jedes Paar läuft als A/B und B/A; widersprechen sich die Urteile, zählt es
als `inconsistent` und geht als Unentschieden ein. Ergebnis `rubric.pairwise_rank`, `pairwise_strength`,
`pairwise_applied`, Bericht `report.ranking` mit Positionsanteil, Widerspruchsquote und allen Urteilen. Die Auswahl
nutzt den Rang nur, wenn jedes Paar in beiden Reihenfolgen gültig beantwortet wurde.

**Konsequenzen.** Vor dem Einschalten muss die Budgetrechnung um die Vergleiche erweitert oder `top_n` gesenkt
werden. Die Abnahme braucht einen Blindvergleich mit Redakteurs-Top-10 (Gate 2) und den gemessenen
Positionsanteil; liegt `a_share` weit von 0,5 oder die Widerspruchsquote hoch, wird verworfen. Rollback: Regel false.

**Produkt.** Der Kunde sieht zehn Vorschläge; welcher oben steht, entscheidet über die erste Freigabe. Ein
Vergleich über das ganze Video kann die besten Momente nach vorn holen, kostet aber Modellaufrufe und Laufzeit.
Ohne Nachweis bleibt die heutige Rangfolge.

**Redaktion.** Redakteure vergleichen Clips nebeneinander, nicht auf einer absoluten Skala; der Paarvergleich
bildet das nach. Das Urteil bleibt an die sieben Kriterien der Grundlage gebunden und sagt nichts über Reichweite.
Ein Kandidat, der ein Gate reißt, wird nie verglichen.

**Engineering.** Eigene Implementierung ohne Abhängigkeit, deterministisch (feste Paarreihenfolge, feste
Abbruchgrenzen, Gleichstand nach bisheriger Rangfolge). Jeder Vergleich zählt im `BudgetLLM`; verweigerte oder
ungültige Antworten verhindern die Anwendung, statt einen halben Rang zu erzeugen. Fassung 1 bleibt byte-gleich.
