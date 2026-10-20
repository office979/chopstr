# 060: Messsystem für den Launch (Phase 0, Lane E)

Stand 20.10.2026. Bezug: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitte 1, 6 und 8 (Phase 0),
`docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitte 2 und 7. Umsetzung in `workers/eval/`, Baseline in
`workers/eval/results/baseline.json`.

**Problem.** Das vorhandene Messwerkzeug konnte keine der Launch-Schwellen belastbar belegen. Das Gold-Format
kannte nur eine Bewertung, keine Person; Entwicklung und Abschluss liefen auf denselben Videos; Recall und
Precision teilten sich ein k; der Grenzfehler mischte Start und Ende; leere Eingaben ergaben 0 statt „nicht
messbar“; cpWER, DER, Highlight-Versatz, Reproduzierbarkeit und Kosten je Quellstunde fehlten; der
Blindvergleich kannte weder „beide unbrauchbar“ noch Bewerter noch einen Vergleich mit einem anderen Werkzeug;
es gab keine Baseline mit Toleranz je Metrik.

**Alternativen.** (1) Fertige Bibliotheken (jiwer, pyannote.metrics, meeteval) einbinden. (2) Eine
Messdatenbank mit Oberfläche bauen. (3) Die vorhandenen Werkzeuge erweitern, je Frage ein kleines Modul mit
JSON-Ausgabe in einem gemeinsamen Metrik-Format, dazu eine Datei-Baseline mit Vergleich.

**Evidenz.** Lokal fehlen torch und pyannote, eine neue Abhängigkeit nur für Metriken wäre im Worker-Image
mitzuschleppen. Die Definitionen sind klein und prüfbar: cpWER ist Levenshtein je Sprecher mit bester
Zuordnung, DER ohne Collar ist eine Summe über Zeitintervalle, die Clopper-Pearson-Grenze trifft die
Review-Zahlen (0 von 20: 13,9 %, 1 von 20: 21,6 %, `tests/test_launch_eval_sinnfehler.py`). Auf dem
synthetischen Testmaterial misst das neue Werkzeug eine WER von 3,1 % (1676 Referenzwörter) und einen
Wortanfang, der im Median 357 ms vor der Montagegrenze liegt (das Ende 112 ms); das ist ein echter Befund über
die Wortzeiten, aber gegen Montagegrenzen und nicht gegen kontrollierte Audioanker gemessen. Von 40
Baseline-Metriken sind 3 messbar, 37 stehen mit Ursache als nicht messbar.

**Unsicherheit.** Die Toleranzen in `eval/baseline.py` (`METRICS`) sind erste Festlegungen ohne
Streuungsmessung; sie müssen nach den ersten wiederholten Läufen auf echtem Material nachgeschärft werden. Die
Wortzuordnung für die Sprecherbewertung folgt dem Text (Levenshtein), bei sehr schlechter ASR werden Wörter
„nicht erkannt“ statt falsch zugeordnet. Der Funnel (`report["funnel"]`) ist ein angenommener Vertrag mit
Lane P2; ohne ihn ist „nach Gates“ nicht messbar. Gold aus zwei Personen ist ein Übereinstimmungssignal, keine
Korrektheitsgarantie.

**Entscheidung.** Alternative 3. Neue Module `data_loader`, `speaker_eval`, `alignment_eval`, `repro_eval`,
`cost_eval`, `sinnfehler`, `baseline`; Erweiterung von `eval_harness` (Abdeckung an drei Stellen, Recall@20,
Precision@5 und @10 je Redakteur, Grenzfehler getrennt, neue Momente), `wer_eval` (None statt 0) und
`blind_compare` (beide unbrauchbar, Bewerter-ID, Zusammenführen, Cohen-Kappa, Wettbewerbsmodus mit vorab
festgelegter Vergleichsart). `eval/data/split.json` legt alles vorhandene Material in `entwicklung`, der
Abschlussteil ist leer und ohne ausdrückliche Bestätigung gesperrt.

**Konsequenzen.** Jede Änderung kann mit `eval.baseline --vergleich` gegen die Baseline gehalten werden;
eine Verschlechterung über der Toleranz endet mit Exit-Code 1. Solange menschliche Referenzen fehlen, sind die
meisten Launch-Schwellen nicht messbar und damit nicht erfüllt; das Werkzeug macht das sichtbar, statt es zu
verdecken. Die Baseline muss neu erstellt werden, sobald DetectReports mit `funnel`, Referenzdaten oder ein
`job_costs`-Export vorliegen.

**Perspektive Produkt.** Das Messsystem beantwortet, ob chopstr mehr eigenständige, sinntreue und direkt
verwendbare Clips liefert, und es sagt ehrlich, wann es das noch nicht beantworten kann. Für die
Launch-Entscheidung heißt das: Ohne fünf echte Langvideos mit Rechteklärung, drei Redakteure und drei Bewerter
gibt es keine Freigabe; der Bericht nennt dann die fehlenden Daten statt einer geschönten Zahl. Der
Wettbewerbsvergleich ist vorbereitet, braucht aber Clips eines anderen Werkzeugs mit geklärten Rechten.

**Perspektive Redaktion.** Die Redaktion liefert Spannen, Top-10, Schnittpunkt-Urteile und Sinnfehler-Bögen in
einfachen JSON-Dateien oder über die Bewertungsseite (`bewertung.html`, jetzt mit Bewerter-ID und „beide
unbrauchbar“). Ein guter Moment außerhalb der eigenen Top-10 zählt nicht als Fehler, sondern als Prüfauftrag.
Ein bestätigter kritischer Sinnfehler sperrt den betroffenen Clip, unabhängig von jeder Quote.

**Perspektive Engineering.** Alle Werkzeuge sind ohne GPU, ohne Datenbank und ohne neue Abhängigkeit testbar;
die Datenbank ist nur über `--database-url` erreichbar. Ein fehlender Wert ist im JSON `None` mit Ursache und
im Bericht „nicht messbar“. Jede Metrik hat Einheit, Richtung und Toleranz an einer Stelle (`METRICS`); eine
unbekannte Metrik bricht den Vergleich ab, damit keine Zahl ohne Definition in einen Bericht gelangt.
