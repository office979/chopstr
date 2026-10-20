# 001: Ehrliche Inventur und Gate 0 (Phase 0)

Stand 20.10.2026, Code-Stand 6c9f29f (vor den Arbeiten der Phasen 1 bis 5). Auftrag:
`docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 8, Phase 0. Vier Inventur-Lanes haben nur gelesen (Pipeline gegen
die 15 Schwachstellen, Web-Oberfläche, ASR/Sprecher/Render, Messsystem); der Baseline-Lauf hat die vorhandene
Pipeline an Material ausgeführt. Jede Zahl trägt ihre Quelle; was nicht messbar ist, steht so.

## 1. Was tatsächlich existiert (gegen Abschnitt 2 des Originals)

Das Original beschreibt ein syntaxgeprüftes Gerüst, nie an Material gelaufen. Tatsächlich:

| Bereich | Stand | Beleg |
|---|---|---|
| Worker | läuft lokal ohne Temporal (`local_worker`), mit Temporal in Docker (nicht in dieser Sitzung ausgeführt); Tests 2746 passed, 3 skipped, 24 xfailed; ruff ohne Befund | `workers/`, Abnahmebericht Core Clipping Abschnitt 9.1 |
| Web | Next.js 16, 807 Tests grün, läuft lokal gegen Postgres 5499 | `apps/web` |
| Policy | Fassung 1 (Standard, byteidentisch, Snapshot-Test) und Fassung 2 (Core Clipping) mit Schaltern `implementation.*`; Fassung 2 nur mit `CHOPSTR_POLICY_VERSION=2` | `packages/editorial/`, `docs/PIPELINE.md` Abschnitt 8 |
| ASR | faster-whisper auf CTranslate2, Modell `cstr/whisper-large-v3-turbo-german-int8_float32` (einziges Modell im Cache, 814 MB); `language="de"` fest; Varianten `de` und `de-CH` am Markenprofil, AT über das DE-Modell; Hotwords nur Markenwörterbuch; CH-Modell nicht vorhanden | `transcribe.py:30, 303-327, 358`, `config.py:129-131` |
| Sprecher | pyannote `speaker-diarization-community-1`, nur `exclusive_speaker_diarization` (Überlappung geht verloren); lokal nicht lauffähig (torch, pyannote, HF-Token fehlen); Fallback ein Sprecher für alles, als `skipped` markiert; eine Audiospur je Quelle, Mono-Mix | `transcribe.py:203-231, 454-529`, `ingest.py:135-142` |
| Wortzeiten | nur Whisper-Wortzeitstempel, kein Alignment, kein `time_source`; Highlight-Versatz nirgends gemessen | `transitions.py:44`, `captions_de.py:743` |
| Momentfindung | Kapitel fest 240 s, Überlappung 30 s nur v2; Heatmap 0,5 Audio (z-normiert) plus 0,5 Text (roh); deterministische Payoff-Suche, Gates (Berichtsmodus), Kritiker, Kürzung (Regel aus), ClipCandidate; kein Vergleich über Kapitel außer Sortierung nach `total` | `story_engine.py:58, 1624-1660`, `signals.py:77-131` |
| Render | Original-Audio je Segment, 20-ms-Fades, Loudnorm zweistufig, Titelkarte und Hook als drawtext, Captions libass, Reframe neutral (OpenCV und YuNet fehlen, auch im Image), Ausgabeprüfung vor Upload; bei Prüffehler bleibt die Datei mit `file_key` stehen | `render.py:214-269, 899-986` |
| Web-Freigabe | vollständige Timeline mit Schnitt, Effekten, Musik (Reiter „Schnitt“); keine Begründung, keine Belegstellen, keine Flags, keine Qualitätszahl auf der Karte; Annehmen und Ablehnen nur über API, nicht aus der Oberfläche; Upload ohne Briefing | `ClipDetail.tsx:126-132, 1124-1230`, `ClipBoard.tsx:987-990` |
| Messsystem | `eval_harness` (P@k, Recall, IoU 0,5, ein k), `clip_eval`, `blind_compare` (v1 gegen v2, 0 Bewertungen), `wer_eval` (WER ohne jiwer); keine Referenzdaten, kein Split, kein cpWER, kein DER, kein Highlight-Versatz, keine Baseline-Datei; leere Eingaben werden 0 statt None | `workers/eval/` |

Platzhalter oder tot: Lachen in der Heatmap (`laughter_values` leer, Bonus 0,8 ohne Quelle), `gladia-eu`
Fallback (nie aufgerufen), Reframe-Detektor (ohne Modell neutral), `dach_nlp.auto_remove_ranges` (kein
Aufrufer), `qualityWord`/`formatTotal` im Web (kein Aufrufer, falsche Skala), `.env.example` nennt
`primeline/whisper-large-v3-turbo-german`, das faster-whisper nicht direkt lädt (README 537); das CPU-Image
(`workers/Dockerfile`) installiert kein faster-whisper, bedient laut Compose aber beide Queues (abgeleitet,
nicht ausgeführt).

## 2. Baseline-Lauf an Material (Fassung 1, Heuristik, CPU)

Material: drei synthetische Gespräche mit echter ASR (TTS, je zwei Stimmen, 4 bis 5 Minuten, Video 720p; aus
`workers/eval/runs/testmaterial/`), eingetragen mit `workers/eval/ingest_local.py` (neu, Phase-0-Reparatur:
ohne Web-Upload gab es keinen Weg, Dateien als Quelle einzutragen) und verarbeitet mit
`python -m chopstr_worker.local_worker --once` auf einem Apple-Silicon-Mac, ohne Diarisierung, Provider
`local-heuristic`. Das echte Material im Repo (23 s Interview, 44 s Werbeanzeige) ist zu kurz für mehr als
einen Kandidaten und war schon verarbeitet. Es gibt kein Langvideo von 30 bis 120 Minuten im Repo.

| Quelle | Dauer | ASR | Kandidaten | zurückgehalten (Flag) | gerendert |
|---|---|---|---|---|---|
| A Interview Handwerk | 297,9 s | 115,6 s | 3 | 3 (claim, einmal auch sensitive_topic) | 0 |
| B Monolog Gründerin | 242,6 s | 73,9 s | 3 | 2 (claim) | 1 |
| C Debatte Viertagewoche | 242,8 s | 84,7 s | 2 (1 verworfen: too_long 76,5 s) | 2 (claim) | 0 |

Laufzeit gesamt 310 s für 783 s Material, davon ASR 274 s; hochgerechnet rund 24 Minuten je Quellstunde auf
CPU (Schwelle: unter 20 Minuten; Wert auf GPU nicht gemessen). Render des einen Clips 7,3 s. Alle 8 Kandidaten
tragen `heuristic_only`; 7 von 8 tragen `claim` und bleiben nach Produktregel P27 als Entwurf stehen, bis ein
Mensch sie prüft. Die Freigabe dieser 7 ist Sache des Prüfers und wurde in dieser Sitzung nicht ausgeführt.

WER gegen die Skripte (Normalisierung aus `make_material.py`, Ergebnis in
`workers/eval/runs/2026-10-20-baseline/asr_wer.json`): A 2,3 %, B 1,1 %, C 8,8 %. Standalone auf der
Original-WAV (03.10.) waren es 1,3 / 1,4 / 3,5 %. **Defekt gefunden:** Im Worker-Pfad fehlen in C 37 Wörter am
Stück (73,5 bis 86,3 s, „Das funktioniert nur, wenn man die Arbeitszeit pro Tag erhöht …“), dazu Lücken über
2 s bei 56,3 bis 61,7 s und 95,0 bis 97,6 s. Das ist eine verschluckte Bedingung („nur, wenn“), also ein
Sinnfehler nach Regel 2, der vor jeder Clip-Logik entsteht. Übergeben an Phase 1 (Verdacht VAD-Parameter
oder Fensternaht auf dem AAC-dekodierten Signal). Alle Wörter tragen `SPEAKER_00` (Diarisierung übersprungen).

Weitere Reparatur für den Baseline-Lauf: der Symlink `workers/.local/bin/ffmpeg` zeigte auf einen alten Pfad
und wurde neu gesetzt (libass und drawtext vorhanden).

## 3. Baseline je Launch-Schwelle (Abschnitt 1 der gültigen Fassung)

| Kriterium | Baseline | Status |
|---|---|---|
| Verwendbarkeit (60 % ohne Änderung, 3 je Quellstunde) | nicht messbar: keine Redakteure, kein echtes Langmaterial; Ausbeute Fassung 1: 8 Kandidaten auf 0,22 Quellstunden, 1 gerendert | nicht messbar |
| Sinnfehler | nicht messbar: keine manuelle Prüfung; automatischer Testsatz editorial_v1: Fassung 1 11 von 14, Fassung 2 14 von 14 (Abnahmebericht 9.2); ein Transkript-Dropout als Fehlerquelle gefunden | nicht messbar |
| Schnittqualität | nicht messbar: keine Hörer; automatische Grenzqualität aus `clip_eval` vorhanden | nicht messbar |
| Untertitel WER | Hochdeutsch synthetisch 1,1 bis 8,8 % (Schwelle 4 %; C reißt sie durch den Dropout); AT nicht messbar (kein AT-Material); Highlight-Versatz nicht messbar (keine Audioanker, kein Werkzeug) | teilweise |
| Debatten-Sprecherzuordnung | nicht messbar: Diarisierung lokal nicht lauffähig; Referenz `sprecherwechsel.json` vorhanden (synthetisch, ohne Überlappung); cpWER und DER ohne Werkzeug | nicht messbar |
| Vergleich gegen Wettbewerber | nicht messbar: kein Wettbewerbsmaterial, keine Bewerter; Werkzeug kennt nur v1 gegen v2 | nicht messbar |
| Reproduzierbarkeit | Cache-Wiederholung identisch (Schlüssel); frische Läufe mit Heuristik deterministisch (Tests); mit Sprachmodell nicht messbar (kein Provider) | teilweise |
| Laufzeit | rund 24 Minuten je Quellstunde auf CPU (Schwelle 20, GPU nicht gemessen); Bedienzeit Upload bis Freigabe nicht gemessen | gemessen, Schwelle verfehlt (CPU) |

Regel aus der Review: kein fehlender Wert zählt als bestanden oder null.

## 4. Status der 15 Schwachstellen vor den Phasen 1 bis 5

Standard ist Fassung 1; fast alles, was unten „teilweise“ heißt, wirkt nur unter Fassung 2 und oft nur mit
Regel oder Schalter. Belege aus der Inventur-Lane Pipeline.

| Nr. | Schwachstelle | Stand vor Phase 1 | Beleg |
|---|---|---|---|
| 1 | Referenzdaten | teilweise: Werkzeuge da, keine Gold-Spannen, kein Split | `eval_harness.py:23-43`, `eval/clips/` leer |
| 2 | Gewichte gesetzt | offen, ehrlich dokumentiert („nicht gemessen“); gelernte Gewichte ausgesetzt | `story_score.py:162`, Y2:910, `story_engine.py:200-207` |
| 3 | Ein Aufruf je Kapitel, absolute Scores | teilweise: v2 Übersicht plus Vorschlag plus Suche; kein Vergleich über Kapitel, kein zweites Modell, kein Mehrfach-Sampling | `story_engine.py:2104-2201, 1624-1660` |
| 4 | Kapitel 4 Minuten | teilweise: 30 s Überlappung nur v2, keine Themenerkennung | `segment.py:136-160`, Y2:592 |
| 5 | Heatmap audio-lastig | teilweise: 50/50, Text roh statt normiert, Marker auf 2,4 bis 6,2 % der Sätze | `signals.py:77-131` |
| 6 | Story-Graph 60 s | teilweise: `LOOKAHEAD_S = 60`, Arten correction/contrast ohne Sprecherbezug | `story_graph.py:36, 88-121` |
| 7 | Exklusive Diarisierung | offen | `transcribe.py:527` |
| 8 | Schnitt nur Text | teilweise: Pausen aus Wortlücken, `boundary_confidence` gesetzt; keine Prosodie | `transitions.py:26-35` |
| 9 | Füllwort-Kürzen | im Code behoben (geschützte Spannen), Regel `trim.enabled` aus | `trim_plan.py:77-80, 284-300` |
| 10 | Humor, Lachen | teilweise: Flag und Sperre da; Lachen nie berechnet | `signals.py:139-151`, `analyze.py:60` |
| 11 | CH und AT | teilweise: CH-Route ohne Modell, AT über DE, Erkennung nachträglich ohne Routing | `transcribe.py:30, 371`, `nlp.py:59-70` |
| 12 | Verbklammer | teilweise: drei Fälle; zu-Infinitiv und Korrelate fehlen | `dach_nlp.py:355-480` |
| 13 | Eigenständigkeit | im Code behoben (deterministische Gates v2), Standard offen, keine Koreferenz | `editorial_gates.py:414-871` |
| 14 | Visuelle Analyse | offen, dokumentiert (Reframe neutral) | `reframe.py:8` |
| 15 | Zwei Zahlen im UI | offen anders als beschrieben: keine Reichweitenzahl, aber auch keine Qualitätszahl sichtbar | `ClipBoard.tsx`, `labels.ts:62-75` |

Der Status nach den Phasen 1 bis 5 steht in `docs/launch-report.md`.

## 5. Erste Datenlage zu den Widersprüchen A, B, C

- A (Suche oder Ranking): nicht entscheidbar ohne Referenzmomente. Werkzeug für die Abdeckung an drei Stellen
  (Pool, nach Gates, Top-k) wird in Phase 2 gebaut und bleibt bis zu echten Referenzen ohne Zahl. Beobachtung
  aus dem Blindvergleich Lauf B: Fassung 2 verwirft 41,3 % der Vorschläge (Überdeckung, Kapitelgrenze, zu kurz),
  das spricht dafür, zuerst Pool und Gates zu messen, nicht das Ranking.
- B (Lachen): nicht messbar, Lachen wird nicht berechnet. Entscheidung: Lachen bleibt Hinweis, kein Bonus,
  bis es Daten gibt (`laughter_values` leer).
- C (Schnitt und Füllwörter): epistemische Marker sind geschützt (Code), Prosodie fehlt; Hörtest nicht
  möglich. Phase 4 baut die Prosodie-Grenzen mit Schalter, Hörtest bleibt offen.

## 6. Gate 0

Inventur liegt vor, alle messbaren Baselines sind gemessen (Laufzeit, WER Hochdeutsch synthetisch,
Determinismus mit Heuristik, Ausbeute Fassung 1), die übrigen sind mit Ursache als nicht messbar
ausgewiesen. Ein Defekt (ASR-Dropout) ist gefunden und an Phase 1 übergeben. Gate 0 gilt als bestanden im
Sinn der gültigen Fassung (Inventur plus messbare Baselines); es gilt nicht als Nachweis für eine Schwelle.

**Entscheidung (Perspektiven).** Produkt: Die Phasen 1 bis 5 laufen parallel als Lanes, weil sie voneinander
unabhängig sind; die Timeline wird entfernt. Redaktion: Keine Zahl aus synthetischem Material wird als
Qualitätsnachweis verwendet; die 7 zurückgehaltenen Kandidaten warten auf einen Prüfer. Engineering: Der
ASR-Dropout hat Vorrang vor jeder Clip-Logik, weil er einen Sinnfehler vor der Auswahl erzeugt.
