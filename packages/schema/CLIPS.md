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
| `fidelity_warnings` | Ergebnis von `fidelity.check_cut` für die Komposition |
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
