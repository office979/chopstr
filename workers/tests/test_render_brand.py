"""Marken-Fonts und Logo-Wasserzeichen im Render (Phase 4): echte OTF als Asset im lokalen Storage, echtes ffmpeg."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from chopstr_worker import config
from chopstr_worker.activities import render as act_render
from chopstr_worker.activities.render import NOTE_FONT_MISSING, NOTE_LOGO_SVG, STEP_RENDER
from chopstr_worker.pipeline import captions_de, render, render_plan
from tests.conftest import WORKERS_ROOT, make_test_video, requires_ffmpeg
from tests.test_render_activity import SCRIPT, SEGMENTS
from tests.transcript_fixtures import make_words

INTER_OTF = WORKERS_ROOT / "fonts" / "Inter-Bold.otf"


def _logo_png(path: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=240x80:d=1", "-frames:v", "1", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.fixture
def project(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    monkeypatch.setenv("RENDER_X264_PRESET", "ultrafast")
    config.reload()
    fake_context.settings = config.settings()
    video = make_test_video(tmp_path / "in.mp4", seconds=14.0)
    fake_context.store.put_file("sources", "uploads/in.mp4", video)
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, country="AT", address="du", default_platform="tiktok", caption_preset="tiktok_bold")
    sha = hashlib.sha256(INTER_OTF.read_bytes()).hexdigest()
    font_key = f"brand/{pid}/font/{sha}.otf"
    fake_context.store.put_file("derived", font_key, INTER_OTF, "font/otf")
    font_id = fake_db.add_brand_asset(wid, pid, "font", font_key, mime_type="font/otf", sha256=sha, font_family="Inter", font_weight=700)
    logo = _logo_png(tmp_path / "logo.png")
    logo_sha = hashlib.sha256(logo.read_bytes()).hexdigest()
    logo_key = f"brand/{pid}/logo/{logo_sha}.png"
    fake_context.store.put_file("derived", logo_key, logo, "image/png")
    logo_id = fake_db.add_brand_asset(wid, pid, "logo", logo_key, mime_type="image/png", sha256=logo_sha)
    fake_db.brand_profiles[pid]["ci"] = {
        "fonts": {"primary_asset_id": font_id, "secondary_asset_id": None, "fallback": "Inter"},
        "logo_asset_id": logo_id,
        "watermark": {"enabled": True},
    }
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, width=640, height=360, fps=25.0, duration_s=14.0, status="ready")
    fake_db.add_transcript_version(sid, make_words(SCRIPT, t0=0.5, gap_s=0.5))
    cid = fake_db.add_candidate(sid, SEGMENTS, rubric={"suggested_title_card": "Preise im Handwerk"})
    return {"wid": wid, "pid": pid, "sid": sid, "cid": cid, "font_id": font_id, "font_sha": sha, "logo_id": logo_id}


def test_to_ass_uses_brand_font_family():
    words = [{"text": "Hallo", "start": 0.0, "end": 0.4}, {"text": "Welt", "start": 0.5, "end": 0.9}]
    default = captions_de.to_ass(words, 0.0, "tiktok_bold")
    branded = captions_de.to_ass(words, 0.0, "tiktok_bold", font_family="Haus Grotesk")
    assert "Style: Cap,Inter," in default and "Style: Cap,Haus Grotesk," in branded
    assert captions_de.to_ass(words, 0.0, "tiktok_bold", font_family="  ") == default


def test_brand_block_normalizes_watermark():
    assert render_plan.brand_block(None) == {
        "font_asset_id": None,
        "logo_asset_id": None,
        "watermark": {**render_plan.WATERMARK_DEFAULTS},
        "profil_id": None,
        "profil_fassung": None,
        "profil_name": None,
    }
    b = render_plan.brand_block({"font_asset_id": "f1", "logo_asset_id": "l1", "watermark": {"enabled": True, "opacity": 2.0}})
    assert b["watermark"]["enabled"] is True and b["watermark"]["opacity"] == 1.0 and b["watermark"]["width_ratio"] == 0.18
    assert render_plan.brand_block({"watermark": {"enabled": True}})["watermark"]["enabled"] is False  # ohne Logo kein Wasserzeichen


def test_brand_block_haelt_die_markenfassung_fest():
    """Mit welcher Fassung des Markenprofils wurde geclippt?

    Ohne diesen Vermerk laesst sich am fertigen Video nicht mehr sagen, welche Farben, Schriften
    und Regeln galten. Eine Agentur, die eine Marke aendert, muesste raten, welche Videos noch
    stimmen. Fehlt die Angabe, steht None da statt einer erfundenen Zahl.
    """
    b = render_plan.brand_block({"profil_id": "p1", "profil_fassung": 4, "profil_name": "Kunde A"})
    assert b["profil_id"] == "p1" and b["profil_fassung"] == 4 and b["profil_name"] == "Kunde A"
    assert render_plan.brand_block({})["profil_fassung"] is None
    # Aus der Datenbank kommt die Version haeufig als Zeichenkette.
    assert render_plan.brand_block({"profil_fassung": "7"})["profil_fassung"] == 7


def test_watermark_filter_stays_inside_safe_zone():
    plan = {"output": {"width": 1080, "height": 1920}, "captions": {"safe_zone": {"top": 108, "bottom": 320, "left": 60, "right": 120}}, "brand": {"watermark": {"enabled": True, "opacity": 0.5, "width_ratio": 0.2}}}
    f = render.watermark_filter(plan, 7)
    assert f.startswith("[7:v]scale=216:-1") and "colorchannelmixer=aa=0.50" in f
    assert f.endswith("[vt][wm]overlay=x=W-w-120:y=H-h-320[vout]")


@requires_ffmpeg
def test_render_uses_brand_font_and_logo(fake_db, fake_context, project):
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    clip = fake_db.clips[clip_id]
    assert clip["status"] == "rendered" and clip["render_error"] is None
    plan = clip["render_plan"]
    assert plan["captions"]["font"] == "Inter" and plan["captions"]["preset"] == "tiktok_bold"
    assert plan["brand"]["font_asset_id"] == project["font_id"]
    assert plan["brand"]["logo_asset_id"] == project["logo_id"]
    assert plan["brand"]["watermark"] == {"enabled": True, "position": "bottom_right", "opacity": 0.85, "width_ratio": 0.18}
    # Die Fassung des Markenprofils landet im Plan und bleibt damit am gebauten Clip haengen.
    assert plan["brand"]["profil_fassung"] == project.get("brand_version", 1)
    font_local = fake_context.work_dir / "fonts" / f"{project['font_sha']}.otf"
    assert font_local.is_file() and font_local.stat().st_size == INTER_OTF.stat().st_size
    ass_key = clip["file_key"][: -len(".mp4")] + ".ass"
    assert "Style: Cap,Inter," in fake_context.store.get_bytes("derived", ass_key).decode("utf-8")
    fin = fake_db.events_for(STEP_RENDER)[-1]["payload"]
    assert fin["font"] == "Inter" and fin["brand"] == plan["brand"]
    assert NOTE_FONT_MISSING not in fin["notes"] and NOTE_LOGO_SVG not in fin["notes"]
    caps = render.capabilities()
    assert fin["watermark_drawn"] is caps["overlay"]
    assert fin["overlays_drawn"] is caps["drawtext"]
    assert fake_context.store.exists("derived", clip["file_key"]) and fake_context.store.exists("derived", clip["poster_key"])
    periods = list(fake_db.usage_periods.values())
    assert len(periods) == 1 and periods[0]["render_count"] == 1 and periods[0]["workspace_id"] == project["wid"]


@requires_ffmpeg
def test_render_falls_back_to_inter_with_notes(fake_db, fake_context, project):
    pid = project["pid"]
    svg_id = fake_db.add_brand_asset(project["wid"], pid, "logo", f"brand/{pid}/logo/x.svg", mime_type="image/svg+xml")
    fake_db.brand_profiles[pid]["ci"] = {
        "fonts": {"primary_asset_id": "00000000-0000-0000-0000-000000000000", "fallback": "Inter"},
        "logo_asset_id": svg_id,
        "watermark": {"enabled": True},
    }
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    clip = fake_db.clips[clip_id]
    assert clip["status"] == "rendered"
    plan = clip["render_plan"]
    assert plan["captions"]["font"] == "Inter" and plan["brand"]["font_asset_id"] is None and plan["brand"]["logo_asset_id"] is None
    assert plan["brand"]["watermark"]["enabled"] is False
    fin = fake_db.events_for(STEP_RENDER)[-1]["payload"]
    assert NOTE_FONT_MISSING in fin["notes"] and NOTE_LOGO_SVG in fin["notes"] and fin["watermark_drawn"] is False
    assert not (fake_context.work_dir / "fonts").exists()


def test_brand_assets_for_without_ci_is_empty(fake_context):
    out = act_render.brand_assets_for(fake_context, {})
    assert out["font_path"] is None and out["logo_path"] is None and out["notes"] == [] and out["watermark"] == {}
