# 051: Die Kandidatenliste ist die Freigabe

Stand 20.10.2026, Lane W (Phase 5). Bezug: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 5 (Regeln 11, 12, 14,
15) und Abschnitt 8 (Phase 5), `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 5, `docs/ENTSCHEIDUNGEN.md`
P27, P36, P37, `packages/schema/CANDIDATES.md`.

**Problem.** Die Liste unter `/projekte/[id]/clips` zeigte keine Begründung (`candidates.why` war bewusst
entfernt), keine Belegstellen, keine Flags, keine Ergebnisklasse, keinen Haltegrund (P27 verlangt ihn
sichtbar) und keine Qualitätszahl. Annehmen und Ablehnen gab es nur als Route
(`api/projects/[id]/candidates/[cid]/verdict`), ohne Aufrufer in der Oberfläche; ein zurückgehaltener
Kandidat wurde nur über „Video clippen“ in der Detailansicht angenommen. Sortiert wurde nach Prüfstand
(was Arbeit braucht) und Startzeit, also nicht nach der Frage, um die es in einer Freigabe geht: welcher
Vorschlag ist verwendbar, und welcher am besten.

**Alternativen.** (a) Eine eigene Freigabeseite neben der Clipliste. (b) Die Clipliste erweitern: jede
Karte trägt den Freigabeteil des Kandidaten. (c) Nur Annehmen und Ablehnen ergänzen, Begründung und
Klasse weiter in der Detailansicht.

**Evidenz.** Regel 12 (jeder Kandidat mit Begründung in einem Satz und Belegstellen), Regel 14 (drei
Ergebnisklassen; ein bestätigter Fehler verschwindet nicht durch Anklicken), Regel 11 (Humor und sensible
Themen gehen mit Flag an den Menschen), P27 (Haltegrund an der Karte). Der Vertrag von Lane P3
(`rubric.review_state` mit `state`, `reasons[{code, text, source_span, origin}]`, `repair`;
Titelkarte in `rubric.repair_applied`) ist in Arbeit; heutige Läufe haben ihn nicht.

**Unsicherheit.** Der Rückfall ohne `review_state` ist eine Ableitung, keine Prüfung: unsicher heisst dort
Haltegrund der Automatik, `humor` oder `sensitive_topic`, oder ein Story-Graph-Treffer; nicht freigabefähig
heisst ein gerissenes Tor (`gate_passed = false`, entsteht nur durch eine Revision). Das Flag `claim`
allein macht nicht unsicher, weil es fast jeden Kandidaten trifft (P36). Belegstellen für Einstieg und
Pointe stehen nur im Bericht des ClipCandidate, nicht in der Rubrik; bis die Pipeline sie in die Rubrik
schreibt, ist die Belegstelle der ganze Clip.

**Entscheidung.** (b). Jede Karte zeigt über `app/projekte/[id]/clips/CandidateReview.tsx`, gerechnet in
`apps/web/lib/candidates/review.ts`: „Warum dieser Clip?“ (`candidates.why`, fehlt er, steht das da),
Ergebnisklasse (bestanden, unsicher, nicht freigabefähig) mit Gründen und Quellstelle, Flags als Wörter,
Belegstellen als klickbare Zeitbereiche (`opening_source_span`, `payoff_source_span` in beiden
Spannenformen, sonst `start_s` bis `end_s`; der Klick öffnet die Vorschau an der Stelle), eine
Titelkarten-Reparatur, das Urteil mit Grund (Haltegrund nach P27, Kommentar an die Redaktion, Ablehnung)
und eine Qualitätszahl (052). Knöpfe: Annehmen, Ablehnen (Pflichtgrund im Dialog), An Redaktion
(Pflichtkommentar, Sekunde im Clip freiwillig). Ein nicht freigabefähiger Kandidat lässt sich nur mit
„Warum trotz Befund?“ annehmen; die Route prüft das selbst (`override_reason`, sonst 400) und speichert
die Begründung im Urteil (`trotz Befund angenommen: …`), im Audit und im Decision Log. Sortierung:
bestanden, unsicher, nicht freigabefähig; darin Qualität absteigend; abgelehnte Kandidaten ans Ende.

**Konsequenzen.** „Flag an Redaktion“ kann nicht als `human_verdict = 'revise'` gespeichert werden: die
Prüfbedingung der Spalte erlaubt nur `accepted`, `rejected`, `edited` (Migration 0001, Zeile 205), und
Migrationen liegen ausserhalb dieser Lane. Das Urteil wird deshalb offen (`null`), der Grund beginnt mit
`an Redaktion: ` (wie der Haltegrund der Automatik), Audit `candidate.flagged`, Decision Log mit
`verdict: "revise"`. Offen heisst nicht veröffentlichbar (`lib/publishing/gates.ts`). Wer eine eigene
Spalte oder einen eigenen Wert will, braucht eine Migration und einen Eintrag in `CANDIDATES.md`. Die
öffentliche Schnittstelle kennt `override_reason` (OpenAPI `Verdict`), aber kein `revise`. Der Prüfstand
der Clips (`offen`, `bereit`, `verworfen`) und die Gastfreigabe bleiben unverändert daneben.

*Produkt.* Die Liste beantwortet die Frage der Freigabe: was darf raus, warum, und was ist offen. „Jede
Auswahl erklärt“ auf der Produktseite stimmt damit.

*Redaktion.* Unsichere Kandidaten zeigen Grund und Quellstelle, sodass ein Mensch die Unsicherheit am
Original auflösen kann; ein nicht freigabefähiger verschwindet nicht durch einen Klick, sondern nur mit
einer gespeicherten Begründung.

*Engineering.* Eine Rechnung für Karte, Sortierung und Route (`reviewState`), mit Rückfall, solange der
Worker `review_state` nicht schreibt. Tests: `tests/kandidat-freigabe.test.ts`.
