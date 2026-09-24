"""Render-Plan ``render_plan_v1``: Vertragstreue, Größen je Aspect, Safe-Zone-Skalierung, Hook-Overlay-Default."""

from __future__ import annotations

import json

import pytest

from chopstr_worker.pipeline import captions_de, reframe, render_plan

SEGMENTS = [{"start": 812.4, "end": 830.1, "role": "body"}, {"start": 840.0, "end": 861.0, "role": "body"}]
SOURCES = {"storage_key": "uploads/abc", "transcript_version": 3, "hook_version": 1, "candidate_id": "cand-1"}
CONTRACT_KEYS = {
    "contract", "platform", "aspect", "output", "segments", "filler_cuts", "reframe", "shots", "motion", "captions",
    "title_card", "hook_overlay", "audio", "brand", "sources", "versions",
}  # fmt: skip


def _reframe(aspect: str) -> reframe.ReframeResult:
    out_w, out_h = render_plan.output_size(aspect)
    shots = reframe.plan_shots_for_positions(SEGMENTS, [], 1920, 1080, out_w, out_h, [], {}, strategy="neutral")
    return reframe.ReframeResult("neutral", "none", False, [], shots, 1920, 1080, out_w, out_h)


def _plan(platform: str, aspect: str | None = None, **kw) -> dict:
    aspect = aspect or render_plan.aspect_for_platform(platform)
    kw.setdefault("caption_preset", captions_de.PLATFORM_DEFAULT_PRESET[platform])
    kw.setdefault("src_fps", 25.0)
    return render_plan.build_plan(
        platform=platform, aspect=aspect, segments=SEGMENTS, reframe_result=_reframe(aspect), caption_cards=14,
        sources=SOURCES, **kw,
    )  # fmt: skip


def test_plan_has_all_contract_keys_and_is_json():
    plan = _plan("linkedin", title_card="Preise im Handwerk", onscreen_hook="Der teuerste Fehler")
    assert set(plan) == CONTRACT_KEYS
    assert plan["contract"] == "render_plan_v1" and plan["platform"] == "linkedin" and plan["aspect"] == "4:5"
    assert plan["output"] == {"width": 1080, "height": 1350, "fps": 25.0}
    assert plan["segments"] == SEGMENTS and plan["filler_cuts"] is False
    assert set(plan["reframe"]) == {"strategy", "detector", "faces_detected", "positions", "min_shot_s"}
    assert plan["reframe"]["min_shot_s"] == 1.2
    # quelle_x, auswahl und grund tragen keine Bildinformation, sondern sagen der Oberflaeche, wer
    # zu dieser Zeit zur Wahl stand und warum die Automatik so entschieden hat. Ohne sie koennte
    # die Zeitleiste anzeigen, was entschieden wurde, aber nichts anbieten.
    assert set(plan["shots"][0]) == {
        "start", "end", "crop_x", "crop_y", "crop_w", "crop_h", "layout", "quelle_x", "auswahl", "grund", "zoom", "geteilt",
    }
    assert set(plan["captions"]) == {
        "preset", "font", "font_px", "max_chars", "baseline_y", "safe_zone", "cards", "highlight",
        "bold", "all_caps", "max_lines", "words_per_card", "outline_px", "box", "base_color", "highlight_color", "outline_color", "box_color",
    }
    assert plan["captions"]["cards"] == 14 and plan["captions"]["font"] == "Inter"
    assert plan["title_card"] == {"text": "Preise im Handwerk", "seconds": 2.5}
    assert plan["hook_overlay"] is None  # LinkedIn: Default aus
    assert plan["audio"] == {"preset": "master", "lufs": -16.0, "true_peak": -1.5, "micro_fade_ms": 20}
    assert plan["sources"] == SOURCES
    assert plan["versions"] == {"captions_de": "captions_v1", "render": "render_v1", "reframe": "reframe_v2"}
    json.dumps(plan)
    assert render_plan.plan_duration(plan) == pytest.approx(38.7)


@pytest.mark.parametrize(
    "aspect,size",
    [("9:16", (1080, 1920)), ("4:5", (1080, 1350)), ("1:1", (1080, 1080)), ("16:9", (1920, 1080))],
)
def test_output_sizes_per_aspect(aspect, size):
    assert render_plan.output_size(aspect) == size
    plan = _plan("tiktok", aspect=aspect)
    assert (plan["output"]["width"], plan["output"]["height"]) == size
    with pytest.raises(ValueError):
        render_plan.output_size("3:2")


def test_fps_from_source_never_mixed():
    assert _plan("tiktok", src_fps=50.0)["output"]["fps"] == 50.0
    assert render_plan.build_plan(
        platform="tiktok", segments=SEGMENTS, reframe_result=_reframe("9:16"), caption_preset="tiktok_bold",
        caption_cards=1, sources=SOURCES,
    )["output"]["fps"] == render_plan.DEFAULT_FPS  # fmt: skip


def test_safe_zone_scaled_proportionally_for_4_5_and_1_1():
    base = _plan("tiktok", aspect="9:16", caption_preset="linkedin_static")["captions"]
    assert base["safe_zone"] == {"top": 120, "bottom": 220, "left": 80, "right": 80} and base["font_px"] == 54
    assert base["baseline_y"] == 1500
    four_five = _plan("linkedin")["captions"]
    f = 1350 / 1920
    assert four_five["safe_zone"] == {"top": round(120 * f), "bottom": round(220 * f), "left": 80, "right": 80}
    assert four_five["font_px"] == round(54 * f) and four_five["baseline_y"] == round(1700 * f) - round(200 * f)
    assert four_five["max_chars"] >= base["max_chars"]  # kleinere Schrift, gleiche Breite
    square = _plan("tiktok", aspect="1:1", caption_preset="tiktok_bold")["captions"]
    g = 1080 / 1920
    assert square["safe_zone"] == {"top": round(108 * g), "bottom": round(320 * g), "left": 60, "right": 120}
    assert square["preset"] == "tiktok_bold" and square["highlight"] is True


def test_hook_overlay_default_per_platform_and_override():
    hook = "Der teuerste Fehler meiner Karriere"
    for platform in ("tiktok", "reels", "shorts"):
        assert _plan(platform, onscreen_hook=hook)["hook_overlay"] == {"text": hook, "seconds": 3.0}
    assert _plan("linkedin", onscreen_hook=hook)["hook_overlay"] is None
    assert _plan("linkedin", onscreen_hook=hook, hook_overlay=True)["hook_overlay"]["text"] == hook
    assert _plan("tiktok", onscreen_hook=hook, hook_overlay=False)["hook_overlay"] is None
    assert _plan("tiktok", onscreen_hook="")["hook_overlay"] is None
    assert _plan("tiktok", title_card="  ")["title_card"] is None


def test_audio_presets_and_validation():
    assert _plan("tiktok", audio_preset="legacy_social")["audio"] == {"preset": "legacy_social", "lufs": -14.0, "true_peak": -1.0, "micro_fade_ms": 20}
    with pytest.raises(ValueError):
        _plan("tiktok", audio_preset="loud")
    with pytest.raises(ValueError, match="Reframe wurde für"):
        render_plan.build_plan(
            platform="tiktok", aspect="9:16", segments=SEGMENTS, reframe_result=_reframe("4:5"), caption_preset="tiktok_bold",
            caption_cards=1, sources=SOURCES,
        )  # fmt: skip
    with pytest.raises(ValueError, match="Länge 0"):
        render_plan.normalize_segments([{"start": 5, "end": 5}])


def test_plan_hash_is_deterministic_and_sensitive():
    a, b = _plan("tiktok"), _plan("tiktok")
    assert render_plan.plan_hash(a, 1, 3) == render_plan.plan_hash(b, 1, 3)
    assert render_plan.plan_hash(a, 2, 3) != render_plan.plan_hash(a, 1, 3)
    assert render_plan.plan_hash(a, 1, 4) != render_plan.plan_hash(a, 1, 3)
    assert len(render_plan.plan_hash(a, 1, 3)) == 16


def test_motion_zoom_only_when_reframing():
    """Hochformat aus einer Querformat-Quelle: Push-in. Gleiches Format: Bild bleibt unangetastet."""
    portrait = _plan("tiktok")  # Quelle 1920x1080, Ausgabe 1080x1920
    assert portrait["motion"]["zoom_to"] == render_plan.ZOOM_TO
    assert portrait["motion"]["min_shot_s"] == render_plan.ZOOM_MIN_SHOT_S

    out_w, out_h = render_plan.output_size("16:9")
    shots = reframe.plan_shots_for_positions(SEGMENTS, [], 1920, 1080, out_w, out_h, [], {}, strategy="neutral")
    same = reframe.ReframeResult("neutral", "none", False, [], shots, 1920, 1080, out_w, out_h)
    plan = render_plan.build_plan(
        platform="tiktok", aspect="16:9", segments=SEGMENTS, reframe_result=same, caption_cards=14,
        sources=SOURCES, caption_preset="tiktok_words", src_fps=25.0,
    )  # fmt: skip
    assert plan["motion"]["zoom_to"] == 1.0


def test_normalize_segments_zieht_durchgehende_abschnitte_zusammen():
    """Teilen ohne Entfernen darf im Ergebnis nicht hoerbar sein.

    Im Editor kann jemand an einer Stelle teilen und dann nichts wegnehmen. Die Komposition hat
    danach zwei Abschnitte, die in der Quelle aneinander liegen. Jeder Abschnitt bekommt beim
    Rendern eine Tonblende von 20 ms (render._audio); zwei Abschnitte ergaeben also ein hoerbares
    Loch an einer Stelle, an der der Nutzer nichts geschnitten hat.
    """
    aus = render_plan.normalize_segments([{"start": 10, "end": 20}, {"start": 20, "end": 30}])
    assert aus == [{"start": 10.0, "end": 30.0, "role": "body"}]


def test_normalize_segments_behaelt_eine_echte_luecke():
    aus = render_plan.normalize_segments([{"start": 10, "end": 20}, {"start": 25, "end": 30}])
    assert [(s["start"], s["end"]) for s in aus] == [(10.0, 20.0), (25.0, 30.0)]


def test_normalize_segments_trennt_rollen():
    """Ein Teaser bleibt ein eigener Abschnitt, auch wenn er direkt an den Koerper anschliesst."""
    aus = render_plan.normalize_segments([{"start": 10, "end": 20, "role": "teaser"}, {"start": 20, "end": 30}])
    assert [s["role"] for s in aus] == ["teaser", "body"]
