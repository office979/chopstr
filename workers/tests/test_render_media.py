"""Medientest mit echtem ffmpeg: 12-s-Testvideo 1280x720 mit Ton, Plan bauen, 9:16 und 4:5 rendern, messen."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from chopstr_worker.pipeline import captions_de, compose, reframe, render, render_plan
from tests.conftest import requires_ffmpeg

SEGMENTS = [{"start": 1.0, "end": 5.0, "role": "body"}, {"start": 6.0, "end": 12.0, "role": "body"}]
EXPECTED_S = 10.0


def _video(path: Path, seconds: float = 12.0) -> Path:
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=25:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def _words() -> list[dict]:
    out, t, i = [], 1.0, 0
    while t < 12.0:
        text = "nicht" if i % 7 == 3 else f"Wort{i}." if i % 5 == 4 else f"Wort{i}"
        out.append({"text": text, "start": round(t, 3), "end": round(t + 0.4, 3), "speaker": "SPEAKER_00" if (i // 6) % 2 == 0 else "SPEAKER_01"})
        t += 0.5
        i += 1
    return out


@pytest.fixture(scope="module")
def src(tmp_path_factory) -> Path:
    if not render.ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe nicht installiert")
    return _video(tmp_path_factory.mktemp("media") / "src.mp4")


def _build(platform: str, aspect: str, words: list[dict], workdir: Path) -> tuple[dict, dict, list[dict]]:
    out_w, out_h = render_plan.output_size(aspect)
    positions = [320.0, 960.0]
    shots = reframe.plan_shots_for_positions(SEGMENTS, words, 1280, 720, out_w, out_h, positions, {"SPEAKER_00": 0, "SPEAKER_01": 1}, [300.0, 300.0])
    rf = reframe.ReframeResult("two_speakers", "none", False, positions, shots, 1280, 720, out_w, out_h)
    out_words = compose.remap_words(words, compose.Composition.from_json(SEGMENTS))
    preset_name = captions_de.PLATFORM_DEFAULT_PRESET[platform]
    preset = captions_de.scaled_preset(preset_name, out_w, out_h)
    cards = captions_de.cards_for(out_words, preset)
    plan = render_plan.build_plan(
        platform=platform, aspect=aspect, segments=SEGMENTS, reframe_result=rf, caption_preset=preset_name, caption_cards=len(cards),
        sources={"storage_key": "uploads/x", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"}, src_fps=25.0,
        title_card="Preise im Handwerk", onscreen_hook="Der teuerste Fehler meiner Karriere", hook_overlay=True,
    )  # fmt: skip
    paths = render.write_captions(out_words, preset, (out_w, out_h), workdir, "cap")
    assert plan["captions"]["font_px"] == preset.font_px and plan["captions"]["baseline_y"] == preset.baseline_y
    return plan, paths, cards


@requires_ffmpeg
@pytest.mark.parametrize("platform,aspect", [("tiktok", "9:16"), ("linkedin", "4:5")])
def test_render_from_plan_meets_master_spec(src, tmp_path, platform, aspect):
    plan, paths, cards = _build(platform, aspect, _words(), tmp_path)
    assert len(plan["shots"]) >= 3 and cards
    out = tmp_path / f"out_{aspect.replace(':', 'x')}.mp4"
    result = render.render_from_plan(plan, src, paths["ass"], out, x264_preset="ultrafast")
    assert result.expected_duration_s == EXPECTED_S and result.compressor is False
    assert result.measured["input_lra"] < render.COMPRESS_ABOVE_LRA

    w, h = render_plan.output_size(aspect)
    assert render.regression_checks(out, EXPECTED_S, w, h) == []
    loud = render.measure_loudness(out)
    assert -17.0 <= loud["integrated_lufs"] <= -15.0
    assert loud["true_peak_dbtp"] <= -1.0

    poster = render.make_poster(out, tmp_path / f"poster_{platform}.jpg", 1.0)
    assert Path(poster).is_file() and Path(poster).stat().st_size > 1000

    srt = Path(paths["srt"]).read_text(encoding="utf-8")
    vtt = Path(paths["vtt"]).read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> ") and re.search(r"\n\d+\n\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}\n", srt)
    assert vtt.startswith("WEBVTT\n\n1\n00:00:00.000 --> ") and "," not in vtt.split("-->")[1].split("\n")[0]
    last_end = max(float(m) for m in re.findall(r"--> \d\d:\d\d:(\d\d\.\d{3})", vtt))
    assert last_end <= EXPECTED_S + 0.01  # Ausgabe-Timeline, nicht Quellzeit
    ass = Path(paths["ass"]).read_text(encoding="utf-8")
    assert f"PlayResX: {w}" in ass and f"PlayResY: {h}" in ass

    # Ehrlichkeit: was der ffmpeg-Build nicht kann, steht als Hinweis im Ergebnis
    caps = render.capabilities()
    assert result.captions_burned is caps["subtitles"]
    if not caps["subtitles"]:
        assert any("subtitles-Filter" in n for n in result.notes)
    if not caps["drawtext"]:
        assert any("drawtext-Filter" in n for n in result.notes)
    else:
        assert result.title_card_drawn and result.hook_overlay_drawn


@requires_ffmpeg
def test_regression_checks_flag_wrong_duration_and_size(src):
    warnings = render.regression_checks(src, 5.0, 1080, 1920)
    assert any(w.startswith("Dauer weicht ab") for w in warnings)
    assert any(w.startswith("Auflösung 1280x720") for w in warnings)
    assert render.regression_checks(src.with_name("missing.mp4"), 1.0, 1, 1) == ["Ausgabedatei fehlt oder ist leer"]


def test_filter_graph_structure_without_ffmpeg(tmp_path):
    plan, paths, _ = _build("tiktok", "9:16", _words(), tmp_path)
    n_shots, n_segs = len(plan["shots"]), len(plan["segments"])
    args = render.input_args("src.mp4", plan)
    assert args.count("-i") == n_shots + n_segs and args[:2] == ["-ss", "1.000"]
    a = render.audio_chain(plan, n_shots, "loudnorm=I=-16.0:TP=-1.5:LRA=11.0", compressor=True)
    assert a.count("afade=t=in") == n_segs and a.count("afade=t=out") == n_segs and "d=0.020" in a
    assert f"concat=n={n_segs}:v=0:a=1[ac]" in a and "[ac]acompressor=" in a and a.endswith(f"aresample={render.AUDIO_RATE}[aout]")
    caps = {"subtitles": True, "drawtext": True, "loudnorm": True, "ebur128": True}
    font = render.font_file()
    assert font is not None and font.name in render.FONT_CANDIDATES
    v, notes, burned, title, hook, watermark = render.video_chain(plan, paths["ass"], font, caps, font.parent)
    assert watermark is False
    assert burned and title and hook and notes == []
    assert v.count("crop=") == n_shots and f"concat=n={n_shots}:v=1:a=0[vc]" in v
    assert "subtitles='" in v and ":fontsdir='" in v and v.count("drawtext=") >= 2 and "expansion=none" in v
    assert "enable='lt(t,2.50)'" in v and "enable='lt(t,3.00)'" in v and v.endswith("[vout]")
    v2, notes2, burned2, t2, h2, _wm2 = render.video_chain(plan, paths["ass"], None, {"subtitles": False, "drawtext": False}, None)
    assert not burned2 and not t2 and not h2 and len(notes2) == 2 and v2.endswith("[vc]null[vout]")
    assert render.needs_compressor(7.1) and not render.needs_compressor(7.0) and not render.needs_compressor(None)
    assert render.loudnorm_pass2(render.Loudness(-16, -1.5), {"input_i": -21.79, "input_tp": -14.46, "input_lra": 0.1, "input_thresh": -31.79, "target_offset": -0.03}).endswith(
        "measured_I=-21.79:measured_TP=-14.46:measured_LRA=0.10:measured_thresh=-31.79:offset=-0.03:linear=true:print_format=summary"
    )


def test_zoom_filter_expression_and_chain():
    """Push-in: Supersampling vor zoompan, linear bis zoom_to, ein Ausgabeframe je Eingabeframe."""
    from chopstr_worker.pipeline import render as r

    f = r.zoom_filter(1080, 1920, 25.0, 4.0, 1.08)
    assert "scale=2160:3840" in f          # doppelte Ausgabegröße gegen Stufen im Zoom
    assert "zoompan=" in f and "d=1" in f  # Länge bleibt unverändert
    assert "on/100" in f                   # 4 s bei 25 fps
    assert "s=1080x1920" in f and f.endswith("setsar=1")

    # Kurze Einstellungen bleiben still, lange bekommen den Zoom
    plan = {
        "output": {"width": 1080, "height": 1920, "fps": 25.0},
        "motion": {"zoom_to": 1.08, "min_shot_s": 1.2},
        "shots": [
            {"start": 0.0, "end": 0.5, "crop_x": 0, "crop_y": 0, "crop_w": 608, "crop_h": 1080, "layout": "single"},
            {"start": 0.5, "end": 5.0, "crop_x": 0, "crop_y": 0, "crop_w": 608, "crop_h": 1080, "layout": "single"},
        ],
        "segments": [{"start": 0.0, "end": 5.0, "role": "body"}],
        "sources": {"storage_key": "uploads/in.mp4"},
    }
    chain, _, _, _, _, _ = r.video_chain(plan, None, None, {"zoompan": True, "vstack": True}, None)
    assert "[v0]" in chain and "[v1]" in chain
    assert chain.count("zoompan=") == 1     # nur die lange Einstellung
    assert "zoompan" not in chain.split("[v0];")[0]

    # Ohne zoompan im ffmpeg bleibt es beim statischen Ausschnitt
    plain, _, _, _, _, _ = r.video_chain(plan, None, None, {"zoompan": False, "vstack": True}, None)
    assert "zoompan=" not in plain
