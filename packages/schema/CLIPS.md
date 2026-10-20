# Datenvertrag: Clips, Render-Plan, Hooks, Captions (Phase 3)

Tabellen `clips`, `hook_versions`, `caption_versions` (Migrationen 0001 + 0002). Die Web-App legt Clips
beim Annehmen an und sendet das Freigabe-Signal; der Worker rendert, schreibt Copy und Provenienz.
Vertragsversion: `clips_v1`, `render_plan_v1`.

## Ablauf

1. **Web, Annehmen im Review**: Nutzer wählt Ziele (Standard: alle vier; LinkedIn immer mit dabei, wenn
   Markenprofil `default_platform = linkedin`). Pro Ziel eine `clips`-Zeile:
   `candidate_id`, `source_id`, `platform`, `destination = platform`, `aspect` (tiktok/reels/shorts `9:16`,
   linkedin `4:5`), `composition = candidate.segments`, `title_card = rubric.suggested_title_card` (oder leer),
   `ad_label` (aus Briefing `is_ad`, Land: DE `Anzeige`, AT/CH `Werbung`), `status = 'draft'`, `created_by`.
   Danach `candidates.human_verdict = 'accepted'`, Audit `candidate.accepted` mit `clip_ids`, und pro Clip
   Temporal-Signal `approve(candidate_id, platform)` an `project-<source_id>`. Ohne Temporal (Demo) bleibt
   der Clip `draft` und die Demo simuliert `rendering → rendered`.
2. **Worker, `render_pack(candidate_id, destination)`**: findet die `clips`-Zeile `(candidate_id, platform = destination)`
   mit Status `draft`, `failed` oder `rendered` (Re-Render, z. B. nach Hook-Änderung); fehlt sie, legt er sie an.
   Setzt `status = 'rendering'`, Events `step = 'render'` (`started`, `progress` je Schritt: copy, reframe,
   captions, encode, provenance; `finished` / `failed`), Kostenlog `job_type = 'render'`.
3. **Copy zuerst**: existiert keine `hook_versions`-Zeile für den Clip, erzeugt der Worker Version 1 (`origin = 'llm'`):
   Prompt `hooks_v1` → fünf Varianten → `copy_de.lint` pro Variante → `fidelity.hook_claim_check` gegen den Clip-Text →
   `post_caption_v1` pro Plattform → Linter → optional LanguageTool (nur wenn `LANGUAGETOOL_URL` gesetzt und Host erlaubt).
   `spoken_hook` / `onscreen_hook` = erste Variante ohne `claim_issues` (sonst Variante 1 mit Issues), `pattern` dazu,
   `variants` = alle fünf, `post_captions = {tiktok, reels, shorts, linkedin}`, `cta`, `lint_notes`, `claim_issues`.
   Existiert eine manuelle Version (`origin = 'manual'`), nimmt der Render die höchste Version.
4. **Render**: Reframe → Captions → ffmpeg → Provenienz → Upload → `clips` aktualisieren (siehe Spalten) →
   `caption_versions` Version n+1 (`origin = 'auto'`, `cards`, `ass_key`, `srt_key`, `cps_warnings`) → `status = 'rendered'`,
   `rendered_at`. Fehler: `status = 'failed'`, `render_error` (deutsch, verständlich).
5. **Web, Re-Render**: `POST /api/projects/<id>/clips/<clipId>/render` sendet `approve(candidate_id, platform)` erneut.

## Spalten `clips` nach dem Render

| Spalte | Inhalt |
|---|---|
| `file_key` | `renders/<clip_id>/<hash>.mp4` im Bucket `derived` (H.264 High, yuv420p, +faststart, AAC 192k) |
| `srt_key`, `vtt_key` | Untertitel als Datei, gleiche Basis |
| `poster_key` | JPG bei 1,0 s |
| `duration_s`, `width`, `height`, `fps` | aus ffprobe des Ergebnisses |
| `loudness` | `{ "integrated_lufs": -16.1, "true_peak_dbtp": -1.6, "preset": "master" }` (gemessen mit `ebur128`, Preset `master` = -16 / -1,5, `legacy_social` = -14 / -1) |
| `provenance` | `{ "c2pa": "signed" \| "skipped" \| "failed", "reason": "c2patool nicht installiert", "ai_label_required": false, "ai_features": [], "source_credit": "Quelle: …" \| null, "ad_label": "Anzeige" \| null }` |
| `render_plan` | siehe unten, deterministisch, vollständig (aus dem Plan lässt sich der Render wiederholen) |
| `cps_warnings` | Liste von Strings (Lesetempo über 17 Zeichen/Sekunde) |
| `composition` | Beim Annehmen `candidate.segments`. Nach dem Render unter Policy v2 mit `cut.padding` (AP10b) mit Vor- und Nachlauf: die gepaddeten Quellsegmente aus `render_plan.timeline` (`source_in`, `source_out`, gleiche Reihenfolge und Rollen), damit das Web die Ausgabezeit aus denselben Segmenten rechnet wie das Video. Nur bei bestandener technischer Prüfung; das Padding ist idempotent, ein erneuter Render ergibt denselben Plan. Unter v1 unverändert. Der Kandidat bleibt unverändert. |
| `fidelity_warnings` | Ergebnis von `fidelity.check_cut` für die Komposition; unter v2 mit `cut.padding` zusätzlich Übergangsbefunde `transition_cut_in_word` (`high`, mittel nur bei überlappenden Wortzeiten), `transition_gap_short`, `transition_speaker_change`, `transition_caption_lost` (je `medium`) mit `detail`, `segment_index` und je nach Art `edge`, `time_s`, `word_index`, `rest_s` |
| `speaker_positions` | aus der UI bestätigt oder vom Worker vorgeschlagen `{ "SPEAKER_00": 0, "SPEAKER_01": 1 }` |
| `caption_style` | Untertitel-Stil dieses Clips (Migration 0008), `{}` heißt: nichts eingestellt. Felder: `preset`, `font`, `font_px`, `bold`, `all_caps`, `words_per_card` (1 bis 6), `max_lines`, `base_color`, `highlight_color`, `highlight_words`, `outline_px`, `box`, `bottom_margin_px`. Größen gelten für 1080x1920 und werden auf die Ausgabegröße umgerechnet. Grenzen und Prüfung: `captions_de.STIL_GRENZEN` / `style_anwenden`, gespiegelt in `apps/web/lib/clips/caption-style.ts`. Der Clipstil sticht den Stil des Markenprofils. |

## `render_plan` (`render_plan_v1`)

```json
{
  "contract": "render_plan_v1",
  "platform": "linkedin",
  "aspect": "4:5",
  "output": { "width": 1080, "height": 1350, "fps": 25 },
  "segments": [{ "start": 812.4, "end": 861.0, "role": "body" }],
  "filler_cuts": false,
  "reframe": {
    "strategy": "talking_head" | "two_speakers" | "neutral",
    "detector": "yunet" | "none",
    "faces_detected": true,
    "positions": [412.0, 1310.0],
    "min_shot_s": 1.2
  },
  "shots": [{ "start": 812.4, "end": 830.1, "crop_x": 240, "crop_y": 0, "crop_w": 1215, "crop_h": 1080, "layout": "single" }],
  "captions": {
    "preset": "linkedin_static",
    "font": "Inter",
    "font_px": 62,
    "max_chars": 24,
    "baseline_y": 1200,
    "safe_zone": { "top": 120, "bottom": 150, "left": 60, "right": 60 },
    "cards": 14,
    "highlight": false
  },
  "title_card": { "text": "Preise im Handwerk", "seconds": 2.5 } | null,
  "hook_overlay": { "text": "Der teuerste Fehler meiner Karriere", "seconds": 3.0 } | null,
  "audio": { "preset": "master", "lufs": -16, "true_peak": -1.5, "micro_fade_ms": 20 },
  "sources": { "storage_key": "uploads/abc", "transcript_version": 3, "hook_version": 1, "candidate_id": "…" },
  "versions": { "captions_de": "captions_v1", "render": "render_v1", "reframe": "reframe_v2" }
}
```

Unter Policy v2 mit `cut.padding` (AP10b, `pipeline/transitions.py`) kommen additiv hinzu, ohne Schalter
fehlen sie und der Plan ist byte-gleich zu vorher:

* `segments` sind die gepaddeten Schnittzeiten: Start höchstens `cut.lead_in_s` (0,06 s) vor dem ersten Wort,
  nie vor dem Ende des Vorworts; Ende höchstens `cut.lead_out_s` (0,18 s) nach dem letzten Wort, nie in das
  Folgewort; bei lückenlosen Wortzeiten kein Padding; bei niedriger Sicherheit höchstens bis zur Mitte der Stille.
* `timeline`: je Segment Herkunft und Ziel, deterministisch aus `compose.output_timeline`:
  `{ "segment_index": 0, "role": "body", "source_in": 812.34, "source_out": 830.28, "output_in": 0.0, "output_out": 17.94, "boundary_confidence": 0.95, "low_confidence": false }`.
  `boundary_confidence` (0 bis 1, Formel im Modulkopf von `transitions.py`, Herkunft H) ist die schwächere
  der beiden Kanten; `null` für ein Segment ohne Wort.
* `timebase`: `{ "unit": "s", "reference": "source_audio", "frame_snapping": false, "vfr": false | true | null, "vfr_verified": false }`.
  Kanonische Zeitbasis sind Sekunden auf der Audioebene der Quelle, keine Rasterung auf Frames; `vfr` kommt aus
  ffprobe (mittlere gegen nominelle Bildrate), das Verhalten bei variabler Bildrate ist ungeprüft.
* `versions.render` ist `render_v2` (sonst `render_v1`); der Idempotenz-Hash ändert sich damit nur bei aktivem Schalter.

Lane P4 (Launch Phase 4, Fassung 2, je ein Schalter in `implementation`, Regeln in `clip_policy_v2.yaml`; ohne sie
fehlen die Felder und der Plan ist byte-gleich; Entscheidungen `docs/decisions/040` bis `043`):

* `timeline[k].edges` (Regel `cut.prosody.enabled`, Standard aus, nur mit `cut.padding`): je Segment
  `{"in": edge, "out": edge}` mit `edge = { "chosen_s", "text_s", "rms_min_s", "breath", "confidence" }`. `chosen_s` ist
  die Schnittzeit in Quellzeit (gleich `source_in` bzw. `source_out`), `text_s` die Wortgrenze aus der ASR,
  `rms_min_s` das leiseste 20-ms-Fenster im Suchfenster `cut.prosody.search_window_s` (0,35 s; `null` ohne Audio
  oder ohne Raum zwischen den Wörtern), `breath` true, wenn ein Atem direkt vor dem Wortbeginn erkannt und
  ausgelassen wurde, `confidence` 1 minus Pegel an der Kante durch Sprachpegel (0 bis 1, `null` ohne Audio). Nie im
  Nachbarwort, nie in einer geschützten Spanne; gemessen am 16-kHz-WAV der Quelle, gerendert aus dem Original.
* `hook_audio` (Regel `cut.hook_audio.enabled`, Standard aus, nur mit `cut.padding`):
  `{ "speech_onset_s", "hook_onset_s", "preamble_removed_s", "ok", "basis" }` auf der Ausgabezeit. `ok` heisst:
  Sprache beginnt bis `cut.hook_audio.max_lead_s` (1,0 s) und der Hook-Satz bis `cut.hook_audio.hook_window_s`
  (3,0 s). `preamble_removed_s` ist die Länge des übersprungenen Vorgeplänkels (ganze Sätze nur aus Füllwörtern,
  Rückmeldesignalen, Begrüssungen), gerechnet gegen den Beginn des Kandidaten. `basis` `audio` oder `words`.
* `captions.reading_speed` (Schalter `implementation.captions.reading_speed`, mit AP10a): `{ "profile": "standard" |
  "langsam", "chars_per_s": 15 | 12 }`. Profil aus dem Feld `reading_speed` im Untertitelstil (Markenprofil oder
  Clip), sonst `standard`. Eine Karte mit mehreren Wörtern steht mindestens Zeichen durch `chars_per_s`, nie in die
  nächste Karte und nie über das Clipende; Schrift, Farbe, Position und Animation bleiben.
* `reframe.speaker_face_binding` (Regel `cut.split_screen.enabled`, Standard aus): je Einstellung
  `{ "start_s", "end_s", "binding": { "<SPEAKER>": { "position", "x", "confidence", "votes" } } }`, gemessen aus
  der Mundbewegung bei Alleinrede. Split-Screen (`layout = "geteilt"`, `grund = "overlap_gebunden"`) nur an Stellen
  mit Wörtern `overlap: true` (Vertrag Lane P1, Sprecher aus `speakers`) ab 1,2 s und nur, wenn zwei beteiligte
  Sprecher mit `confidence` ab `cut.split_screen.min_binding_confidence` (0,8) an verschiedene Positionen gebunden
  sind; sonst die bisherige Ansicht. Ohne Gesichtsdetektor eine leere Liste.
* `title_card` mit `source = "repair"` und `source_span` (Fassung 2): kommt aus `rubric.repair = { "kind":
  "title_card", "text", "source_span" }` (Lane P3) und ersetzt den Text der vorhandenen Titelkarte; Dauer
  (`seconds` 2,5) und Stil bleiben.

## Export als Abnahmeobjekt (`export.strict`, Lane P4)

Fassung 2 mit Schalter `implementation.export.strict` und Regel `export.strict` (Standard false, damit Fassung 1
unverändert bleibt). Zusätzlich zu den Einträgen der Ausgabeprüfung (Migration 0014) stehen in `export_checks`:

| `pruefung` | geprüft |
|---|---|
| `timeline_dauer` | Dauer der Datei gleich Summe der Timeline-Segmente, Toleranz `export.duration_tolerance_s` (0,2 s) |
| `untertitel_abdeckung` | kein SRT-Eintrag vor 0 oder nach dem Clipende, letzte Karte endet vor dem Clipende |
| `untertitel_zeiten` | Wörter und Zeiten der Untertitel entsprechen der Schnittbeschreibung (`source_in`/`source_out` zu `output_in`/`output_out`) |
| `synchron` | jeder Wortanfang der Untertitel liegt in einem Segment der Ausgabe |
| `ton_stumm` | Tonspur vorhanden und lauter als -60 LUFS |
| `bild_schwarz` | weniger als 90 Prozent der Dauer schwarz |
| `abrufbar` | die MP4 liegt nach dem Hochladen im Speicher |
| `anrede` | Du/Sie-Hinweis (Schalter `implementation.captions.address_check`, auch ohne `export.strict`): `hinweis` bei gemischter Anrede, nie `fehler`, keine Textänderung |

Letzter Eintrag: `{ "pruefung": "abnahme", "ergebnis": "ok" | "fehler", "text", "gemessen": null, "export_ok": bool }`.
`status = 'rendered'` und `file_key` nur mit `export_ok: true`; sonst `status = 'failed'`, `render_error` mit dem
ersten Fehler, `file_key` leer (die Datei bleibt unter `renders/<clip_id>/<hash>.mp4` im Speicher, ist aber nicht
zum Download freigegeben). Ein erneuter Aufruf mit demselben Plan überspringt den Render nur, wenn das gespeicherte
`export_checks` `export_ok: true` trägt; er legt nie eine zweite `clips`-Zeile oder eine zweite Datei an. Ein
abgebrochener Render endet `failed` (oder bleibt `rendering`, wenn der Prozess stirbt), nie `rendered`.

Tonregel 10 (Test `tests/test_launch_p4_export.py`): jeder Segment-Eingang ist das Original der Quelle, nie das
16-kHz-WAV (das dient nur der Analyse der Kanten) und nie eine separierte Spur. Auf dem Weg der Sprache stehen nur
`asetpts`, `afade` (Blenden an den Kanten), `concat`, `asplit`, `amix` (Musik), `acompressor` (LRA über 7),
`loudnorm` und `aresample`; die Musik darf zusätzlich `atrim`, `apad`, `volume` und `sidechaincompress` (Sprache nur
als Auslöser) nutzen.

Ausgabegrößen: `9:16` 1080×1920, `4:5` 1080×1350, `1:1` 1080×1080, `16:9` 1920×1080. Bildrate = Quellrate,
nie mischen (25 oder 30 oder 50/60 bleiben).

Reframe-Strategien: ein Sprecher oder eine Sitzposition → `talking_head` (ruhiger Crop auf die Position,
Augen im oberen Drittel); zwei Positionen → `two_speakers` (virtuelle Kamera schneidet auf den aktiven
Sprecher, min. Shot 1,2 s, `speaker_positions` bestimmt Zuordnung); keine Gesichter oder kein Detektor →
`neutral` (mittiger Crop, im Plan sichtbar, in der UI als Hinweis).

## `hook_versions`

`spoken_hook` (max. 12 Wörter), `onscreen_hook` (max. 9 Wörter), `pattern`, `variants` (fünf Einträge
`{ pattern, spoken, onscreen, lint_notes: [], claim_issues: [] }`), `post_captions` (`{ tiktok, reels, shorts, linkedin }`),
`cta`, `lint_notes`, `claim_issues`, `origin` (`llm` | `manual`), `model_id`, `prompt_version` (`hooks_v1`).
Manuelle Versionen entstehen im Hook-Studio (`POST /api/projects/<id>/clips/<clipId>/hooks`).

## `caption_versions`

`preset`, `cards` (`[{ "start": 0.0, "end": 1.4, "lines": ["Der teuerste Fehler", "meiner Karriere"] }]` auf der
Ausgabe-Timeline), `ass_key`, `srt_key`, `cps_warnings`, `origin`.

## Medien in der Web-App

URLs = `NEXT_PUBLIC_MEDIA_BASE_URL` + `/` + Key (lokal MinIO `http://localhost:9000/chopstr-derived`).
Fehlt die Basis-URL oder der Key (Demo), zeigt die UI Platzhalter. Signierte URLs kommen in Phase 4.

## Stumme Vorschau (QA-Schritt)

Die Web-App rendert eine CSS-Vorschau des Ausgabeformats mit Safe Zones, Caption-Karten im Preset-Stil,
On-Screen-Hook (erste 3 s) und Titelkarte, ohne Ton. Sie ersetzt keinen Render, macht aber Layout, Umbrüche
und Lesetempo-Warnungen vor dem Render prüfbar.
