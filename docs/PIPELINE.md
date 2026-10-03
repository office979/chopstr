# Pipeline des Clipping-Kerns: Ist-Zustand

Stand 03.10.2026, Code-Stand HEAD 070d916. Beschrieben ist, was heute im Code läuft, nicht was laufen soll.
Lieferung nach `docs/MASTER-PROMPT-CORE-CLIPPING.md` Abschnitt 3 (Phase 1). Bekannte Schwächen mit Fundstellen stehen
in `docs/RESEARCH-CLIPPING-KERN.md` Abschnitt 2 und werden hier nicht wiederholt, nur über ihre Nummer (Befund 1 bis 13) verlinkt.

Schreibweise: `W/` = `workers/chopstr_worker/`, `A/` = `apps/web/lib/`, `P/` = `packages/`. Fundstellen als `Datei:Funktion Zeilen`.
Jede Aussage wurde am Code gelesen. Was nicht gelesen oder nicht ausgeführt wurde, steht als "ungeprüft". Stellen, die ich
zusätzlich im venv ausgeführt habe (`workers/.venv`, nur lesend), sind mit "ausgeführt" markiert.

## 1. Übersicht der Stufen

```
Ingest → ASR + Diarisierung (+ Heatmap) → Fusion/NLP → [Kapitel → Vorschlag → Bewertung → Heilung/Teaser → select_best]
       → Zeilen + auto_create_clips → render_pack: [Copy → Reframe → Captions → Plan → ffmpeg → Prüfung] → Ausgabeentscheidung
```

Die eckigen Klammern markieren je eine Activity (`detect_candidates`, `render_pack`). Beide laufen
im lokalen Worker und im Temporal-Workflow über dieselben `run_*`-Funktionen (Unterschiede: Abschnitt 4).

### 1.1 Ingest
- Eingabe: `sources`-Zeile, Original im Bucket `sources`.
- Ausgabe: `sources` (`sha256`, `duration_s`, `width`, `height`, `fps`, `audio_key`, `proxy_key`, `size_bytes`), 16-kHz-Mono-WAV, 720p-Proxy.
- Code: `W/activities/ingest.py:run 21-121`; `W/ingest.py:probe 73-115`, `extract_audio 127-140`, `make_proxy 143-158`.
- Art: deterministisch (ffprobe, ffmpeg). Kein Prompt, keine Policy.
- Key: `storage.derived_key(storage_key, AUDIO_PARAMS | PROXY_PARAMS, "ingest_v1")` (`W/activities/common.py 67-72`). Vorhandene Ableitungen werden übersprungen. Nutzungsminuten werden nur gebucht, wenn `sources.duration_s` noch leer ist (`ingest.py 81-83`).
- Fehler: laut. Ohne Tonspur `IngestError`, `sources.status = failed` über `events.step` (`W/events.py:step 82-110`).

### 1.2 Transkription, Diarisierung, Fusion
- Eingabe: `audio16k.wav`, `asr_variant` (`de` | `de-CH`) und `brand_vocab` des Markenprofils (`W/db.py:load_source 70-98`).
- Ausgabe: `asr/<hash>.json` (`TranscriptResult`: `words[]`, `model_id`, `variant`, `provider`, `beta`, `windows`, `duration_s`, `stats`), `diar/<hash>.json` (`turns[[start,end,speaker]]`, `model_id`, `speakers`, `skipped`, `hint`), danach `transcript_versions` (Zeile mit `words`, `stats`, `origin = asr`, `version = max + 1`).
- Code: `W/activities/transcribe.py:run_transcribe 48-99`, `run_diarize 102-145`; `W/pipeline/transcribe.py:plan_windows 78-93`, `merge_windows 111-139`, `transcribe_window 303-327`, `diarize 503-537`; Fusion `W/activities/nlp.py:run 45-116` mit `assign_speakers` (`transcribe.py 203-232`), `normalize_numbers` (196-200), `dach_nlp.detect_dialect` (246-274) und `dach_nlp.annotate` (301-322).
- Art: Modelle (faster-whisper, pyannote), deterministische Fusion. Kein Prompt, keine Policy.
- Key: ASR `derived_key(audio_key, {variant, vocab-hash, window_s, overlap_s}, "asr_v1:<model>")`, Diarisierung `derived_key(audio_key, {speakers}, "diar_v1:<model>")` (`activities/transcribe.py 25-31`). Treffer im Storage überspringen den Schritt. Jede Fusion schreibt eine neue `transcript_versions`-Zeile, auch bei unverändertem Input.
- Fehler: ASR laut (`TranscribeError` ohne konfiguriertes Modell, `ImportError` ohne faster-whisper). Diarisierung still: ohne `HF_TOKEN` oder ohne pyannote bekommt die ganze Datei den Sprecher `SPEAKER_00`, `skipped: true`, Hinweis nur im Event (`transcribe.py 454-482, 503-519`).

### 1.3 Segmentierung (Sätze, Kapitel)
- Eingabe: Wortliste der höchsten `transcript_versions.version` (`W/activities/common.py:load_transcript 87-99`).
- Ausgabe: `Sentence[]` und Kapitel `list[list[Sentence]]`, beide nur im Speicher, nie persistiert (Abschnitt 2).
- Code: `W/pipeline/segment.py:sentences_from_words 50-67`, `chapterize 94-107`, `numbered 110-112`; Grenzen `W/pipeline/dach_nlp.py:is_sentence_end 125-146`.
- Art: deterministisch. Satzende = Satzzeichen (`! ? …`, `.` außer Abkürzung, Ordinalzahl, Dezimalzahl), Pause von mindestens 0,7 s oder Sprecherwechsel. Kapitel schließen, sobald sie 240 s erreichen (`story_engine.CHAPTER_SECONDS 53`).
- Key, Fehler: keiner, keine eigene Fehlerbehandlung. `segment.candidate_windows 70-91` (Fenster 12 bis 90 s) wird nirgends aufgerufen.
- Befund 1.

### 1.4 Signale und Heatmap
- Eingabe: Audio, optional ASR-Wörter, falls `asr/<hash>.json` beim Start der Activity schon existiert (`W/activities/analyze.py:run_heatmap 80-130`).
- Ausgabe: `heatmap/<hash>.json` (`bin_s`, `n_bins`, `values`, `seeds` bis 25 mit 45 s Mindestabstand, `audio_values`, `text_included`), `wellenform/<hash>.json` (25 Werte je Sekunde, nur für die Zeitleiste), `sources.waveform_key`.
- Code: `W/pipeline/signals.py:audio_heatmap 67-81`, `text_heatmap 84-108`, `combined 123-131`, `seeds 111-120`, `to_payload 134-149`.
- Art: deterministisch. Audio 0,6 RMS + 0,4 Spectral Flux als z-Wert, begrenzt auf -3 bis 3; Text aus festen Diskursmarkern, Fragen, Zahlen; Mischung 0,5 zu 0,5. Lachen-Eingang (`laughter`) wird nirgends übergeben.
- Key: `derived_key(audio_key, {text: bool}, "signals_v2")`, Wellenform eigener Key (`analyze.py 70-77`). Der Textanteil ist Teil des Keys, der Inhalt der Heatmap nicht Teil des Keys der Kandidaten (Befund 3).
- Fehler: `fail_status=None`, die Quelle wird nicht auf `failed` gesetzt. Wellenform-Fehler nur als Warnung. Fehlt die Heatmap, läuft die Engine ohne Seeds (`_load_heat 133-142`).
- Verwendung: Seeds ordnen nur die Kapitel (`story_engine.chapter_order 333-342`). `audio_values` wirken über `audio_wert 190-226` auf den Gesamtwert und die Teaser-Wahl. Im Prompt kommt nichts davon vor (Befund 3).

### 1.5 Kandidatensuche (Vorschlag)
- Eingabe: Kapitel, `sources.brief` (`audience`, `wanted`, `exclude`, `platform`).
- Ausgabe: je Kapitel höchstens 4 Satzspannen `{first_sent, last_sent, structure, why}` (`MAX_PER_CHAPTER 51`), gesamt `report.proposals`.
- Code: `W/pipeline/story_score.py:propose 218-234`, Aufruf `story_engine.run 859-911`. Vorfilter vor der Bewertung `_vorfilter_grund 602-625`.
- Art: Sprachmodell (`LLM.structured`, `max_tokens 2000`, `temperature 0.2`, `W/providers_llm.py 53-131`). Provider `local-heuristic` antwortet deterministisch aus dem gerenderten Prompt (`W/heuristic_llm.py:propose_moments 174-233`, höchstens 3 Momente, Länge aus Wortzahl geschätzt, 2,5 Wörter/s).
- Prompt: `propose_moments_v1` (kennt weder Policy noch Länge noch Moment-Typen, RESEARCH Abschnitt 2, Absatz "Weitere neue Befunde"), System `system_editor_v1`. Policy: nur die Heuristik liest `laenge.*` und `moment_typen` (Abschnitt 5).
- Key: der Vorschlag selbst wird nicht gecacht (`LLM(...)` ohne Redis, `analyze.py 339`); der Cache liegt eine Ebene höher (1.8).
- Fehler: laut. Ein Vorschlag mit Index außerhalb des Kapitels oder `first > last` wird still gestrichen (`story_score.py 230-233`).
- Befund 3, 11.

### 1.6 Bewertung (Rubrik, Gates, Heilung, Teaser)
- Eingabe: ein Vorschlag, die Satzliste, Wortliste, Heatmap.
- Ausgabe: `CandidateResult` (Abschnitt 2) oder `{"reason": too_short | too_long | *_after_repair, ...}` in `report.discarded` (`story_engine.evaluate_span 683-796`).
- Ablauf in `evaluate_span`:
  1. `story_score.score_with_repair 376-392`: bewertet, erweitert bei `needs_earlier_context` oder `unresolved_references` um einen Satz nach vorn und bei `ends_before_answer` um einen Satz nach hinten, höchstens 2 Runden (`MAX_REPAIR_ROUNDS 52`), danach `repair_failed`. Jede Runde ist ein neuer Modellaufruf.
  2. `kontext_verlaengern 628-680`: wenn eines der Enden-Gates (`fidelity`, `sentence_boundaries`, `no_open_loop`, `ENDE_TORE 49`) reißt, werden bis zu `kontext_zugabe_saetze` (2) Sätze angehängt, solange `kontext_zugabe_s` (7 s) und `hart_max_s + zugabe` nicht überschritten sind und danach alle fünf Gates bestehen. Danach wird nicht neu bewertet.
  3. Längenprüfung `_length_reason 585-599`: `hart_min_s 18`, `hart_max_s 70` (+ 7 s nur nach Heilung).
  4. `deterministic_gates 453-461`: `standalone` (aus den drei Modell-Flags), `fidelity` (nur `ends_before_contrast`, 3 Folgewörter), `sentence_boundaries` (Satzzeichen am Wort vor dem Start und am letzten Wort, `…` zählt nicht), `verb_bracket` (spaCy, sonst `passed: true, available: false`), `no_open_loop` (`OPEN_LOOP_END`).
  5. Story-Graph `story_graph.find_later_qualifications 57-82` (Kontrastmarker plus lexikalische Überlappung ab 0,15 im 60-s-Folgefenster) und je Treffer `story_graph.confirm 90-97`; ohne Urteil `confirmed = null`.
  6. Teaser `teaser_satz 255-292`: stärkster Satz (Moment-Typ-Bonus plus Klang) aus Satz 2 bis zum Beginn des letzten Viertels, höchstens 6 s, Vorsprung mindestens 2,0 gegenüber dem ersten Satz, kein Rückverweis-Pronomen am Anfang. Nur wenn `compose.Composition.validate` den Teaser akzeptiert (`compose.py 48-67`), wird er als erstes Segment `role: teaser` vorangestellt und `structure = payoff_first`.
  7. `total = policy_total 295-327`: `Policy.gesamtwert(rubric_points) * (1 - laenge_abzug(abspiel_dauer))`, danach Klang-Faktor `(1 - w) + w * 2 * klang` mit `w = 0,15`. Skala nominal 0 bis 14 (`punkte_gesamt`), nicht 0 bis 10; durch den Klang-Faktor sind bis 16,1 möglich. Die Gewichte aus `resolve_weights` (`learned_weights`) gehen nur in `rubric.scores[k].weight` ein, nicht in `total` (Befund 12).
- Art: Sprachmodell für Rubrik und Story-Graph-Bestätigung, alles andere deterministisch.
- Prompt: `score_clip_v2` (sieben Kriterien, Skala 0 bis 2, Platzhalter `{policy}`), `story_graph_confirm_v1`. Policy: Abschnitt 5.
- Key: keiner je Spanne (kein Redis, `LLM(...)` in `analyze.py 339`).
- Fehler: laut bei fehlender Policy (`PolicyError`) und bei Antworten ohne jede Punktzahl (`_harmonise 301-303`). Still: fehlendes spaCy (`verb_bracket`), Heuristik ohne Story-Graph-Urteil, Rubrikwerte, die geraten werden müssen (`rubric_guessed`, nirgends gespeichert). Die Belegprüfung `_evidence_grounded 244-252` wird berechnet (`ungrounded_evidence`, `story_score.py 369`), aber von keinem Code gelesen oder gespeichert. Gleiches gilt für `needs_human` (368).
- Befund 2, 5, 6, 11, 12.

### 1.7 Auswahl (`select_best`)
- Eingabe: alle bewerteten Spannen eines Quellvideos (`raw`), Obergrenze `MAX_CANDIDATES 20`.
- Ausgabe: `report.candidates` nach Startzeit sortiert, `report.discarded` mit Gründen `gate`, `overlap`, `limit` (`story_engine.select_best 818-844`). `report.verworfen` hält die verworfenen Kandidaten, wird aber weder in `to_json` (131-144) noch in die Datenbank geschrieben.
- Art: deterministisch. Sortierung `(gate_passed, total, -start_s)` absteigend. Wer ein Gate gerissen hat, wird verworfen (kein Sortiereffekt mehr). Überdeckung `gemeinsamer_anteil` (Anteil am kürzeren) ab 0,4 gilt als Dublette. Dublette `(first_sent, last_sent)` schon in `run 900-905`.
- Policy: keine (`bewertung.modus`, `schwelle_*` werden nicht gelesen).
- Folge: in der Tabelle `candidates` steht nie ein Kandidat mit `gate_passed = false`. Nur eine Web-Revision kann das ändern (1.8).
- Befund 4.

### 1.8 Persistenz, menschliche Freigabe, `auto_create_clips`
- Eingabe: `DetectReport` (Cache oder frischer Lauf).
- Ausgabe: `candidates`-Zeilen (`version = 1`), je Kandidat höchstens ein `clips`-Zeile (`status draft`), `candidates.human_verdict = accepted`, `decision_log`-Zeilen, Outbox `candidates_ready`, `sources.status = ready`.
- Code: `W/activities/analyze.py:run_detect_candidates 319-402`, `_write_rows 189-239`, `auto_create_clips 263-316`, `_drop_stale_auto_rows 179-186`.
- Cache-Key (`candidates_key_for 145-166`): `derived_key("transcript/<tv_id>", {transcript_version, brief, prompt_versions, provider, model, weights, engine, policy}, "candidates_v1")`. Nicht enthalten: Heatmap-Inhalt, Transkriptinhalt (nur die Versionsnummer), Policy-Inhalt (nur der Name `clip_policy_v1`, `policy_version()` ist fest). `PolicyError` wird beim Key still zu `"unbekannt"` (153-155); davor wirft allerdings `resolve_weights` über `story_score.weights` schon (`analyze.py 334`).
- Idempotenz: Re-Run löscht Automatik-Clips im Status `draft` samt Automatik-Kandidaten und Kandidaten ohne Urteil; beurteilte Zeilen bleiben, ein neuer Kandidat, der einen überlebenden zu mindestens 0,4 überdeckt, wird nicht geschrieben (`_write_rows 200-214`). Ein Fenster (Zehntelsekunde) mit bestehendem Clip bekommt keinen zweiten (`_window 242-244`).
- Menschliche Freigabe, zwei Ebenen:
  - Kandidat: `auto_create_clips` setzt `human_verdict = accepted`, `verdict_reason = "automatisch angenommen (ohne Auswahlschritt)"`, `verdict_by = NULL` (305-312). Der manuelle Weg bleibt in `apps/web/app/api/projects/[id]/candidates/[cid]/verdict/route.ts` (legt je gewählter Plattform einen Clip an und sendet `approve`).
  - Clip: `clips.review` (`offen` | `bereit` | `verworfen`, Migration 0012) und Gastfreigabe. Erst diese Ebene sperrt, aber nur das Veröffentlichen (1.14). Der Worker prüft beim Veröffentlichen zusätzlich `human_verdict = accepted` (`W/activities/publish.py:check_gates 101-118`), was für Automatik-Clips immer erfüllt ist.
- Clip-Felder: `aspect` fest `9:16`, `platform = destination` aus `brand_profiles.default_platform`, sonst `reels` (`clip_platform 247-260`), `composition = candidate.segments`, `title_card = rubric.suggested_title_card`, `ad_label` aus `brief.is_ad` und Land.
- Fehler: laut, die Schritte stehen im selben `events.step`. `decision_log.record_detect_report` ist nicht abgefangen.

### 1.9 Komposition und Schnittplan
- Eingabe: `clips.composition` (Segmente in Quellzeit, Abspielreihenfolge), Wortliste.
- Ausgabe: `render_plan` (`render_plan_v1`, Abschnitt 2), `compose.remap_words` (Wörter auf der Ausgabe-Timeline).
- Code: `W/pipeline/compose.py:Composition 33-67`, `remap_words 86-99`; `W/pipeline/render_plan.py:normalize_segments 159-176`, `build_plan 183-258`, `plan_hash 261-264`.
- Art: deterministisch. Segmente werden auf ms gerundet, aneinanderliegende Segmente gleicher Rolle (Lücke unter 1 ms) verschmelzen, Länge 0 oder negativ wirft `ValueError`.
- Key: `plan_hash(plan, hook_version, transcript_version)`, 16 Hex-Zeichen, bildet `renders/<clip_id>/<hash>.*`. Stimmt `clips.file_key` mit dem Hash überein und existiert die Datei, wird nicht neu gerendert (`W/activities/render.py 739-747`).
- Nicht gelesen: Zeitmarken- und Effekt-Logik (`W/pipeline/effekte.py`, `musik.py`), ungeprüft.
- `fidelity_warnings` am Clip: `render.py:fidelity_warnings 489-504` ruft `fidelity.check_cut` für Kandidatenbereich gegen die Body-Segmente. Bei der Automatik (ein Body-Segment, kein Weglassen) bleibt die Liste leer; sie wirkt nur bei Handschnitt.
- Befund 5, 8.

### 1.10 Copy (Hooks, Claim-Check, Linter)
- Eingabe: Text aller Segmente einschließlich Teaser (`render.py:clip_words 480-486`), `BrandProfile` (`address`, `country`, `gender_mode`, `banned_phrases`, `protected_terms`, `tone_adjectives`, `platform = destination`).
- Ausgabe: `hook_versions` Version 1 (`origin llm`): fünf Varianten `{pattern, spoken, onscreen, lint_notes, claim_issues}`, `spoken_hook`, `onscreen_hook`, `pattern`, `post_captions` je `tiktok|reels|shorts|linkedin`, `cta`, `lint_notes`, `claim_issues`, `model_id`, `prompt_version`.
- Code: `W/pipeline/copy_engine.py:write_copy 264-316`, `generate_variants 127-153`, `select_variant 156-158`, `generate_post_caption 203-224`, `languagetool_check 227-261`; `W/pipeline/copy_de.py:lint 67-110`; `W/pipeline/fidelity.py:hook_claim_check 61-71`; Aufruf `W/activities/render.py 612-637`.
- Art: Sprachmodell, danach deterministisch. Linter korrigiert nur Eindeutiges (Em-Dash, `ß` in CH, Genderzeichen), alles andere sind Hinweise. Claim-Check: jede Zahl und jeder von zehn Superlativen im Hook muss als Teilstring im Clip stehen. Auswahl: erste Variante ohne Claim-Treffer, sonst Variante 1 mit Treffern. Wortlimits (12 gesprochen, 9 im Bild) und Lint-Verstöße disqualifizieren nicht.
- Prompt: `hooks_v1`, `post_caption_v1`, System `system_editor_v1`. Policy: keine.
- Key: nur "existiert eine `hook_versions`-Zeile?" (`_load_hook 431-445`). Das Prompt-Ergebnis selbst wird nicht gecacht. Es werden immer vier Post-Captions erzeugt, auch für ein einziges Ziel (`copy_engine.write_copy 286-291`).
- Verwendung: nur `onscreen_hook` geht in den Plan (Hook-Overlay, 3,0 s; Standard an für `tiktok|reels|shorts`, aus für `linkedin`, `render_plan.py 35, 55-59`). `spoken_hook` wird gespeichert und nirgends verwendet (Befund 7). `thompson_order` wird im Render nicht übergeben (`pattern_order=None`, `render.py 629`). `copy_de.generate_hooks` (Zweitpfad mit Schema-Schlüssel `hooks`) wird nie aufgerufen.
- Fehler: Lint, Claim-Check, LanguageTool laut im Ergebnis, nie fatal. Kein Hook-Ergebnis (`variants` leer) wirft `RuntimeError`, der Render scheitert. `decision_log`-Fehler sind abgefangen (`render.py 636-637`).

### 1.11 Captions
- Eingabe: `out_words` (Ausgabe-Timeline), Preset, `caption_style` (Marke und Clip), `caption_text_field` (`text` | `text_norm`).
- Ausgabe: `caption_versions` (`cards`, `ass_key`, `srt_key`, `cps_warnings`, `origin auto`), Dateien `.ass`, `.srt`, `.vtt`.
- Code: `W/pipeline/captions_de.py:build_cards 438-488`, `to_ass 554-598`, `to_srt 636-646`, `cards_for 675-697`, `cps_warnings 491-516`; Presetwahl `W/activities/render.py:caption_preset_for 517-530` (Clip-Stil, dann das Preset des Markenprofils für die Standardplattform, sonst im Hochformat wortweise).
- Art: deterministisch. Karten brechen an Satzzeichen, Konjunktionen, Pausen über 0,4 s und bei überlangen Wörtern; Silbentrennung per pyphen. Lesetempo 17 Zeichen/s nur für Karten mit mindestens 2 Wörtern.
- Key: über den Plan-Hash (die angewendeten Preset-Werte stehen im Plan, `render_plan.caption_block 62-108`).
- Fehler: Fehlt libass oder die Schriftdatei, wird der Schritt übersprungen und als Hinweis vermerkt (`render.py` Docstring 11-14); die technische Prüfung stuft "keine Untertitel eingebrannt" dann als `fehler` ein (1.13). Befund 9.

### 1.12 Reframing
- Eingabe: Quelldatei, Segmente, Wörter (Sprecher), `clips.speaker_positions`, `reframe_override`, `zeitmarken`.
- Ausgabe: `ReframeResult` (`strategy` `talking_head|two_speakers|neutral|slide_pip`, `detector`, `positions`, `shots[]` mit `start`, `end`, `crop_*`, `layout`, `grund`, `notes`), im Plan als `reframe` und `shots`.
- Code: `W/pipeline/reframe.py:plan_reframe 801-948`, `plan_shots_aus_zielen 653-719`; Messung `W/pipeline/tracking.py` (nur überflogen, im Detail ungeprüft).
- Art: deterministisch (YuNet-Gesichtsdetektion, Mundbewegung, Folienerkennung mit OpenCV). Kein Prompt, keine Policy.
- Key: `REFRAME_VERSION = "reframe_v2"` im Plan, damit im Hash.
- Fehler: still zurückgefallen. Fehlt YuNet-Modell oder OpenCV, oder wirft die Detektion, läuft `neutral` (mittiger Crop) mit einem Hinweis in `notes` (`reframe.py 868-872`). Geometrie wird aus der echten Datei gelesen, Abweichung zur Datenbank nur als Warnung (`render.py 644-649`). Befund 10.

### 1.13 Render und technische Prüfung
- Eingabe: `render_plan`, Quelldatei, `.ass`, optional Font, Logo, Musik.
- Ausgabe: `renders/<clip_id>/<hash>.{mp4,srt,vtt,jpg,ass,streifen.jpg}`, `clips` (`file_key`, `duration_s`, `loudness`, `provenance`, `render_plan`, `cps_warnings`, `fidelity_warnings`, `export_checks`, `status`, `render_error`).
- Code: `W/pipeline/render.py:render_from_plan 531-601`, `input_args 214-228`, `audio_chain 237-269`, `bitstrom_pruefen 707+`; `W/pipeline/ausgabe_pruefung.py:pruefen 85-247`; Ablauf `W/activities/render.py:_render 593-941`.
- Art: deterministisch (ffmpeg: H.264 High, CRF 19, AAC 192k, Loudnorm zweistufig, Preset `master` -16 LUFS / -1,5 dBTP). Ein beschädigter Bildstrom löst genau einen zweiten Render aus (`render.py 767-783`).
- Prüfung nach dem Render: Datei, Bild, Ton, Dauer, Auflösung, Schwarzbild, Pegel, Spitze, Untertitel, Schrift mit Schwellen aus `P/schema/ausgabe_regeln_v1.json` (Abschnitt 3). `status = failed` und `render_error`, sobald ein Befund `fehler` ist; die Datei bleibt trotzdem im Storage (`render.py 871-877`). `render.regression_checks 739` und `DURATION_TOLERANCE_S` sind ungenutzt.
- Fehler: laut (`clips.status = failed`, `render_error`, Event `failed`). Still: Musik fehlt, Effekte unlesbar, Marken-Font fehlt, c2patool fehlt (`provenance.c2pa = skipped`), Filmstreifen fehlt, `drawtext` fehlt (Titelkarte und Hook-Overlay fehlen dann ohne Fehler, nur Hinweis in `notes`).
- Policy: keine. Prompts: keine.

### 1.14 Ausgabeentscheidung
- Eingabe: Prüfstand des Clips (`A/clips/pruefstand.ts`: `redaktion`, `datei`, `befunde`), `clips.export_checks`, Gast- und Vertragsstatus.
- Ausgabe: `{erlaubt, gruende[]}` für `herunterladen`, `veroeffentlichen`, `eintragen` (`A/clips/ausgabe.ts:ausgabe 115-140`), Regelkatalog `P/schema/ausgabe_regeln_v1.json`.
- Art: deterministisch, einzige serverseitige Stelle (Download-Route und `A/publishing/gates.ts`).
- Wirkung: `inhalt_fehler` (Treuebefund mit Schwere `fehler`, also `negation_removed`, `ends_before_contrast`, `joined_statements`) und `technik_fehler` sperren das Veröffentlichen, nicht den Download. `nicht_freigegeben` verlangt `clips.review = bereit` oder Gastzusage, nur fürs Veröffentlichen. Es gibt keine Regel zu `humor`, `sensitive_topic` oder `claim` (Abschnitt 7, Beobachtung c).
- Fehler: eine fehlende Prüfung (`technik = null`, alte Videos) sperrt nichts (`ausgabe.ts 79-85`).

### 1.15 Decision Log und Lernen
- Eingabe, Ausgabe: `decision_log`-Zeilen `candidate_proposed`, `candidate_scored` (aus `record_detect_report`), `hook_variant_shown`, `hook_selected`, `reframe_strategy`, `publish`, vom Web `candidate_verdict` (`W/decision_log.py 30-193`). Lernschleife `W/learning.py:fit_rubric_weights 106-137`, `update_brand_weights 172-191`: Ridge-Fit der fünf Alt-Scores auf `0,6 * Urteil + 0,4 * Reward`, ab 20 Entscheidungen, Gewichte auf 0,05 bis 0,5 begrenzt, Ergebnis in `brand_profiles.learned_weights`.
- Art: deterministisch, nächtlicher Workflow (`LearningWorkflow`, nur im Temporal-Betrieb).
- Wirkung: `learned_weights` ändern den Cache-Key und `rubric.scores[k].weight`, aber nicht `total` und damit nicht die Auswahl (Befund 12). Die Lernzeilen lesen `human_verdict is not null` ohne Filter auf `verdict_by` (`learning.py 38-41`), zählen also auch die automatisch angenommenen Kandidaten als `accepted`. `learning.thompson_order`, `update_hook_stats`, `dach_nlp.auto_remove_ranges`, `compose.from_keep_ranges` und `story_engine.weighted_total` haben keinen Aufrufer im Produktionspfad (per Textsuche im Quelltext geprüft).
- Fehler: im Render abgefangen, in `detect_candidates` laut.

### 1.16 Eval
- Eingabe: Datenbank (letzte `transcript_versions.words`, alle `candidates` einer Quelle), optional `workers/eval/clips/*.json` (Referenzstellen).
- Ausgabe: Konsolentabelle und JSON: Grenzprüfung je Kandidat (`satzanfang`, `satzende`, `beginnt_mit_rueckverweis`, `verneinung_am_rand`, `laenge_s`), Trefferquote und Precision@k (Abdeckung der Referenzstelle mindestens 0,5).
- Code: `workers/eval/clip_eval.py:check_boundaries 198-249`, `main 353-431`. Aufruf `.venv/bin/python -m eval.clip_eval --titel "<Teil des Titels>"`.
- Grenzen der Messung: liest nur `candidates` (also nach `select_best`, ohne `discarded`), prüft Satzgrenzen mit `dach_nlp.is_sentence_end` statt mit dem Wortlaut-Gate der Engine, und sieht weder Hooks noch Captions noch das gerenderte Video. Der Referenzsatz `eval/clips/referenzsatz_v1.json` wurde nicht gelesen, ungeprüft (RESEARCH Abschnitt 2 nennt ihn "nicht belastbar").

## 2. Datenstrukturen

**Wort** (JSON in `transcript_versions.words`, erzeugt in `transcribe.py:Word 48-57`, ergänzt in `activities/nlp.py`):
`text`, `start`, `end` (Sekunden Originalzeit, 3 Dezimalen), `prob`, `speaker`, `filler` (`hard|soft|backchannel|modal_keep|null`), `negation` (bool), `sentence_idx`, optional `text_norm` (nur bei Schweizerdeutsch).

**Satz** (`segment.Sentence 18-33`, nur im Speicher): `idx`, `text`, `start` (Start des ersten Wortes), `end` (Ende des letzten Wortes), `speaker` (des ersten Wortes), `word_range` (inklusive Wortindizes). `Wort.sentence_idx` und `Sentence.idx` kommen aus derselben Funktion mit derselben Schwelle 0,7 s und stimmen deshalb überein, solange die Wortliste gleich bleibt. Für ein im Web bearbeitetes Transkript ist das ungeprüft (`A/transcript/sentences` nicht gelesen).

**Kapitel**: `list[Sentence]` mit mindestens 240 s Länge (letztes kürzer), nur im Speicher. Nur die Anzahl steht im Bericht.

**Kandidat** (`candidates`-Zeile = `story_engine.CandidateResult 76-106`):

| Feld | Inhalt |
|---|---|
| `segments` | `[{start, end, role}]` mit `role` `teaser` oder `body` in Abspielreihenfolge, Originalzeit |
| `start_s`, `end_s`, `first_sent`, `last_sent` | Grenzen des Body, Satzzeiten auf 3 Dezimalen |
| `structure` | Vorschlag des Modells oder `payoff_first` bei Teaser |
| `rubric` | `contract`, `text`, `speakers`, `duration_s` (Quellspanne), `scores` (fünf Alt-Schlüssel: `value` 0 bis 10, `weight`, `evidence`), `rubric_points` (sieben Policy-Schlüssel, Skala 0 bis 2, Bruchteile erlaubt), `policy_version`, `laenge_abzug`, `abspiel_dauer_s`, `teaser_satz`, `klang`, `unresolved_references`, `needs_earlier_context`, `ends_before_answer`, `is_humor`, `sensitive_topic`, `suggested_title_card`, `repair` (`rounds`, `expanded_front`, `expanded_back`, `failed`), `kontext_zugabe`, `proposal_why`, `parent_id` |
| `gates` | `standalone`, `fidelity`, `sentence_boundaries`, `verb_bracket` (mit `available`), `no_open_loop`, je `{passed, detail}` |
| `story_graph_flags` | `[{sentence_idx, seconds_after, marker, text, overlap, confirmed, reason, repair, suggestion}]` |
| `risk_flags` | Teilmenge von `humor`, `sensitive_topic`, `claim`, `heuristic_only`. `ad` wird nirgends gesetzt |
| `total`, `gate_passed`, `why` | `total` auf der Policy-Skala, nominal 0 bis 14, mit Klang bis 16,1 (1.6); `gate_passed` ist in der Tabelle immer `true` (1.7) |
| `model_id`, `prompt_version` | Rubrik-Modell und `score_clip_v2`. Die Versionen der anderen beiden Stufen stehen nur im Event und im Decision Log |
| `policy_version` | nur als `rubric.policy_version`, keine eigene Spalte |

**Clip** (`clips`-Zeile): vom Worker angelegt `source_id`, `candidate_id`, `platform`, `destination`, `aspect`, `composition` (Kopie von `candidate.segments`), `title_card`, `ad_label`, `status`. Vom Render geschrieben: `file_key`, `srt_key`, `vtt_key`, `poster_key`, `filmstrip_key`, `duration_s`, `width`, `height`, `fps`, `loudness`, `provenance`, `render_plan`, `cps_warnings`, `fidelity_warnings`, `speaker_positions`, `export_checks`, `render_error`, `rendered_at`. Von Hand gesetzt: `review`, `reframe_override`, `caption_style`, `zeitmarken`, `effekte`, `musik`.

**Render-Plan** (`render_plan_v1`, `render_plan.py:build_plan 183-258`): `contract`, `platform`, `aspect`, `output{width,height,fps}`, `segments[]`, `filler_cuts` (immer `false`), `reframe`, `shots[]`, `motion{zoom_to, min_shot_s}`, `effekte[]`, `musik`, `captions{...}` (Preset-Werte, Safe Zone, `cards`), `title_card{text,seconds 2.5}`, `hook_overlay{text,seconds 3.0}`, `audio{preset,lufs,true_peak,micro_fade_ms 20}`, `zeitmarken[]`, `brand{...}`, `sources{storage_key, transcript_version, hook_version, candidate_id}`, `versions`.

**Originalzeit und Clipzeit**

| Originalzeit (Quellvideo) | Clipzeit (Ausgabe-Timeline) |
|---|---|
| Wörter, Sätze, `candidates.segments`, `start_s`, `end_s`, `clips.composition`, `render_plan.segments`, `render_plan.shots`, `clips.zeitmarken` (Quellzeit, Migration 0011) | `compose.remap_words` (`out_words`), `caption_versions.cards`, `.ass/.srt/.vtt`, `clips.effekte`, Titelkarte und Hook-Overlay ab 0, `duration_s` |

Nicht getrennt gespeichert: Es gibt kein Feld "Segmentgrenze in Clipzeit". Wer sie braucht, rechnet sie aus den kumulierten Längen der Plan-Segmente (`plan_duration 179-180`). `candidates.start_s/end_s` beschreibt nur den Body, nie den Teaser.

## 3. Zeitstempel

**Herkunft.** ASR-Wortzeiten von faster-whisper (`word_timestamps=True`, `vad_filter=True`), je Fenster von 600 s mit 20 s Überlappung (`config.py`, `transcribe.py:plan_windows 78-93`), in Quellzeit verschoben und auf 3 Dezimalen gerundet (`transcribe.py 325`). Die Naht wird an der längsten Pause im Überlappungsbereich gelegt (`_best_cut 100-108`). Der Gladia-Fallback (`_transcribe_gladia 379-436`) ist ungeprüft.

**Wo gerundet oder verschoben wird.**

| Stelle | Wirkung |
|---|---|
| `evaluate_span 719-720, 781-782` | Segment- und Kandidatenzeiten `round(..., 3)`; Schnitt exakt auf Wortgrenzen, ohne Vor- und Nachlauf |
| `normalize_segments 159-176` | `round(..., 3)`, Verschmelzen von Segmenten ohne Lücke |
| `render.input_args 214-228` | je Shot und je Segment ein eigener Input mit `-ss {start:.3f} -t {dauer:.3f}`, Video und Audio getrennt |
| `render.audio_chain 252-260` | 20 ms Fade-in und Fade-out innerhalb jedes Segments. Die ersten und letzten 20 ms des Segments werden abgesenkt, es wird nichts davor oder danach zugegeben |
| `compose.LEAD_IN_S 0,05`, `LEAD_OUT_S 0,08`, `MERGE_GAP_S 0,15` | nur in `from_keep_ranges`, das nie aufgerufen wird (Befund 8) |
| `compose.remap_words 86-99` | Wort kommt nur hinein, wenn es vollständig im Segment liegt (`start >= seg.start` und `end <= seg.end`, ohne Epsilon); Teaser-Wörter erscheinen doppelt; `round(..., 3)` |
| `captions_de._fmt_t 519-522` | ASS-Zeit auf Hundertstel; Randfall `59.996` ergibt `0:00:60.00` (ausgeführt; Verhalten von libass ungeprüft) |
| `captions_de._srt_t 649-654` | SRT und VTT auf ms |
| `captions_de.to_ass 575-598` | ein Event je Karte, bei Wort-Highlight ein Event je Wort von `word.start` bis `word.end`, keine Überbrückung der Lücken (Befund 9) |
| `reframe.plan_shots_aus_zielen 653-719` | Shotgrenzen werden in das Segment geklemmt, lückenlos; Mindestdauer 1,2 s (`MIN_SHOT_S 38`, `tracking.MIN_ZIEL_S 78`) |
| `signals`, `story_engine.audio_wert 190-226` | Heatmap in 1-s-Bins, `int(t / bin_s)`; die Bins des Abschnitts sind `[int(start), int(end) + 1)` |

**Toleranzen.**

| Wert | Quelle |
|---|---|
| Satzende bei Pause ab 0,7 s | `segment.py 14`, `dach_nlp.py 125` |
| Kartenumbruch bei Pause über 0,4 s | `captions_de.py 483` |
| Teaser höchstens 6,0 s, aus dem Body, ein Sprecher | `compose.py 15, 48-67`, `P/editorial/clip_policy_v1.yaml:hook_vorziehen` |
| Dublette ab Überdeckung 0,4 des kürzeren; Clip-Fenster auf 0,1 s gerundet | `story_engine.py 67`, `analyze.py 47` |
| zusammengesetzte Aussage ab 20 s Abstand im Original | `fidelity.py 23` |
| Dauer des Videos gegen den Plan: Hinweis ab 0,3 s, Fehler ab 1,0 s | `ausgabe_regeln_v1.json` (`dauer`) |
| Pegel: Hinweis ab 2,0 LU, Fehler ab 4,0 LU; Spitze: ab 0,5 dB, Fehler ab 2,0 dB; Schwarzbild: ab 0,5 s, Fehler ab 1,0 s | `ausgabe_regeln_v1.json`, `render.BLACK_MIN_S 49` |
| Treffer im Eval ab Abdeckung 0,5 | `clip_eval.py` (`--schwelle`) |

## 4. Lokaler Worker gegen Temporal-Container

| Aspekt | Lokal (`W/local_worker.py`) | Temporal (`W/worker.py`, `W/workflows/clip_project.py`, `workers/Dockerfile`, `infra/docker-compose.yml`) |
|---|---|---|
| Start | `python -m chopstr_worker.local_worker [--once]`, Polling alle 3 s | `python -m chopstr_worker.worker --queues cpu`, `gpu` oder `cpu,gpu` |
| Quell-Ablauf | sechs Schritte nacheinander (`SOURCE_PIPELINE 48-55`), Abbruch beim ersten Fehler | `transcribe_de`, `diarize`, `heatmap` parallel (`clip_project.py 87-92`) |
| Heatmap | läuft nach der ASR, Textanteil enthalten | läuft parallel, der Textanteil fehlt, wenn die ASR beim Start noch nicht fertig ist (`analyze.py 86-92`) |
| Wiederholung | keine; gescheiterte IDs stehen nur im Speicher des Prozesses (`failed` Set 97-98) | IO 5, GPU 3, LLM 3 Versuche; nicht wiederholt: `ResidencyError`, `SchemaError`, `TranscribeError`, `NotImplementedError`, `LookupError` (`clip_project.py 25-29`). andere Fehler, etwa `PolicyError`, werden also wiederholt |
| Render-Auslöser | jeder Clip `draft` mit Kandidat `accepted` wird gerendert (`SQL_PENDING_CLIPS 59-62`), also alle Automatik-Clips | nur das Signal `approve(candidate_id, destination)` (`clip_project.py 59-61, 108-141`). Im Web senden es nur `verdict`-, `render`- und `fassungen`-Route. Nichts im Worker sendet es nach `auto_create_clips`: Automatik-Clips bleiben `draft`, bis jemand rendert (aus dem Code gelesen, Laufzeit ungeprüft) |
| Freigabe-Warten | keines | bis 14 Tage (`REVIEW_TIMEOUT`), dann Ende |
| LLM-Provider | `local-heuristic` per `scripts/local_env.sh` | `bedrock-eu` Standard (`config.py 74`, `docker-compose.yml 164`) |
| Pfade | `prompts_dir()` und `policy_dir()` suchen aufwärts nach `packages/prompts`, `packages/editorial` (`editorial.py 38-48`, `prompts.py 22-32`); `ausgabe_regeln` und `caption_fonts.json` relativ zum Monorepo | `workers/Dockerfile 14-18` kopiert `packages/prompts`, `workers/chopstr_worker`, `workers/eval`, `workers/fonts`. Es fehlen `packages/editorial`, `packages/schema`, `packages/design`. `docker-compose.yml` setzt kein `EDITORIAL_DIR`, `CHOPSTR_AUSGABE_REGELN` oder `CHOPSTR_CAPTION_FONTS` |
| Folge im Image | Policy vorhanden | `editorial.load()` wirft `PolicyError` in der Kandidatensuche; `ausgabe_pruefung.regeln()` wirft `FileNotFoundError` erst nach dem Encode (aus dem Code abgeleitet, im Container nicht ausgeführt). Befund 13 |
| Python-Pakete | `workers/.venv` (ausgeführt): kein spaCy, kein OpenCV, `workers/models/` enthält nur `.gitkeep`. Folge: `verb_bracket` meldet `available: false`, Reframe `neutral` | CPU-Image `[nlp]`: spaCy ohne Sprachmodell (`nlp()` liefert `None`), kein OpenCV (`vision`), kein faster-whisper, kein pyannote; GPU-Image `[asr,nlp]` ohne `vision`. `docker-compose` lässt den einen `worker` mit CPU-Image beide Queues bedienen: ASR bräuchte `faster_whisper` (`transcribe.py 278-287`), das dort fehlt |
| ffmpeg | `imageio-ffmpeg` mit libass und drawtext (`local_env.sh`) | Debian-ffmpeg (`Dockerfile 7-9`), Fähigkeiten über `render.capabilities()` |
| Speicher | lokaler Ordner (`S3_ENDPOINT` leer) | S3 oder MinIO |
| Löschen, Veröffentlichen, Outbox, Lernen | im selben Poll (`process_deletions`, `process_publications`, `process_outbox`) | eigene Workflows und Schedules (`--ensure-schedules`) |

## 5. Gelesene und ungelesene Policy-Schlüssel (`P/editorial/clip_policy_v1.yaml`)

Geladen und geprüft wird immer Version 1 (`editorial.POLICY_VERSION 26`; das YAML-Feld `version` wählt nichts). `_pruefe 279-293` verlangt die Abschnitte aus `PFLICHTFELDER 28-31`, Gewichtssumme 1,0 und aufsteigende Längengrenzen. Spalte "Wo" gilt für den Produktionspfad mit Sprachmodell; "H" = nur der Heuristik-Provider liest den Schlüssel (`heuristic_llm.py`).

| Schlüssel | Gelesen | Wo |
|---|---|---|
| `version` | ja | `policy_version()` Kennung, `story_score.py 371` |
| `stand` | nein | nur in `Policy.stand` abgelegt |
| `laenge.ziel_s` | H und Prompt | `heuristic_llm.py 188`, `editorial.als_prompt_text 260` |
| `laenge.gut_von_s`, `gut_bis_s` | ja | `laenge_abzug 136-144` → `story_engine.py 318, 753`; H `456-457`; Prompt |
| `laenge.hart_min_s`, `hart_max_s` | ja | `story_engine._length_reason 585-599`, `laenge_abzug`; H `188` |
| `laenge.kontext_zugabe_s`, `kontext_zugabe_saetze` | ja | `story_engine.py 592, 620, 653` |
| `rubrik.skala_max` | ja | `story_score.py 138, 307-328`, `editorial.gesamtwert 198` |
| `rubrik.kriterien[].schluessel`, `frage`, `gewicht` | ja | Antwortschema `story_score.rubric_schema 121-153`, `gesamtwert 190-198`, `legacy_weights 161-173` |
| `rubrik.kriterien[].null_punkte`, `zwei_punkte` | Prompt | `editorial.py 265-266` |
| `rubrik.kriterien[].herkunft`, `hinweis` | nein | nur im `Kriterium`-Objekt |
| `bewertung.punkte_gesamt` | ja | `gesamtwert 198` |
| `bewertung.modus` | nur Prüfung | `_pruefe 292`; die Eigenschaft `sperrt` hat keinen Aufrufer, `sperren` würde nichts ändern |
| `bewertung.schwelle_schneiden`, `schwelle_verwerfen` | nein | Eigenschaften ohne Aufrufer |
| `moment_typen[].marker`, `marker_regex`, `braucht_audio`, `bonus` | ja | `typen_im_text 216-219`, `story_engine.satz_staerke 229-252` (Teaser), H `154, 473` |
| `moment_typen[].name`, `hebel` | Prompt, H | `editorial.py 270`, `heuristic_llm.py 219` |
| `moment_typen[].schluessel` | ja | H `TYP_WIRKT_AUF 75-82` |
| `einstieg.pronomen` | ja | `story_engine.py 244` (Teaser-Eignung), H `307` |
| `einstieg.keine_pronomen_ohne_bezug`, `keine_gastgeberfrage`, `einleitungen_kappen`, `einleitungsfloskeln` | H | `heuristic_llm.py 279, 307, 313, 340` |
| `einstieg.nie_mitten_im_satz`, `nie_in_selbstkorrektur` | nein | |
| `ausstieg.satz_zu_ende`, `vor_der_abschwaechung`, `abschwaechung_marker` | H | `heuristic_llm.py 413, 419` |
| `ausstieg.verbklammer_nicht_trennen` | nein | das Gate ist fest verdrahtet (`story_engine.py 360-373`) |
| `zusammenhang.*` (`ein_zusammenhaengender_abschnitt`, `mindest_dichte`, `max_gedanken`) | nein | Eigenschaft `zusammenhang` ohne Aufrufer |
| `audio.in_bewertung_verwenden`, `audio.gewicht` | ja | `policy_total 323-326` |
| `audio.merkmale.*` | nein | `lachen`, `applaus`, `pause_vor_aussage`, `energie_anstieg` stehen nur in der Datei |
| `hook_vorziehen.aktiv`, `mindest_vorsprung`, `max_teaser_s`, `nicht_aus_letztem_anteil` | ja | `teaser_satz 255-292`; `compose.MAX_TEASER_S 15` ist eine zweite, feste 6,0 |
| `ausschluss.organisatorisches_gespraech`, `organisations_marker` | H | `ist_organisatorisch 246-250` → `heuristic_llm.py 458` |
| `ausschluss.begruessung_und_abschied`, `insiderwitz_ohne_kontext` | nein | |

Folge: Mit einem Sprachmodell wirken `einstieg.*` (außer `pronomen`), `ausstieg.*` und `ausschluss.*` nur als feste Textzeilen im Prompt (`editorial.py 272-275`), nicht über die YAML-Werte. Vorschlag und Bewertung des Modells kennen nur Länge, Rubrik und Moment-Typen (Prompt-Text).

## 6. Prompt-Versionen

`prompts.load(name, version=None)` (`W/prompts.py 83-96`) sucht `<name>_v*.md` in `PROMPTS_DIR` oder `packages/prompts` und nimmt ohne Versionsangabe die höchste Nummer (numerisch sortiert). Alle Aufrufer im Worker übergeben keine Version (Suche über alle `prompts.load(`-Stellen). Eine neue `_vN+1`-Datei schaltet den Pfad deshalb sofort um, ohne Code-Änderung. Die Version erscheint als `prompt_version`: im Kandidaten (nur `score_clip`), im Cache-Key der Kandidaten (alle drei Engine-Prompts, `story_engine.prompt_versions 850-856`), in `hook_versions.prompt_version` (nur `hooks`) und im LLM-Cache-Key `llm:<sha256(provider, model, prompt_version, [system, user, schema])>` (`providers_llm.cache_key 38-40`, im Produktionspfad ohne Redis nicht aktiv). Die Version von `post_caption` wird nicht in die Zeile geschrieben (`CopyResult.post_caption_prompt_version` fehlt in `to_row 95-107` und `_write_hook_version 448-477`).

| Name | Geladene Version (ausgeführt) | Tool | Wo |
|---|---|---|---|
| `system_editor` | `system_editor_v1` | | `story_score.system_prompt 117-118`, `copy_engine._system_prompt 123-124` |
| `propose_moments` | `propose_moments_v1` | `propose_moments` | `story_score.propose 218-234` |
| `score_clip` | `score_clip_v2` (`policy: clip_policy_v1` im Kopf); `_v1` bleibt als Datei, wird nicht mehr geladen | `score_clip` | `story_score.score 352-373` |
| `story_graph_confirm` | `story_graph_confirm_v1` | `confirm_qualification` | `story_graph.build_confirm_prompt 85-87` |
| `hooks` | `hooks_v1` | `write_hooks` | `copy_engine.generate_variants 127-153` (zweiter, ungenutzter Pfad `copy_de.py 113-124`) |
| `post_caption` | `post_caption_v1` | `write_post_caption` | `copy_engine.generate_post_caption 203-224` |

Gewichts-Frontmatter von `score_clip_v2` ist nur Kopie; bei Abweichung gewinnt die Policy und es gibt eine Log-Warnung (`story_score.weight_drift 176-194`). Die Policy-Fassung steckt über den Namen im Cache-Key (`clip_policy_v1`), ihr Inhalt nicht.

## 7. Drei Problemarten

Einordnung nach Master-Prompt Abschnitt 3. Die Befundnummern sind die der Tabelle in `docs/RESEARCH-CLIPPING-KERN.md` Abschnitt 2 (dort mit Status und Schwere).

| Problemart | Frage | Stufen in diesem Dokument | Befunde (RESEARCH Abschnitt 2) |
|---|---|---|---|
| Auswahl | Wurde der richtige Gedanke gefunden, und wurde der falsche verworfen? | 1.4 Heatmap, 1.5 Vorschlag, 1.7 `select_best` | 3, 4, 11 |
| Redaktion | Sind Einstieg, Kontext, Aufbau, Hook und Abschluss des gefundenen Gedankens gut? | 1.6 Bewertung, Heilung, Teaser, 1.9 Komposition, 1.10 Copy, 1.15 Lernen | 5, 6, 7, 12 |
| Ausführung | Beschädigen Zeitstempel, Satzzerlegung, Untertitel, Reframe oder Build die gute Entscheidung? | 1.3 Segmentierung, 1.11 Captions, 1.12 Reframing, 1.13 Render, 1.2 und Abschnitt 4 (Image) | 1, 2, 8, 9, 10, 13 |

Beim Schreiben aufgefallen, nicht im Katalog (a bis f), je als Beobachtung am Code, nicht als Bewertung:

- a. Auswahl: Die Belegprüfung der Rubrikzitate (`_evidence_grounded`) und `rubric_guessed` haben keine Folge, nichts liest sie (1.6).
- b. Redaktion: Die Lernzeilen zählen automatisch angenommene Kandidaten als menschliches `accepted` (`learning.py 38-41`, `analyze.py 305-312`).
- c. Redaktion: Weder `risk_flags` (`humor`, `sensitive_topic`, `claim`) noch `needs_human` führen zu einer Regel in `ausgabe_regeln_v1.json`. Veröffentlicht wird nach `clips.review`.
- d. Redaktion: `A/candidates/labels.ts:qualityWord 69-75` setzt Schwellen 8, 6, 4 für eine Skala 0 bis 10, `total` liegt nominal auf 0 bis 14.
- e. Ausführung: Das Web setzt nach einer Revision `sentence_boundaries` immer auf bestanden und die Segmente auf ein einziges `body` (`A/candidates/gates.ts 59`, `revise.ts 58`); ein vorhandener Teaser geht verloren, `total` bleibt stehen.
- f. Ausführung: Im Temporal-Betrieb löst `auto_create_clips` keinen Render aus (Abschnitt 4).
