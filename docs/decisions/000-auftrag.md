# 000: Der Launch-Auftrag selbst (erste Antwort nach Abschnitt 9)

Stand 20.10.2026. Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` (gültige Fassung nach Review). Diese Notiz ist die
erste Antwort nach Abschnitt 9: Perspektiven auf den Auftrag, Inventur-Plan für Phase 0, Risiken, Rückfragen.
Der Auftraggeber hat bei der Übergabe verfügt, dass nicht auf Freigabe gewartet wird; die Rückfragen sind
deshalb mit Annahmen beantwortet, die er widerrufen kann.

## 1. Entscheidungsnotiz zum Auftrag

**Problem.** Der Auftrag beschreibt den Stand vom 21.09.2026 (Gerüst, nie gelaufen) und will in acht Wochen
Launch-Reife mit acht messbaren Schwellen. Der tatsächliche Stand ist weiter (Inventur in `001-inventur.md`),
aber die wichtigsten Nachweise hängen an Dingen, die im Repo nicht existieren: echtes Langmaterial,
Redakteursurteile, ein Sprachmodell-Provider, Diarisierung, ein Wettbewerbsvergleich.

**Perspektive Produkt und Entwicklung.** Zu ambitioniert ist nicht die Technik, sondern die Beweislast: Von
acht Schwellen sind heute vier ohne Menschen oder fremdes Material nicht messbar (Verwendbarkeit,
Schnittqualität, Sinnfehler, Vergleich), zwei ohne Modelle oder Referenzen nicht messbar (Untertitel-WER auf
AT, Debatten-Zuordnung), eine misst heute nur den Cache (Reproduzierbarkeit) und eine ist messbar
(Laufzeit). Die Woche-1-bis-8-Planung ist deshalb ein Ziel, keine Zusage. Zu vorsichtig ist das Original
beim „Timeline raus“: Es gibt eine fertige Timeline mit Schnitt, Effekten und Musik, die dem Produktversprechen
„Freigabe statt Editor“ widerspricht und Pflegeaufwand bindet. Das Entfernen ist eine klare, prüfbare
Aufgabe (Phase 5) und wird gemacht; die Korrekturen ohne Timeline (Worttext, Sprecher, Untertitelstil,
Bildausschnitt) bleiben, weil sie kein Schnitt sind.

**Perspektive redaktionelle Qualität.** Falsch wäre, Schwellen an Fixtures oder synthetischem Material als
erfüllt zu melden. Das Material im Repo (drei TTS-Gespräche von 4 bis 5 Minuten, ein 23-s-Video, eine
44-s-Werbeanzeige) ist Entwicklungsmaterial; es taugt für Defektsuche und Regression, nicht für ein
Redakteursurteil. Die Schwelle „6 von 10“ wird als Anteil mit Mindestzahl je Quellstunde gesetzt, damit die
Pipeline wenige gute Clips liefern darf (Regel 15). Die Sinnfehler-Schwelle wird als „kein bestätigter
kritischer Fehler in freigegebenen Clips“ plus Unsicherheitsbericht gesetzt (Review 2C). Die
Sprachregeln 3, 5, 6, 7 sind so präzisiert, dass sie gute Clips nicht blockieren.

**Perspektive AI Engineering.** Zu früh verpflichtend waren Pairwise-Ranking, Zwei-Modell-Verifikation,
logistische Regression, Flix-Modell und 5-%-Separation; sie sind jetzt Hypothesen mit Abnahmekriterium.
Technisch falsch im Original: „Highlight-Versatz Forced Alignment gegen Whisper“ (misst nur die Differenz
zweier Verfahren), „exklusive Diarisierung“ als Befund ohne Prüfung, welche Ausgabe genutzt wird (die
Pipeline nutzt tatsächlich nur `exclusive_speaker_diarization`, Inventur 2.2), und „Modalpartikel über POS“
(ein Tag entscheidet nicht über die Funktion). Lokal fehlen torch, pyannote, spaCy, OpenCV; WER-Werkzeug
existiert, cpWER und DER nicht. Die Entscheidung „Suche oder Ranking zuerst“ braucht die Abdeckung an drei
Stellen (Pool, nach Gates, Top-k), nicht nur Recall@20.

**Alternativen.** (a) Auftrag wörtlich ausführen und an Gate 0 stehen bleiben, weil Baselines fehlen.
(b) Auftrag nach Review überarbeiten, messbare Teile messen, nicht messbare mit Ursache ausweisen, die
Engineering-Arbeiten, die ohne Menschen gehen, ausführen und den Launch-Bericht ehrlich schreiben.
(c) Auftrag zurückweisen, bis Material und Redakteure da sind.

**Evidenz.** Inventur-Berichte (`001-inventur.md`), Abnahmebericht Core Clipping, Blindvergleich Lauf B
(0 von 24 Paaren bewertet), Review-Rechnung zur Binomialgrenze.

**Unsicherheit.** Wie weit die Engineering-Arbeiten ohne echtes Langmaterial tragen, ist offen; jede Zahl aus
synthetischem Material kann am echten Material kippen.

**Entscheidung.** (b). Der Auftraggeber hat „ohne Widerrede durchsetzen“ verfügt; die Review-Korrekturen
sind Teil des Auftrags. Das Ergebnis ist ein Launch-Bericht, der für jede Schwelle sagt: erreicht, nicht
erreicht oder nicht messbar, und was fehlt.

**Konsequenzen.** Phase 0 beginnt sofort (Abschnitt 2). Die Phasen 1 bis 5 werden als Prioritäten mit
Nachweisen abgearbeitet, parallel wo unabhängig. Alles Menschliche (Redakteurs-Top-10, Hörtest,
Blindvergleich gegen Wettbewerber, Audioanker) wird als Werkzeug plus Anleitung geliefert und als „nicht
messbar, wartet auf Bewertende“ berichtet.

## 2. Inventur-Plan für Phase 0 (ausgeführt, Ergebnisse in `001-inventur.md`)

1. Repo-Stand lesen und je Modul prüfen (vier Inventur-Lanes: Pipeline gegen die 15 Schwachstellen,
   Web-Oberfläche, ASR/Diarisierung/Render, Eval-Harness):

```bash
cd workers && .venv/bin/python -m pytest -q -x -p no:cacheprovider && .venv/bin/ruff check .
cd apps/web && npx vitest run && npx tsc --noEmit
```

2. Installierte Abhängigkeiten und Modelle feststellen (kein pip-Aufruf, der pip-Shebang zeigt auf einen alten
   Pfad):

```bash
cd workers && .venv/bin/python -c "import importlib.metadata as m; print({d.metadata['Name']: d.version for d in m.distributions()})"
ls ~/.cache/huggingface/hub
```

3. Echtes Material durch die vorhandene Pipeline bis zum Export (lokaler Worker, Heuristik-Provider, Whisper
   auf CPU, keine Diarisierung ohne Token), Laufzeit gemessen:

```bash
cd workers && .venv/bin/python -m eval.ingest_local <video.mp4> --title "..." --speakers 2 --brief '{...}'
cd workers && .venv/bin/python -m chopstr_worker.local_worker --once   # Analyse
cd workers && .venv/bin/python -m chopstr_worker.local_worker --once   # Render
```

4. Baseline mit den vorhandenen Werkzeugen (`clip_eval`, `blind_compare`, `wer_eval` gegen die Skripte der
   synthetischen Gespräche); Referenzstruktur `workers/eval/data/` mit `split.json` anlegen; fehlende Metriken
   (cpWER, DER, Highlight-Versatz, Abdeckung an drei Stellen, Reproduzierbarkeit über 5 Läufe) als Werkzeug
   bauen und „nicht messbar“ mit Ursache ausgeben, wo Eingaben fehlen.

5. Status der 15 Schwachstellen gegen den Code mit Belegen, Gate-0-Notiz.

## 3. Risiken und Gegenmaßnahmen

| Risiko | Art | Gegenmaßnahme |
|---|---|---|
| Kein echtes Langmaterial (30 bis 120 Minuten) im Repo; längste Quelle 5 Minuten, synthetisch | Daten | Baseline an dem, was da ist, deutlich als synthetisch markiert; `eval/data/README` beschreibt, was der Auftraggeber liefern muss; Werkzeuge nehmen echtes Material ohne Codeänderung |
| Kein Sprachmodell-Provider lokal; Heuristik unkalibriert | Technik | Alle Zahlen tragen `provider: local-heuristic`; Schwellen, die ein Modell brauchen, heißen „nicht messbar“ |
| Diarisierung nicht lauffähig (torch, pyannote, HF-Token fehlen); Debatten sind Kernformat | Technik | Sprecherzuordnung je Wort als Metrik und Werkzeug bauen (gegen `sprecherwechsel.json` und RTTM); Overlap-Pfad so vorbereiten, dass die nicht exklusive Ausgabe genutzt wird, sobald das Modell läuft |
| Keine Redakteure, keine Hörer, kein Wettbewerbsmaterial | Daten, Zeit | Bögen und Protokolle fertigstellen (Bewerter-ID, „gleich gut“, „beide unbrauchbar“), Zeitbedarf je Bewertung angeben, Ergebnisse als offen führen |
| Timeline-Entfernung bricht Routen, Tests und Werbetexte | Technik | Abhängigkeitsliste aus der Inventur; Routen und Tests gezielt entfernen, Korrekturen ohne Timeline behalten, Produkttexte angleichen |
| Überanpassung an das Entwicklungsmaterial | Methode | `split.json` trennt Entwicklung, Kalibrierung und Abschluss; Abschlusssatz bleibt leer, bis echtes Material kommt, und wird dann nicht zur Entwicklung genutzt |
| Acht Wochen sind ohne Material nicht haltbar | Zeit | Phasen als Prioritäten; Launch-Bericht nennt je Schwelle den Restaufwand |
| Policy v1 muss byteidentisch bleiben | Technik | Snapshot-Test bleibt rot bei jeder Abweichung; Neues nur unter v2 und Schaltern |

## 4. Rückfragen (mit Annahmen, da keine Wartepause)

1. Echtes Material: fünf Langvideos von PLACEMedia (2 Debatten, 2 Podcasts, 1 Erklärformat) mit Rechten?
   Annahme: kommt später; die Werkzeuge sind darauf vorbereitet, der Abschlusssatz bleibt bis dahin leer.
2. Rechte an Wettbewerbs-Clips und Zugang zu einem Wettbewerbstool für den Blindvergleich? Annahme: nein;
   der Vergleich bleibt „nicht messbar“, das Protokoll ist fertig.
3. Sprachmodell-Provider und Zugangsdaten (Bedrock EU oder Mistral EU) für Messungen mit echtem Modell?
   Annahme: nicht in dieser Sitzung; Zugangsdaten werden nie vom Agenten eingetragen.
4. HF-Token und Rechenumgebung für pyannote (torch) sowie getrennte Mikrofonspuren bei Debatten? Annahme:
   nicht vorhanden; Sprecherpfad wird vorbereitet und gegen die synthetische Ground Truth geprüft.
5. Wer sind die drei Redakteure und die drei Hörer, und wann? Annahme: offen; Bögen liegen bereit.
