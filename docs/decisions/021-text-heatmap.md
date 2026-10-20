# 021: Text-Heatmap v2, z-normiert neben der Audio-Heatmap

Stand 20.10.2026, Lane P2 (Launch Phase 2, Momentfindung). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 3
Nr. 5 und Abschnitt 8 Phase 2; Widerspruch B (Lachen) in Abschnitt 4.

**Problem.** `signals.combined` mischt 0,5 Audio (RMS und Spectral Flux als z-Wert, begrenzt auf -3 bis 3) mit 0,5
rohen Textzählern (1,0 je Diskursmarker über 20 s, 0,5 je Frage über 15 s, 0,5 je Zahl). Die Skalen passen nicht
zusammen; die Marker greifen auf wenigen Sätzen (Inventur: 2,4 bis 6,2 Prozent), Lachen wird nie berechnet
(`laughter_values` leer). Ein ruhig vorgetragenes Kernargument mit Zahl und Einsatz bekommt keinen Seed, sobald
irgendwo jemand lauter wird, und wird nur gefunden, wenn das Modell das Kapitel ohnehin liest.

**Alternativen.** (a) So lassen. (b) Mehr Textmerkmale und den Textanteil z-normieren wie den Audioanteil, Mischung
als Policy-Wert. (c) Ein Klassifikator für „interessante Stelle“ (keine Trainingsdaten, keine Referenz). (d) Die
Heatmap im Activity neu speichern (Datei der Lane P3, Heatmap-Key ohne Textversion).

**Evidenz.** `workers/tests/test_launch_p2_heat.py`: in einem Gespräch mit lauter Begrüßung (Audio z 2,0) liegt
der stärkste Seed heute an der Begrüßung, mit v2 im ruhigen Kernargument („in drei Monaten 40.000 Euro verloren“,
„Risiko existenziell“, „Kredit“). Reaktionen zählen nur als kurzer Einwurf eines anderen Sprechers, Zahlen nur
mit Einheit, Lachen nur mit Daten. Echtes Material mit Redakteurs-Seeds fehlt.

**Unsicherheit.** Alle Wortlisten (`heat.markers.*`, `heat.units`) und die Mischung 0,5 sind
Übertragungshypothesen ohne Messung. Ein häufiges Wort („Kosten“, „echt“) kann flache Gespräche anheben; die
z-Normierung macht den Textanteil zwar vergleichbar, verstärkt aber auch kleine Unterschiede in textarmen Quellen.
Ob Seeds die Abdeckung im Pool erhöhen, ist offen; heute ordnen sie Kapitel und stehen im Vorschlags-Prompt.

**Entscheidung.** (b) hinter Schalter `implementation.heat.text_v2` (gebaut, an) und Regel `heat.text_v2`
(Standard aus), Mischung `heat.text_weight` 0,5. `story_engine.run` mischt die gespeicherte Heatmap aus
`audio_values` und der Wortliste neu (`signals.payload_with_text_v2`), die gespeicherte Datei bleibt unverändert.
Bericht in `report.heat` (Treffer je Merkmal, Gewicht, ob Audio und Lachen vorlagen). (d) bleibt für Lane P3:
`signals.combined_v2` steht bereit, wenn `run_heatmap` die Mischung beim Speichern übernehmen soll.

**Konsequenzen.** Mit der Regel ändern sich Seeds, Kapitelreihenfolge und Seed-Zeilen im Vorschlags-Prompt; der
Kandidaten-Key ändert sich über den Policy-Hash. `audio_wert` und die Teaser-Wahl lesen weiter nur den
Audioanteil. Lachen bleibt `not_implemented`, bis eine Erkennung Daten liefert.

**Produkt.** Gerade Fachgespräche (B2B, Beratung) tragen ihre stärksten Aussagen ruhig vor; eine laute Stelle ist
kein Qualitätsmerkmal. Die Änderung verspricht keine bessere Reichweite und wird nur übernommen, wenn die
Abdeckung im Pool gegen die heutige Heatmap steigt.

**Redaktion.** Einsatz, Zahl mit Einheit, überraschende Wendung und Reaktion des Gegenübers sind die Merkmale, die
Redakteure beim Durchhören markieren. Die Heatmap entscheidet nichts: sie ordnet Kapitel und gibt dem Modell
Hinweise; Verwerfen und Bewerten bleiben bei Gates und Rubrik. Humor bleibt beim Menschen (Regel 11).

**Engineering.** Deterministisch, numpy wie bisher, keine neue Abhängigkeit. Der Heatmap-Key in `analyze.py`
kennt die Textversion nicht; solange die Neuberechnung in der Engine passiert, ist das unschädlich, weil der
Policy-Hash im Kandidaten-Key steckt. Fassung 1 bleibt byte-gleich (`signals.text_heat_settings` liefert `None`).
