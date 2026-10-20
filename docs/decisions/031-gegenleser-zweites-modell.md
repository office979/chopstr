# 031: Gegenleser nach sechs Dimensionen, zweites Modell nur gemessen

Stand 20.10.2026, Lane P3 (Launch Phase 3, Kontexttreue). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 8
Phase 3 und Regeln 2 und 6; Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitte 3 und 8.

**Problem.** Die Sinntreue prüfte Hook und Clip bisher nur auf Zahlen, Mengen und Geltungsbereich
(`fidelity.hook_claim_check_v2`). Eine kurze Paraphrase kann gerade die Bedingung, die Zuschreibung oder den
Zeitraum weglassen (Review 8). Ein Beispiel ist die Verdichtung „Diese Methode kostet dich 40.000 Euro“ aus
„Ich habe in einer Woche rund 40.000 Euro verloren“: sie besteht den Zahlenabgleich und ändert trotzdem
Sprecherbezug und Ursache. Der Kritiker nutzt dasselbe Modell wie die Bewertung. Die Forderung nach einem zweiten
Modell ist im Original Pflicht, aber nicht gemessen.

**Alternativen.** (a) Nur der bestehende Kritiker. (b) Ein deterministischer Gegenleser nach Zuschreibung,
Verneinung, Sicherheit, Bedingung, Zahl und Zeitbezug gegen Kontext und Hook, plus die Prüfung der
Hook-Verdichtung nach Regel 6. (c) Zusätzlich der Modellprompt `counter_reader_v1`, der nur Clip und Hook sieht
und je Dimension Zitate liefert. (d) Ein zweites Modell, das mitentscheidet. (e) Ein zweites Modell, das nur
gemessen wird.

**Evidenz.** Der Beispielfall aus Regel 6 steht als Test in `test_launch_p3_counter_reader.py` und
`test_launch_rules.py`: die zulässige Verdichtung besteht, die unzulässige verletzt Zuschreibung und Kausalität.
Die Zitatprüfung des Modellteils ist dieselbe wie beim Kritiker. Ein echter Provider ist lokal nicht verfügbar.
Zusatzfunde und Fehlablehnungen eines zweiten Modells sind deshalb nicht gemessen.

**Unsicherheit.** Die Wortlisten (Abschwächung, Kausalverben, Zeitwendungen, Näherungen) sind Hypothesen ohne
Messung (H). „Rund“ wegzulassen gilt als Befund zur Größenordnung, das kann zu streng sein. Zwei Modelle können
denselben fehlerhaften Transkripttext übernehmen und finden dann gemeinsam nichts. Die Heuristik ist kein Modell
und kein zweites Modell.

**Entscheidung.** (b) und (c) mit (e):

- Regelbasiert: Schalter `implementation.context.counter_reader` und Regel `context.counter_reader.enabled`
  sind an. Ergebnis in `rubric.counter_reader.deterministic`, je Dimension ein Befund mit Zitat aus Clip und
  Quelle. Die Regel-6-Prüfung gilt mit derselben Regel im Claim-Check der Hooks (`hook_claim_check_v2`).
- Modellprompt: nur mit Regel `context.counter_reader.model` (aus, wegen Budget P41) und laufendem Kritiker.
- Verwerfen: nur ein bestätigter Befund hoher Schwere des ersten Modells mit wörtlichen Zitaten, wie beim
  Kritiker (P42), Grund `critic:counter_reader_<dimension>`.
- Zweites Modell: nur mit `LLM_PROVIDER_SECOND`. Es wird gemessen und verwirft nie. Berichtet werden
  `additional_findings` (Funde nur vom zweiten) und `rejected_by_second_only`. Sein Aufruf zählt im selben Budget.

**Konsequenzen.**

- *Produkt:* Hooks, die Sprecherbezug, Ursache, Zeitraum oder Sicherheit verschieben, fallen auf den wörtlichen
  Rückfall zurück. Abweichungen im Kontext zeigt die Oberfläche als unsicher mit Quellstelle.
- *Redaktion:* Die sechs Befunde mit Zitat ersetzen die Paraphrase als Prüfgrundlage. Bestätigte Fehler bleiben
  von Hinweisen getrennt.
- *Engineering:* Der Modellteil kostet je geprüftem Kandidaten einen Aufruf, mit zweitem Modell zwei. Einschalten
  erst nach einem Lauf mit echtem Provider, der Zusatzfunde und Fehlablehnungen an einer redaktionell geprüften
  Stichprobe ausweist.
