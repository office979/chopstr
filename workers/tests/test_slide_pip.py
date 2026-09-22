"""Folien-Crop (Phase 5c): reine Layoutplanung, Override-Pfad, pip-Filtergraph und ein Medientest mit ffmpeg.

Die Erkennung selbst braucht OpenCV (Extra ``vision``). Fehlt es, prüft der Medientest nur den Override-Pfad
(``reframe_override = "slide_pip"`` ohne erkannte Folie legt das ganze Quellbild oben ab)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chopstr_worker.pipeline import captions_de, compose, reframe, render, render_plan
from tests.conftest import requires_ffmpeg

SRC_W, SRC_H = 1280, 720
SEGS = [{"start": 0.5, "end": 3.0, "role": "body"}, {"start": 3.5, "end": 6.0, "role": "body"}]
EXPECTED_S = 5.0
COLS, ROWS = reframe.SLIDE_GRID


def _grid(fill: float) -> list[list[float]]:
    return [[fill for _ in range(COLS)] for _ in range(ROWS)]


def _split_grid(static_cols: int, stable: float = 0.95, edge: float = 0.05) -> tuple[list[list[float]], list[list[float]]]:
    """Links ``static_cols`` ruhige Spalten mit Kanten, rechts Bewegung."""
    stability = [[stable if c < static_cols else 0.1 for c in range(COLS)] for _ in range(ROWS)]
    edges = [[edge if c < static_cols else 0.2 for c in range(COLS)] for _ in range(ROWS)]
    return stability, edges


def _words() -> list[dict]:
    out, t, i = [], 0.5, 0
    while t < 6.0:
        out.append({"text": "nicht" if i % 5 == 2 else f"Wort{i}", "start": round(t, 3), "end": round(t + 0.35, 3), "speaker": "SPEAKER_00"})
        t += 0.45
        i += 1
    return out


def _slide_video(path: Path, seconds: float = 6.5) -> Path:
    """Links statisches Raster (ruhig, viele Kanten), rechts Testmuster mit zeitlichem Rauschen (Bewegung), Ton."""
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=white:s={SRC_W // 2}x{SRC_H}:r=25,drawgrid=width=40:height=40:thickness=3:color=black",
        "-f", "lavfi", "-i", f"testsrc2=s={SRC_W // 2}x{SRC_H}:r=25,noise=alls=40:allf=t+u",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]", "-map", "[v]", "-map", "2:a", "-t", f"{seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def slide_src(tmp_path_factory) -> Path:
    if not render.ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe nicht installiert")
    return _slide_video(tmp_path_factory.mktemp("slide") / "slide.mp4")


# -- reine Auswertung des Rasters ----------------------------------------------------------------
def test_slide_region_from_grid_finds_static_half_with_edges():
    stability, edges = _split_grid(COLS // 2)
    region = reframe.slide_region_from_grid(stability, edges, SRC_W, SRC_H, frames_sampled=12)
    assert region is not None
    assert (region.x, region.y, region.w, region.h) == (0, 0, SRC_W // 2, SRC_H)
    assert region.area_ratio == 0.5 and region.stability == 0.95 and region.frames_sampled == 12
    assert region.confidence == round(0.6 * 0.95 + 0.4 * 1.0, 3) >= reframe.SLIDE_MIN_CONFIDENCE
    assert region.to_dict() == {"x": 0, "y": 0, "w": 640, "h": 720, "confidence": region.confidence}
    assert all(v % 2 == 0 for v in (region.x, region.y, region.w, region.h))


def test_slide_region_rejects_walls_strips_and_small_areas():
    # ruhig, aber ohne Kanten (Wand): keine Folie
    stability, edges = _split_grid(COLS // 2, edge=0.0)
    assert reframe.slide_region_from_grid(stability, edges, SRC_W, SRC_H) is None
    # schmaler Streifen (4 von 16 Spalten, volle Höhe): Fläche und Seitenverhältnis reichen nicht
    stability, edges = _split_grid(4)
    assert reframe.slide_region_from_grid(stability, edges, SRC_W, SRC_H) is None
    # alles in Bewegung
    assert reframe.slide_region_from_grid(_grid(0.2), _grid(0.1), SRC_W, SRC_H) is None
    # ganzes Bild ruhig mit Kanten: volle Fläche, Sicherheit 1,0
    full = reframe.slide_region_from_grid(_grid(1.0), _grid(0.1), SRC_W, SRC_H)
    assert full is not None and (full.w, full.h, full.confidence) == (SRC_W, SRC_H, 1.0)
    # eine unruhige Zelle in der Mitte zerschneidet das Rechteck, das größte Teilrechteck bleibt
    stability = _grid(1.0)
    stability[ROWS // 2][COLS // 2] = 0.0
    part = reframe.slide_region_from_grid(stability, _grid(0.1), SRC_W, SRC_H)
    assert part is not None and part.w < SRC_W and part.area_ratio >= reframe.SLIDE_MIN_AREA


# -- Layoutplanung ohne Video ----------------------------------------------------------------------
def test_plan_slide_layout_slide_on_top_speaker_below():
    region = reframe.SlideRegion(0, 0, 640, 720, 0.9)
    lay = reframe.plan_slide_layout(SRC_W, SRC_H, 1080, 1920, region, [], [])
    slide, pip, crop = lay["slide_out"], lay["pip"], lay["crop"]
    assert slide["y"] == 0 and slide["h"] <= int(1920 * reframe.SLIDE_MAX_HEIGHT_RATIO) and slide["h"] % 2 == 0
    assert slide["w"] <= 1080 and abs(slide["x"] - (1080 - slide["w"]) / 2) <= 1 and slide["x"] % 2 == 0  # gedeckelt: mittig
    assert pip == {"x": 0, "y": slide["h"], "w": 1080, "h": 1920 - slide["h"]}
    assert lay["caption_top"] == pip["y"] + round(1920 * reframe.SLIDE_CAPTION_GAP_RATIO)
    # ohne Gesicht: neutral im größten Streifen neben der Folie (rechts), geklemmt an den Rand
    assert crop["h"] == SRC_H and crop["w"] == reframe.crop_geometry(SRC_W, SRC_H, pip["w"], pip["h"])[0]
    assert crop["x"] == SRC_W - crop["w"]
    # 16:9-Folie auf 9:16: volle Breite, Höhe proportional (1080 * 9 / 16 = 607,5 -> 606 gerade)
    wide = reframe.plan_slide_layout(1920, 1080, 1080, 1920, reframe.SlideRegion(0, 0, 1920, 1080, 1.0))
    assert wide["slide_out"] == {"x": 0, "y": 0, "w": 1080, "h": 606} and wide["pip"]["h"] == 1314
    # mit Gesicht: Talking-Head-Regel (Augen bei EYE_LINE der Sprecherfläche)
    face = reframe.plan_slide_layout(1920, 1080, 1080, 1920, reframe.SlideRegion(0, 0, 1280, 1080, 0.8), [1600.0], [400.0])
    c = face["crop"]
    assert c["x"] == 1600 - c["w"] // 2 or c["x"] == 1920 - c["w"]
    assert c["y"] == max(0, min(round(400 - reframe.EYE_LINE * c["h"]), 1080 - c["h"]))
    shots = reframe.plan_slide_shots(SEGS, lay)
    assert [s.layout for s in shots] == ["pip", "pip"] and shots[0].crop_w == crop["w"] and shots[1].end == 6.0


def test_plan_reframe_override_paths_without_video():
    words = _words()
    # Override slide_pip ohne Folie (kein Video, kein OpenCV): ganzes Quellbild oben, Hinweis
    res = reframe.plan_reframe(None, SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H, reframe_override="slide_pip")
    assert res.strategy == "slide_pip" and res.slide_region is not None and res.slide_region.confidence == 0.0
    assert res.slide_region.to_dict() == {"x": 0, "y": 0, "w": SRC_W, "h": SRC_H, "confidence": 0.0}
    assert any("ohne erkannte Folie" in n for n in res.notes)
    block = res.plan_block()
    assert block["strategy"] == "slide_pip" and block["override"] == "slide_pip" and block["pip"]["x"] == 0
    assert block["pip"]["w"] == 1080 and block["pip"]["y"] + block["pip"]["h"] == 1920
    assert all(s["layout"] == "pip" for s in res.shots_json()) and len(res.shots) == 2
    # Override talking_head ohne Positionen: ehrlich neutral mit Hinweis, kein slide-Block
    th = reframe.plan_reframe(None, SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H, reframe_override="talking_head")
    assert th.strategy == "neutral" and "slide_region" not in th.plan_block() and th.plan_block()["override"] == "talking_head"
    assert any("Override talking_head nicht möglich" in n for n in th.notes)
    # Override neutral ist immer möglich
    ne = reframe.plan_reframe(None, SEGS, words, None, "4:5", src_w=SRC_W, src_h=SRC_H, reframe_override="neutral")
    assert ne.strategy == "neutral" and ne.shots[0].layout == "single"
    # ohne Override bleibt alles wie in Phase 3 (kein zusätzlicher Schlüssel im Plan)
    auto = reframe.plan_reframe(None, SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H)
    assert set(auto.plan_block()) == {"strategy", "detector", "faces_detected", "positions", "min_shot_s"}
    with pytest.raises(ValueError, match="Unbekannte Reframe-Strategie"):
        reframe.plan_reframe(None, SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H, reframe_override="zoom")
    assert reframe.effective_strategy("two_speakers", [1.0]) == "talking_head"
    assert reframe.effective_strategy("two_speakers", []) == "neutral"
    assert reframe.effective_strategy("slide_pip", []) == "slide_pip"
    assert "slide_pip" in reframe.STRATEGIES


def test_plan_and_filter_graph_for_pip_layout():
    res = reframe.plan_reframe(None, SEGS, _words(), None, "9:16", src_w=SRC_W, src_h=SRC_H, reframe_override="slide_pip")
    plan = render_plan.build_plan(
        platform="tiktok", segments=SEGS, reframe_result=res, caption_preset="tiktok_bold", caption_cards=3,
        sources={"storage_key": "k"}, title_card="Folie", onscreen_hook="Hook", hook_overlay=True,
    )  # fmt: skip
    pip = plan["reframe"]["pip"]
    assert plan["reframe"]["slide_region"]["w"] == SRC_W and plan["shots"][0]["layout"] == "pip"
    # Captions und Overlays liegen in der Sprecherfläche: Safe Zone beginnt unter der Folie
    assert plan["captions"]["safe_zone"]["top"] == pip["y"] + round(1920 * reframe.SLIDE_CAPTION_GAP_RATIO)
    assert plan["captions"]["baseline_y"] > pip["y"]
    assert "text_field" not in plan["captions"]
    graph, notes, burned, title, hook, wm = render.video_chain(plan, None, None, {"subtitles": False, "drawtext": False, "vstack": True}, None)
    assert graph.count("split=2") == 2 and graph.count("vstack=inputs=2") == 2 and graph.count("pad=1080:") == 2
    assert f"scale=1080:{pip['y']}:force_original_aspect_ratio=decrease" in graph
    assert f"scale={pip['w']}:{pip['h']}:flags=lanczos" in graph and "concat=n=2:v=1:a=0[vc]" in graph
    assert graph.count("crop=") == 4  # je Shot Folie und Sprecher
    with pytest.raises(render.RenderError, match="vstack"):
        render.video_chain(plan, None, None, {"subtitles": False, "drawtext": False, "vstack": False}, None)
    broken = {**plan, "reframe": {**plan["reframe"], "pip": {**pip, "x": 10}}}
    with pytest.raises(render.RenderError, match="volle Breite"):
        render.pip_shot_filter(broken, 0, plan["shots"][0])
    with pytest.raises(render.RenderError, match="slide_region"):
        render.pip_shot_filter({**plan, "reframe": {"strategy": "slide_pip"}}, 0, plan["shots"][0])


def test_slide_detector_reports_missing_opencv(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    ok, reason = reframe.slide_detector_available()
    assert ok is False and "OpenCV" in reason
    notes: list[str] = []
    assert reframe.detect_slide_region("nix.mp4", SEGS, notes=notes) is None
    assert notes == [reason]


# -- Medientest ------------------------------------------------------------------------------------
@requires_ffmpeg
def test_render_slide_pip_from_lavfi_video(slide_src, tmp_path):
    words = _words()
    have_cv2, _ = reframe.slide_detector_available()
    if have_cv2:
        notes: list[str] = []
        region = reframe.detect_slide_region(str(slide_src), SEGS, notes=notes)
        assert region is not None, notes
        assert region.x == 0 and region.y == 0 and region.w == SRC_W // 2 and region.h == SRC_H
        assert region.confidence >= reframe.SLIDE_MIN_CONFIDENCE and region.frames_sampled >= 4
        res = reframe.plan_reframe(str(slide_src), SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H)
        assert res.strategy == "slide_pip" and res.slide_region == region
        assert any("Layout Bild-im-Bild" in n for n in res.notes)
        # Override auf neutral: Folie erkannt, aber nicht genutzt, steht im Hinweis
        off = reframe.plan_reframe(str(slide_src), SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H, reframe_override="neutral")
        assert off.strategy == "neutral" and any("per Override neutral nicht genutzt" in n for n in off.notes)
    else:
        res = reframe.plan_reframe(str(slide_src), SEGS, words, None, "9:16", src_w=SRC_W, src_h=SRC_H, reframe_override="slide_pip")
        assert res.strategy == "slide_pip" and any("ohne erkannte Folie" in n for n in res.notes)
    out_words = compose.remap_words(words, compose.Composition.from_json(SEGS))
    preset = captions_de.scaled_preset("tiktok_bold", 1080, 1920)
    plan = render_plan.build_plan(
        platform="tiktok", segments=SEGS, reframe_result=res, caption_preset="tiktok_bold",
        caption_cards=len(captions_de.cards_for(out_words, preset)),
        sources={"storage_key": "k", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"}, src_fps=25.0,
        onscreen_hook="Folie oben, Sprecher unten", hook_overlay=True,
    )  # fmt: skip
    assert plan["shots"][0]["layout"] == "pip" and plan["reframe"]["strategy"] == "slide_pip"
    paths = render.write_captions(out_words, preset, (1080, 1920), tmp_path, "cap")
    out = tmp_path / "slide_pip.mp4"
    result = render.render_from_plan(plan, slide_src, paths["ass"], out, x264_preset="ultrafast")
    assert result.expected_duration_s == EXPECTED_S and "vstack" in result.filter_graph
    assert render.regression_checks(out, EXPECTED_S, 1080, 1920) == []
    loud = render.measure_loudness(out)
    assert -17.0 <= loud["integrated_lufs"] <= -15.0
    if render.capabilities()["subtitles"]:
        assert result.captions_burned
