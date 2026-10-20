# 010: ASR-Routing nach erkannter Sprache, Datenvertrag Transkript, Hotwords

Stand 20.10.2026, Lane P1 (Launch Phase 1). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Regel 13 und Phase 1; Review
`docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 4A und 4C. Code: `workers/chopstr_worker/pipeline/transcribe.py`
(`detect_variant`, `classify_variant`, `choose_route`, `build_hotwords`, `transcribe`), Activities `transcribe` und
`nlp`, Policy `asr.*` in `packages/editorial/clip_policy_v2.yaml`.

**Problem.** Drei Befunde. (1) Die ASR lief fest mit `language="de"`; die Variante kam nur aus dem Markenprofil
(`asr_variant` de oder de-CH), Österreich lief ohne Anpassung über das DE-Modell, und `detect_dialect` lief erst
nach der Transkription, ohne zu routen. Regel 13 verlangt Routing nach der tatsächlichen Sprache der Aufnahme.
(2) Kein Ergebnis sagte, ob es wortgetreu ist, woher die Wortzeiten kommen und warum diese Route gewählt wurde.
(3) Echter Defekt aus der Baseline: im lokalen Worker fehlten in `c_debatte_viertagewoche` 37 Wörter am Stück
(73,5 bis 86,3 s), darunter „Das funktioniert nur, wenn man die Arbeitszeit pro Tag erhöht …“, eine Bedingung,
deren Verlust nach Regel 2 ein Sinnfehler ist.

**Ursache des Defekts.** Nicht die VAD: Silero liefert auf der Worker-WAV (aus dem MP4 über AAC) und auf der
Original-WAV dieselben Sprachsegmente, 73,5 bis 86,3 s ist Sprache. Nicht das Fenster- und Nahtverfahren: der Lauf
hat ein Fenster. Nicht Zufall: derselbe Aufruf ohne Wörterbuch ist zweimal identisch (Temperatur 0 in allen
Segmenten). Die Ursache ist das Marken-Wörterbuch des Profils (`["chopstr", "PLACEMedia"]`, Angabe aus der DB über
den Koordinator), das `transcribe` als `hotwords` an faster-whisper gab. faster-whisper 1.2.1 setzt Hotwords als
Prompt vor jeden 30-s-Abschnitt (`WhisperModel.get_prompt`, `sot_prev` plus Hotword-Token); das hat den Decoder
hier über ganze Sätze springen lassen. Nachgestellt in `workers/tests/test_launch_p1_asr_network.py` (Marker
`network`, erste 120 s reichen: 237 Wörter ohne, 200 mit Hotwords).

**Alternativen.** Routing: (a) Profil wie bisher. (b) Erkennung auf einer Stichprobe vor der Transkription, Profil
als Vorgabe, Überschreiben nur bei sicherer Erkennung. (c) Erkennung je Abschnitt mit Wechsel des Modells
mitten in der Datei. Hotwords: (d) wie bisher in den Decoder. (e) nur Nachkorrektur (`apply_brand_vocab`).
(f) `initial_prompt` statt Hotwords. (g) Hotwords im Decoder plus Nachprüfung auf Lücken.

**Evidenz.** WER gegen das Skript (`make_material.norm_tokens`), Worker-WAVs der drei synthetischen Gespräche,
Modell cstr/whisper-large-v3-turbo-german-int8_float32, CPU int8, Wörterbuch `chopstr PLACEMedia`:

| Datei | ohne Hotwords | Hotwords im Decoder | initial_prompt |
|---|---|---|---|
| a_interview_handwerk (617 Wörter) | 1,30 % | 2,27 % | 1,30 % |
| b_monolog_gruenderin (559) | 1,43 % | 1,07 % | 0,89 % |
| c_debatte_viertagewoche (490) | 0,41 %, 0 Auslassungen | 8,78 %, 38 Auslassungen, Lücken 56,3 bis 61,7 s und 73,5 bis 86,3 s | 0,41 % |

Die Markenwörter kommen im Material nicht vor; ein Nutzen der Hotwords für die Schreibweise ist hier nicht
messbar, der Schaden in c schon. Spracherkennung: kein AT- und kein CH-Material im Repo; geprüft ist das Routing
nur mit einem Fake-Modell (`tests/test_launch_p1_asr_routing.py`).

**Unsicherheit.** Drei synthetische Dateien mit TTS-Stimmen; an echtem Material kann der Effekt größer oder
kleiner sein. Ob Whisper Schweizerdeutsch als „de“ erkennt, ist nicht gemessen; die Variante hängt deshalb an
den Lexikon-Markern eines Vorab-Transkripts der Stichprobe (60 s Anfang, 30 s Mitte), und ein Lexikon findet nur,
was drinsteht. Die Schwelle 0,6 ist ein Startwert. Die Austriazismen-Liste (83 Wörter, Variantenwörterbuch des
Deutschen und ÖWB) ist nicht je Eintrag gegen die Druckausgabe geprüft und ohne AT-Material nicht abgenommen.

**Entscheidung.** (b) unter `ASR_AUTO_ROUTE=1` (Standard aus) und (e) als Standard. Routing: `de-CH` mit
`ASR_MODEL_CH` ergibt die CH-Route (Beta), ohne CH-Modell das DE-Modell mit Hinweis `ch_detected_no_model`; `de-AT`
das DE-Modell mit Austriazismen in der Hotword-Liste; sicheres `de` überschreibt auch ein Profil `de-CH`; `unklar`
lässt das Profil stehen; eine andere Sprache ist Hinweis `non_german_detected`, kein Abbruch. Hotwords: die Liste
(Wörterbuch, geschützte Begriffe, Austriazismen, dedupliziert, höchstens `asr.hotwords.max_terms` und 600 Zeichen)
geht nur mit `asr.hotwords.decode: true` in den Decoder; die Regel steht auf false. Das Marken-Wörterbuch wirkt
immer als Nachkorrektur. (f) ist gemessen unschädlich, wirkt aber nur auf den ersten Abschnitt und brachte hier
keinen messbaren Nutzen; nicht übernommen. (g) erst, wenn Material mit Markenwörtern einen Nutzen zeigt.

**Datenvertrag.** Jedes ASR-Ergebnis trägt `route` = {variant, model_id, verbatim, time_source
(`asr_word_timestamps`), beta, detected_language, detected_variant, detection_confidence, routing_reason,
austriacisms, hints, hotwords}; `fuse_and_nlp` schreibt den Kern nach `transcript_versions.stats.asr_route`
(für ältere ASR-Dokumente ohne Route `default_route`). Whisper-DE gilt als wortgetreu (`verbatim: true`), jede
CH-Route als übertragend (`verbatim: false`, Flix-Modellkarte, Review 4A). `text` ist die gesprochene Form,
`text_norm` nur Untertitelform. Gelesen wird `text_norm` ausschließlich in `pipeline/captions_de.py`
(`text_field`), `pipeline/render.py`, `pipeline/render_plan.py` (`caption_text_field`), `activities/render.py`
und im Web (`lib/transcript/dialect.ts`); keine Schnittgrenze, kein Satzende und kein Gate liest es (geprüft per
grep). Wort-Highlights bei `verbatim: false` (Regel 13: größere Untertitelgruppen) muss die Caption-Lane lesen.

**Konsequenzen.** Standardverhalten ändert sich an genau einer Stelle: das Wörterbuch geht nicht mehr in den
Decoder. Der ASR-Key enthält bei nicht leerem Wörterbuch `hotwords: post_only`, damit Transkripte mit möglichen
Auslassungen nicht wiederverwendet werden; ohne Wörterbuch ist der Key gleich. Unter `ASR_AUTO_ROUTE` kosten
Erkennung und Vorab-Transkript etwa 90 s zusätzliche Dekodierung je Quelle. Wortzeiten bleiben Whisper-Zeiten;
eine Messung gegen manuelle Audioanker (Review 4C) fehlt mangels Anker.

**Perspektive Produkt.** Ein Kunde aus Zürich, der Hochdeutsch spricht, und eine Wiener Agentur mit Material in
mehreren Varianten bekommen die Route nach ihrer Aufnahme, nicht nach ihrem Land. Das Marken-Wörterbuch, das
jedes Profil hat, darf nie Inhalt kosten; eine falsch geschriebene Marke ist korrigierbar, ein verschluckter Satz
nicht sichtbar.

**Perspektive Redaktion.** Der Ausfall verschluckte genau die Einschränkung, die eine Aussage wahr macht („nur,
wenn …“). Ein Clip aus diesem Transkript hätte eine unbedingte Empfehlung gezeigt. Dass die CH-Route überträgt,
steht im Ergebnis; ein normalisierter Satz wird nie als gesprochene Wortfolge behandelt.

**Perspektive Engineering.** Die Ursache ist mit einem Test belegt, der Fix ist eine Zeile im Standardpfad plus
Key-Wechsel. Routing, Schwellen und Hotwords sind Policy-Werte mit Herkunft und laufen nur hinter einem Schalter.
Nicht messbar: CH-Route (Modell fehlt), Erkennungsgüte für AT und CH (kein Material), Highlight-Versatz gegen
Audioanker (keine Anker).
