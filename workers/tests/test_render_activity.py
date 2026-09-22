"""Activity ``render_pack`` mit Fake-DB, lokalem Storage, Heuristik-Provider und echtem ffmpeg (kein Netz, kein Modell)."""

from __future__ import annotations

import pytest

from chopstr_worker import config
from chopstr_worker.activities import render as act_render
from chopstr_worker.activities.render import STEP_RENDER
from tests.conftest import make_test_video, requires_ffmpeg
from tests.transcript_fixtures import make_words

SCRIPT = [
    ("SPEAKER_00", "Ehrlich gesagt war das der teuerste Fehler meiner Karriere.", 3.0),
    ("SPEAKER_00", "Wir haben 40 Prozent Marge verloren, aber das gilt nicht für jede Firma.", 3.5),
    ("SPEAKER_01", "Was würdest du heute anders machen?", 2.0),
    ("SPEAKER_00", "Ich würde die Preise nie wieder unter die Kosten setzen.", 3.0),
]
SEGMENTS = [{"start": 0.5, "end": 5.0, "role": "body"}, {"start": 6.0, "end": 13.0, "role": "body"}]


@pytest.fixture
def project(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    monkeypatch.setenv("RENDER_X264_PRESET", "ultrafast")
    config.reload()
    fake_context.settings = config.settings()
    video = make_test_video(tmp_path / "in.mp4", seconds=14.0)
    fake_context.store.put_file("sources", "uploads/in.mp4", video)
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, country="DE", address="du", default_platform="linkedin", caption_preset="corporate_third")
    sid = fake_db.add_source(
        wid, "uploads/in.mp4", brand_profile_id=pid, width=640, height=360, fps=25.0, duration_s=14.0, status="ready",
        brief={"is_ad": True}, rights_status="third_party", source_owner="Podcast XY", source_title="Folge 3", source_url=None,
    )  # fmt: skip
    fake_db.add_transcript_version(sid, make_words(SCRIPT, t0=0.5, gap_s=0.5))
    cid = fake_db.add_candidate(sid, SEGMENTS, rubric={"suggested_title_card": "Preise im Handwerk"})
    return {"wid": wid, "sid": sid, "cid": cid}


@requires_ffmpeg
def test_render_pack_writes_clip_hook_captions_events_and_costs(fake_db, fake_context, project):
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    clip = fake_db.clips[clip_id]
    assert clip["status"] == "rendered" and clip["render_error"] is None and clip["destination"] == "tiktok"
    assert clip["platform"] == "tiktok" and clip["aspect"] == "9:16" and clip["title_card"] == "Preise im Handwerk"
    assert clip["ad_label"] == "Anzeige"  # DE plus is_ad
    assert clip["file_key"].startswith(f"renders/{clip_id}/") and clip["file_key"].endswith(".mp4")
    base = clip["file_key"][: -len(".mp4")]
    assert clip["srt_key"] == base + ".srt" and clip["vtt_key"] == base + ".vtt" and clip["poster_key"] == base + ".jpg"
    for key in (clip["file_key"], clip["srt_key"], clip["vtt_key"], clip["poster_key"], base + ".ass"):
        assert fake_context.store.exists("derived", key)
    assert (clip["width"], clip["height"]) == (1080, 1920) and clip["fps"] == 25.0
    assert abs(clip["duration_s"] - 11.5) <= 0.3
    assert clip["loudness"]["preset"] == "master" and -17.0 <= clip["loudness"]["integrated_lufs"] <= -15.0
    assert clip["loudness"]["true_peak_dbtp"] <= -1.0
    assert clip["provenance"] == {
        "c2pa": "skipped", "reason": "c2patool nicht installiert", "ai_label_required": False, "ai_features": [],
        "source_credit": "Quelle: Podcast XY, „Folge 3“", "ad_label": "Anzeige",
    }  # fmt: skip
    plan = clip["render_plan"]
    assert plan["contract"] == "render_plan_v1" and plan["reframe"]["strategy"] == "neutral" and plan["reframe"]["detector"] == "none"
    assert plan["captions"]["preset"] == "tiktok_bold" and plan["hook_overlay"]["seconds"] == 3.0
    assert plan["sources"] == {"storage_key": "uploads/in.mp4", "transcript_version": 1, "hook_version": 1, "candidate_id": project["cid"]}
    assert plan["title_card"] == {"text": "Preise im Handwerk", "seconds": 2.5}
    assert isinstance(clip["cps_warnings"], list) and isinstance(clip["fidelity_warnings"], list)
    assert clip["speaker_positions"] is None  # neutral: keine Positionen vorgeschlagen
    assert clip["rendered_at"] is not None

    hooks = [h for h in fake_db.hook_versions if h["clip_id"] == clip_id]
    assert len(hooks) == 1 and hooks[0]["version"] == 1 and hooks[0]["origin"] == "llm"
    assert len(hooks[0]["variants"]) == 5 and hooks[0]["model_id"] == "heuristic-v1" and hooks[0]["prompt_version"] == "hooks_v1"
    assert set(hooks[0]["post_captions"]) == {"tiktok", "reels", "shorts", "linkedin"}
    assert plan["hook_overlay"]["text"] == hooks[0]["onscreen_hook"]

    caps = [c for c in fake_db.caption_versions if c["clip_id"] == clip_id]
    assert len(caps) == 1 and caps[0]["version"] == 1 and caps[0]["origin"] == "auto" and caps[0]["preset"] == "tiktok_bold"
    assert caps[0]["cards"] and set(caps[0]["cards"][0]) == {"start", "end", "lines"} and caps[0]["ass_key"] == base + ".ass"
    assert caps[0]["cards"][0]["start"] >= 0.0 and caps[0]["cards"][-1]["end"] <= 11.5 + 0.01
    assert plan["captions"]["cards"] == len(caps[0]["cards"])

    statuses = fake_db.statuses(STEP_RENDER)
    assert statuses[0] == "started" and statuses[-1] == "finished"
    phases = [e["payload"]["phase"] for e in fake_db.events_for(STEP_RENDER) if e["status"] == "progress"]
    assert phases == ["copy", "reframe", "captions", "encode", "provenance"]
    assert all(e["payload"]["clip_id"] == clip_id for e in fake_db.events_for(STEP_RENDER) if e["status"] == "progress")
    fin = fake_db.events_for(STEP_RENDER)[-1]["payload"]
    assert fin["clip_id"] == clip_id and fin["c2pa"] == "skipped" and fin["hook_version"] == 1 and fin["cached"] is False
    assert fin["regression_warnings"] == [] and fin["llm_provider"] == "local-heuristic"
    assert any("neutral" in n for n in fin["notes"])
    assert fake_db.sources[project["sid"]]["status"] == "ready"  # Quellstatus bleibt unberührt

    cost = fake_db.job_costs[-1]
    assert cost["job_type"] == "render" and cost["clip_id"] == clip_id and cost["cpu_seconds"] > 0
    assert cost["source_minutes"] == pytest.approx(11.5 / 60, abs=0.001) and cost["storage_bytes"] > 0


@requires_ffmpeg
def test_rerender_uses_highest_manual_hook_version_and_new_hash(fake_db, fake_context, project):
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    first_key = fake_db.clips[clip_id]["file_key"]
    fake_db.add_hook_version(clip_id, origin="manual", spoken_hook="Manuell gesprochen", onscreen_hook="Manueller Hook im Bild", pattern="contrarian")

    same = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    assert same == clip_id
    clip = fake_db.clips[clip_id]
    assert clip["status"] == "rendered" and clip["file_key"] != first_key
    assert clip["render_plan"]["sources"]["hook_version"] == 2
    assert clip["render_plan"]["hook_overlay"]["text"] == "Manueller Hook im Bild"
    assert len([h for h in fake_db.hook_versions if h["clip_id"] == clip_id]) == 2  # keine neue LLM-Version
    assert [c["version"] for c in fake_db.caption_versions if c["clip_id"] == clip_id] == [1, 2]
    fin = fake_db.events_for(STEP_RENDER)[-1]["payload"]
    assert fin["hook_version"] == 2 and fin["hook_origin"] == "manual" and fin["llm_provider"] is None


@requires_ffmpeg
def test_rerender_with_same_inputs_is_skipped(fake_db, fake_context, project):
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "shorts")
    key = fake_db.clips[clip_id]["file_key"]
    n_caps = len(fake_db.caption_versions)
    act_render.run_render_pack(fake_context, project["cid"], "shorts")
    fin = fake_db.events_for(STEP_RENDER)[-1]
    assert fin["status"] == "finished" and fin["payload"]["skipped"] is True and fin["payload"]["file_key"] == key
    assert fake_db.clips[clip_id]["status"] == "rendered" and len(fake_db.caption_versions) == n_caps


@requires_ffmpeg
def test_existing_draft_clip_and_linkedin_defaults(fake_db, fake_context, project):
    draft = fake_db.add_clip(project["sid"], project["cid"], "linkedin", SEGMENTS, title_card="Eigener Titel", speaker_positions={"SPEAKER_00": 0})
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "linkedin")
    assert clip_id == draft and len(fake_db.clips) == 1
    clip = fake_db.clips[clip_id]
    assert clip["aspect"] == "4:5" and (clip["width"], clip["height"]) == (1080, 1350)
    plan = clip["render_plan"]
    assert plan["hook_overlay"] is None and plan["title_card"]["text"] == "Eigener Titel"
    assert plan["captions"]["preset"] == "corporate_third"  # Standardplattform des Profils: dessen Preset
    assert plan["captions"]["safe_zone"]["top"] == round(120 * 1350 / 1920)
    assert clip["speaker_positions"] == {"SPEAKER_00": 0}  # aus der UI bestätigt, bleibt erhalten
    assert clip["provenance"]["ad_label"] is None  # Draft der Web-App ohne ad_label


def test_failure_marks_clip_failed_with_german_error(fake_db, fake_context, project):
    fake_db.sources[project["sid"]]["storage_key"] = "uploads/fehlt.mp4"
    with pytest.raises(FileNotFoundError):
        act_render.run_render_pack(fake_context, project["cid"], "reels")
    clip = next(iter(fake_db.clips.values()))
    assert clip["status"] == "failed" and clip["render_error"].startswith("Rendern fehlgeschlagen: ")
    ev = fake_db.events_for(STEP_RENDER)[-1]
    assert ev["status"] == "failed" and ev["message"] == clip["render_error"]
    assert fake_db.sources[project["sid"]]["status"] == "ready"


def test_unknown_destination_and_candidate(fake_db, fake_context, project):
    with pytest.raises(ValueError, match="Unbekanntes Ziel"):
        act_render.run_render_pack(fake_context, project["cid"], "youtube")
    with pytest.raises(LookupError):
        act_render.run_render_pack(fake_context, "00000000-0000-0000-0000-000000000000", "tiktok")
    assert fake_db.clips == {}


def test_helpers_fidelity_and_preset():
    words = make_words(SCRIPT, t0=0.5, gap_s=0.5)
    cut = [{"start": 0.5, "end": 6.5, "role": "body"}, {"start": 7.0, "end": 13.0, "role": "body"}]
    warns = act_render.fidelity_warnings(words, cut, 0.5, 13.0)
    assert any(w["type"] == "negation_removed" for w in warns)  # "nicht" fällt in die Lücke 6,5 bis 7,0
    assert act_render.fidelity_warnings(words, [{"start": 0.5, "end": 13.0, "role": "body"}], 0.5, 13.0) == []
    assert act_render.caption_preset_for("linkedin", {"default_platform": "linkedin", "caption_preset": "corporate_third"}) == "corporate_third"
    assert act_render.caption_preset_for("tiktok", {"default_platform": "linkedin", "caption_preset": "corporate_third"}) == "tiktok_bold"
    assert act_render.ad_label_for({"is_ad": True}, "AT") == "Werbung" and act_render.ad_label_for({}, "DE") is None
