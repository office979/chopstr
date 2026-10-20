# 052: Eine Qualitätszahl, keine Reichweitenzahl

Stand 20.10.2026, Lane W (Phase 5). Bezug: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 8 (Phase 5: „Eine
Qualitätszahl, nicht zwei“), `packages/schema/CANDIDATES.md` (Spalte `total`), Decision 051.

**Problem.** Die Liste zeigte keine Zahl. In `lib/candidates/labels.ts` lagen `formatTotal` und
`qualityWord` ohne Aufrufer; `qualityWord` stufte ab 8 als „Sehr stark“ ein, also auf einer Skala bis 10,
die `total` nie hatte. Zur Wahl standen mehrere Zahlen: `total`, die fünf alten Werte in `rubric.scores`
(0 bis 10), die acht Teilwerte in `rubric.anchor_subscores` (0 bis 4) und die sieben `rubric_points`
(0 bis 2).

**Alternativen.** (a) `total` auf 0 bis 10 umrechnen. (b) Ein Wort statt einer Zahl („Stark“). (c) `total`
unverändert auf der Skala der Richtlinie zeigen: „Qualität 9,3 von 14“. (d) Zusätzlich eine
Reichweitenprognose.

**Evidenz.** `total` ist `Policy.gesamtwert(rubric_points)` über sieben Kriterien zu je 0 bis 2, also
nominal 0 bis 14, mal `(1 - laenge_abzug)`, danach der Klang-Faktor
(`workers/chopstr_worker/pipeline/story_engine.py`, `policy_total`; CANDIDATES.md). Der Klang hebt oder
senkt um höchstens 15 Prozent (`audio.gewicht: 0.15`, `in_bewertung_verwenden: true` in
`packages/editorial/clip_policy_v1.yaml` Zeile 307 und `clip_policy_v2.yaml` Zeile 349), also bis 16,1.
Ob er wirkte, steht in `rubric.klang` (null heisst: keine Heatmap mit Audioanteil). Die Teilwerte sind
`uncalibrated` und gehen in kein `total` ein. Eine Reichweitenzahl erzeugt die Pipeline nirgends.

**Unsicherheit.** `total` ist nicht kalibriert: es ordnet Kandidaten eines Laufs, sagt aber nicht, wie viele
Redakteure den Clip posten würden. Die Vorgabe des Auftrags („von 14 unter Fassung 1, von 16,1 unter
Fassung 2“) trifft die Sache nicht ganz: beide Fassungen nutzen den Klang-Faktor; entscheidend ist, ob
`rubric.klang` gesetzt ist. Der Wert 16,1 spiegelt das heutige Gewicht 0,15 und ist im Web fest
hinterlegt, bis die Pipeline `rubric.policy_total_max` schreibt.

**Entscheidung.** (c). `qualityScore` in `apps/web/lib/candidates/review.ts`: „Qualität x,x von 14“, mit
`rubric.klang` „von 16,1“, ein ausdrückliches `rubric.policy_total_max` gewinnt; ohne `total` keine Zahl.
Keine Umrechnung auf 0 bis 10: die Skala ist nicht 0 bis 10, und eine umgerechnete Zahl mit
Nachkommastelle täuscht eine Genauigkeit vor, die ein unkalibrierter Wert nicht hat (die Review warnt vor
Scheingenauigkeit). Kein Wort statt der Zahl, weil Schwellen für „stark“ nicht gemessen sind. Es gibt
keine Reichweitenzahl, weder an der Karte noch sonst in der Oberfläche; die Zahl trägt den Hinweis „keine
Reichweitenprognose“. `formatTotal` und `qualityWord` sind entfernt.

**Konsequenzen.** Die Liste sortiert innerhalb einer Ergebnisklasse nach `total` (051). Teilwerte und alte
Scores bleiben in den Daten und werden nicht gezeigt. Wenn die Pipeline die Skala ändert, muss sie
`rubric.policy_total_max` schreiben, sonst stimmt der Nenner nicht.

*Produkt.* Eine Zahl, die man vergleichen kann, ohne eine zweite zu erklären; kein Versprechen über
Reichweite, das niemand einlösen kann.

*Redaktion.* Die Zahl ordnet, die Entscheidung bleibt beim Menschen; Ergebnisklasse und Begründung stehen
vor ihr.

*Engineering.* Der Nenner kommt aus den Daten des Kandidaten, nicht aus einer Annahme über die Fassung.
Tests: `tests/kandidat-freigabe.test.ts`, Block „qualityScore“.
