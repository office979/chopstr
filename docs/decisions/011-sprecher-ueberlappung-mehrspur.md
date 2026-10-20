# 011: Sprecherüberlappung erhalten, getrennte Mikrofonspuren nutzen

Stand 20.10.2026, Lane P1 (Launch Phase 1, Transkript und Sprecher). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md`
Abschnitt 8 Phase 1 und Regeln 8 und 16; Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 4B.

**Problem.** Die Diarisierung las nur `exclusive_speaker_diarization` (`pipeline/transcribe.py:diarize`). Diese
Ausgabe ordnet jedem Zeitpunkt genau einen Sprecher zu; wo zwei Menschen gleichzeitig sprechen (Einwurf,
Unterbrechung, Lachen), ging die Information verloren, bevor ein Wort einen Sprecher bekam. `assign_speakers`
vergab je Wort den Mehrheitssprecher ohne Kennzeichen. Zweitens mischte der Ingest die Standard-Audiospur auf
Mono (`ingest.extract_audio`, `-ac 1`); weitere Audiostreams im Container (ein Mikrofon je Sprecher) wurden
nicht gelesen. Ohne `HF_TOKEN` oder pyannote bekommt die ganze Datei einen Sprecher.

**Alternativen.** (a) Nur die exklusive Ausgabe wie bisher. (b) Die reguläre Annotation zusätzlich speichern
und je Wort Überlappung markieren, die exklusive Form für Anzeige und Mehrheit behalten. (c) Quellentrennung
(Separation) bei viel Überlappung. (d) Getrennte Mikrofonspuren als eigene Sprecherquelle über Spurenergie.
(e) Mehrspur über pyannote je Spur.

**Evidenz.** Modellkarte pyannote community-1: reguläre und exklusive Ausgabe, die exklusive zur leichteren
Verbindung mit Transkriptzeiten (Review 4B). Im Repo gibt es kein Material mit echter Überlappung oder mit
mehreren Spuren; pyannote und torch sind lokal nicht installiert. Die Energiezuordnung ist an synthetischen
Spuren geprüft (`tests/test_launch_p1_speakers.py`: Sprecher A, B, beide gleichzeitig, Übersprechen 30 dB
leiser, Stille). Ein Mehrspur-Ingest ist mit einer ffmpeg-Testdatei mit zwei Audiostreams geprüft.

**Unsicherheit.** Ob 0,3 als Mindestanteil je Wort (`speakers.overlap.min_ratio_for_flag`) sinnvoll trennt,
ist nicht gemessen. Die Schwellen der Spurenergie (Fenster 100 ms, 10 dB Abstand, Stille unter -45 dBFS)
sind Startwerte; laute Raumakustik oder Kompressoren auf den Spuren können Übersprechen über die Schwelle heben.
Spuren mit gleicher Startzeit im Container gelten als synchron; eine Drift innerhalb der Aufnahme wird nicht
erkannt. DER und Sprecherzuordnung je Wort haben ohne Referenzmaterial keine Baseline.

**Entscheidung.** (b) und (d). pyannote liefert `turns` (exklusiv, unverändert für Anzeige und Mehrheit) und
neu `overlap_turns` (regulär). `assign_speakers` markiert ein Wort mit `overlap: true` und `speakers`, wenn
mindestens zwei Sprecher je mindestens den Mindestanteil der Wortdauer abdecken; `speaker` bleibt der
Mehrheitssprecher. `stats.overlap_ratio` nennt den Anteil. Mehrspur nur mit `SPEAKERS_MULTITRACK=1`: der
Ingest legt jede Spur als 16-kHz-WAV ab (`sources.audio_tracks`, Migration 0018), wenn alle Spuren dieselbe
Startzeit haben; die Diarisierung nimmt dann `multitrack_energy` statt pyannote (`energy_diarization`: je
Fenster die lauteste Spur, Überlappung, wenn eine zweite Spur höchstens 10 dB darunter und über der
Stilleschwelle liegt). (c) bleibt Hypothese: Separation nur fürs Transkript und nur mit Nachweis am Einzelfall
(Master-Prompt Phase 1). (e) verworfen, weil die Spuren die Trennung schon liefern und pyannote fehlt.

**Konsequenzen.** Der Rückfall ohne pyannote bleibt wie bisher und sichtbar: `diar/*.json` mit `skipped`,
`transcript_versions.diarizer_id = none`, `stats.diarization = skipped` (geprüft in
`tests/test_diarize_fallback.py`). Mit Spuren steht `multitrack_energy` an beiden Stellen. Offen für andere
Lanes: die Löschung (Retention, Löschjob) kennt die Spur-Keys aus `sources.audio_tracks` noch nicht; solange
`SPEAKERS_MULTITRACK` aus ist, entstehen keine. Eine Sprecher-ID ist keine Zuordnung zu einem Gesicht (Regel 16).

**Perspektive Produkt.** Debatten und Interviews sind der Kern des Angebots; eine falsche Zuordnung bei Frage
und Antwort ist nach Regel 8 ein Sinnfehler. Wer mit getrennten Mikrofonen aufnimmt, bekommt die verlässlichste
Zuordnung ohne zusätzliches Modell und ohne Lizenzfrage. Der Schalter bleibt aus, bis echtes Mehrspurmaterial
die Schwellen bestätigt.

**Perspektive Redaktion.** Ein markiertes Überlappungswort ist ein Prüfgrund mit Quellstelle (Regel 14,
„Bewertung unsicher“), kein stilles Raten. Ein Einwurf des Gegenübers mitten im Satz wird sichtbar, statt dem
Hauptsprecher zugeschlagen zu werden. Ein Flag allein repariert nichts; die Gates müssen es lesen.

**Perspektive Engineering.** Beide pyannote-Ausgaben bleiben erhalten, die exklusive Form ändert sich nicht,
die neuen Felder sind additiv (`overlap_turns`, `overlap`, `speakers`, `overlap_ratio`). Die Energiezuordnung
ist deterministisch und ohne GPU testbar. Diar-Keys enthalten Spuren und Regeln, `fuse_and_nlp` rekonstruiert
sie über `diar_key_for_source`. Nicht messbar ohne pyannote und ohne Mehrspurmaterial: Overlap-Erkennung an
echter Aufnahme, DER, Sprecherzuordnung je Wort.
