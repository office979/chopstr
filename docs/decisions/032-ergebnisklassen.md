# 032: Drei Ergebnisklassen als Vertrag für Web und Export

Stand 20.10.2026, Lane P3 (Launch Phase 3). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Regeln 2, 3, 8 und 14;
Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitte 3 und 5.

**Problem.** Es gab nur angenommen, zurückgehalten (Flags `humor`, `sensitive_topic`, Behauptung) und verworfen.
Regelhinweise der Gates, Modellbefunde und bestätigte Fehler standen getrennt in der Rubrik, ohne gemeinsame
Ableitung. Die Oberfläche konnte nicht unterscheiden zwischen „ein Mensch muss eine Unsicherheit auflösen“ und
„dieser Kandidat ist nicht freigabefähig“. Ein bestätigter Sinnfehler darf nicht durch bloßes Anklicken
verschwinden (Review 5).

**Alternativen.** (a) Weiter nur Flags. (b) Ein Gesamtscore mit Schwelle. (c) Drei Klassen `passed`,
`uncertain` und `blocked`, deterministisch aus dem, was die Pipeline schon geprüft hat. Jeder Grund trägt Code,
Satz, Quellstelle und Herkunft (`rule`, `model`, `confirmed`).

**Evidenz.** `test_launch_p3_review_state.py` prüft:

- jede Klasse;
- dass ein Regelhinweis allein nie `blocked` ergibt;
- dass ein bestätigter Kritikerbefund im Lauf `blocked` ergibt;
- die Titelkarte mit erneuter Prüfung;
- dass die Auto-Annahme nur `passed` annimmt.

Wie oft echte Kandidaten `uncertain` werden, ist nicht gemessen. Auf den Demo-Fixtures sind es die meisten,
weil die Gates im Berichtsmodus viele Hinweise geben.

**Unsicherheit.** Viele Hinweise sind Wortlistentreffer (H). Werden fast alle Kandidaten `uncertain`, nimmt die
Automatik kaum noch etwas an, und die Freigabe hängt am Menschen. Das ist gewollt (Freigabe statt Editor), kostet
aber Zeit. `blocked` entsteht heute fast nur bei Kandidaten, die Kritiker oder Gate ohnehin verwerfen.

**Entscheidung.** (c):

- Die Ableitung steht in `release_gate.derive_review_state`. Schalter `implementation.review.review_state` und
  Regel `review.review_state` sind an.
- Die Klasse steht in `rubric.review_state`. `repair` liest nur, ob eine Heilung oder Titelkarte versucht wurde.
- `analyze.auto_accept_blockers` nimmt nur `passed` automatisch an. Ein unsicherer Kandidat hält mit
  `review_uncertain` zurück, ein blockierter mit `review_blocked`. Das Präfix von `verdict_reason` bleibt.
- Die Titelkarte ist zweite Wahl (Regel 2). Sie steht in `rubric.repair_applied`, weil `rubric.repair` unter
  Fassung 1 belegt ist (Absprache mit Lane W). Sie macht den Kandidaten nie `passed`.

**Konsequenzen.**

- *Produkt:* Die Kandidatenliste kann jede Unsicherheit mit Grund und Quellstelle zeigen. Ein blockierter
  Kandidat ist sichtbar nicht freigabefähig, und eine Annahme verlangt eine Begründung (Verdict-Route, Lane W).
- *Redaktion:* Die drei Herkünfte bleiben getrennt lesbar. Ein Mensch kann `uncertain` auflösen, `blocked` nicht
  durch Klicken.
- *Engineering:* Der Vertrag ist additiv. Unter Fassung 1 und mit ausgeschaltetem Schalter fehlt das Feld, und
  die Annahme läuft wie vorher. Offen ist, dass blockierte Kandidaten heute nicht in die Tabelle `candidates`
  geschrieben werden, weil `story_engine.run` sie vorher verwirft. Sollen sie angelegt werden, muss Lane P2
  sie aus `report.verworfen` übernehmen.
