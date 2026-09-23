"""Activity ``detect_candidates`` mit Fake-DB, lokalem Storage und Heuristik-Provider (kein Netz, kein Modell)."""

from __future__ import annotations

import re

import pytest

from chopstr_worker import config
from chopstr_worker.activities import analyze
from chopstr_worker.pipeline import story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import ResidencyError
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler mit Zahlen", "exclude": "Werbung", "platform": "linkedin"}


def _use_provider(monkeypatch, fake_context, provider: str, **env):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.reload()
    fake_context.settings = config.settings()


@pytest.fixture
def source(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief=BRIEF, audio_key="audio/x.wav", duration_s=80.0, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    fake_context.store.put_json("derived", analyze.heatmap_key_for("audio/x.wav", True), {"bin_s": 1, "n_bins": 80, "values": [], "seeds": [3, 50]})
    return sid


def test_writes_rows_events_and_status(fake_db, fake_context, source):
    ids = analyze.run_detect_candidates(fake_context, source)
    assert ids and len(ids) == len(fake_db.candidates)
    row = fake_db.candidates[0]
    assert row["source_id"] == source and row["version"] == 1
    assert row["segments"][0]["role"] == "body" and row["start_s"] < row["end_s"]
    assert row["rubric"]["contract"] == "candidates_v1"
    assert set(row["gates"]) == {"standalone", "fidelity", "sentence_boundaries", "verb_bracket", "no_open_loop"}
    assert row["model_id"] == "heuristic-v1" and row["prompt_version"] == "score_clip_v2"
    assert "heuristic_only" in row["risk_flags"]
    assert isinstance(row["why"], str) and row["why"].endswith(".")

    statuses = fake_db.statuses("detect_candidates")
    assert statuses[0] == "started" and statuses[-1] == "finished" and "progress" in statuses
    prog = next(e for e in fake_db.events_for("detect_candidates") if e["status"] == "progress")
    assert re.fullmatch(r"Kapitel 1 von 1 bewertet, \d+ Kandidaten", prog["message"])
    assert prog["progress"] == 1.0
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["candidates"] == len(ids) and fin["chapters"] == 1 and fin["provider"] == "local-heuristic"
    assert fin["model_id"] == "heuristic-v1" and fin["cached"] is False
    assert fin["prompt_versions"] == ["propose_moments_v1", "score_clip_v2", "story_graph_confirm_v1"]
    assert 0 <= fin["gate_passed"] <= fin["candidates"]

    assert [s for _sid, s in fake_db.status_history] == ["scoring", "ready"]
    assert fake_db.sources[source]["status"] == "ready"
    cost = fake_db.job_costs[-1]
    assert cost["job_type"] == "llm_candidates" and cost["provider"] == "local-heuristic" and cost["model_id"] == "heuristic-v1"
    assert cost["llm_input_tokens"] == 0
    assert fake_context.store.exists("derived", fin["key"])


def test_rerun_is_cached_and_keeps_rows_with_verdict(fake_db, fake_context, source, monkeypatch):
    first = analyze.run_detect_candidates(fake_context, source)
    judged = fake_db.candidates[0]
    # Menschliches Urteil: erkennbar an ``verdict_by``. Nur solche Zeilen überleben den zweiten Lauf,
    # die automatisch angenommenen (ohne ``verdict_by``) weichen dem neuen Ergebnis.
    judged["human_verdict"] = "accepted"
    judged["verdict_by"] = "11111111-1111-1111-1111-111111111111"
    judged["verdict_reason"] = None

    def boom(*a, **kw):
        raise AssertionError("zweiter Lauf darf kein LLM aufrufen")

    monkeypatch.setattr(LLM, "structured", boom)
    second = analyze.run_detect_candidates(fake_context, source)
    assert len(second) == len(first)
    assert judged["id"] in [c["id"] for c in fake_db.candidates]
    assert len(fake_db.candidates) == len(first) + 1
    assert not set(second) & set(first)  # neue Zeilen, alte ohne menschliches Urteil sind weg
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["cached"] is True and fin["candidates"] == len(first)
    assert fake_db.sources[source]["status"] == "ready"


def test_new_transcript_version_invalidates_cache(fake_db, fake_context, source):
    analyze.run_detect_candidates(fake_context, source)
    key1 = fake_db.events_for("detect_candidates")[-1]["payload"]["key"]
    fake_db.add_transcript_version(source, demo_words())
    analyze.run_detect_candidates(fake_context, source)
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["key"] != key1 and fin["cached"] is False and fin["transcript_version"] == 2


def test_runs_without_heatmap(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace(tier="sovereign")
    sid = fake_db.add_source(wid, "uploads/in.mp4", brief=BRIEF)
    fake_db.add_transcript_version(sid, demo_words())
    ids = analyze.run_detect_candidates(fake_context, sid)
    assert ids
    assert fake_db.sources[sid]["status"] == "ready"


def test_residency_error_fails_with_german_message(fake_db, fake_context, source, monkeypatch):
    _use_provider(monkeypatch, fake_context, "openai-us")
    with pytest.raises(ResidencyError):
        analyze.run_detect_candidates(fake_context, source)
    ev = fake_db.events_for("detect_candidates")[-1]
    assert ev["status"] == "failed"
    assert ev["message"].startswith("Kandidatensuche fehlgeschlagen: Anbieter openai-us verarbeitet nicht in der EU")
    assert fake_db.sources[source]["status"] == "failed"
    assert fake_db.candidates == []


def test_missing_model_fails_clearly(fake_db, fake_context, source, monkeypatch):
    _use_provider(monkeypatch, fake_context, "selfhost-eu", SELFHOST_LLM_BASE_URL="https://llm.intern", SELFHOST_LLM_MODEL="")
    with pytest.raises(RuntimeError, match="Kein Sprachmodell"):
        analyze.run_detect_candidates(fake_context, source)
    ev = fake_db.events_for("detect_candidates")[-1]
    assert ev["status"] == "failed" and "LLM_PROVIDER=local-heuristic" in ev["message"]
    assert fake_db.sources[source]["status"] == "failed"


def test_missing_transcript_fails_clearly(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/in.mp4")
    with pytest.raises(RuntimeError, match="Kein Transkript"):
        analyze.run_detect_candidates(fake_context, sid)
    assert fake_db.sources[sid]["status"] == "failed"


# -- Automatische Clips (kein Auswahlschritt mehr) ---------------------------------------------


def _result(start: float, end: float, *, gate_passed: bool, risk_flags: list[str]) -> story_engine.CandidateResult:
    """Ein Kandidat mit frei wählbaren Hinweisen, ohne die Story-Engine laufen zu lassen."""
    return story_engine.CandidateResult(
        segments=[{"start": start, "end": end, "role": "body"}],
        start_s=start,
        end_s=end,
        first_sent=0,
        last_sent=1,
        structure="how_to_list",
        rubric={"contract": "candidates_v1", "suggested_title_card": " Drei Fehler ", "scores": {}, "speakers": []},
        gates={"standalone": {"passed": gate_passed}, "fidelity": {"passed": True}},
        story_graph_flags=[],
        risk_flags=risk_flags,
        total=6.0,
        gate_passed=gate_passed,
        why="Darum.",
        model_id="heuristic-v1",
        prompt_version="score_clip_v1",
    )


def _fixed_report(monkeypatch, cands: list[story_engine.CandidateResult]) -> None:
    report = story_engine.DetectReport(
        candidates=cands, chapters=1, proposals=len(cands),
        prompt_versions=["propose_moments_v1"], model_id="heuristic-v1", provider="local-heuristic",
    )  # fmt: skip
    monkeypatch.setattr(story_engine, "run", lambda *a, **kw: report)


@pytest.fixture
def branded_source(fake_db, fake_context, monkeypatch):
    """Quelle mit Markenprofil, dessen Standard-Plattform ``tiktok`` ist."""
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, default_platform="tiktok")
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief=BRIEF, audio_key="audio/x.wav", duration_s=80.0, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    return sid


def test_clip_per_candidate_is_created_in_portrait(fake_db, fake_context, branded_source):
    ids = analyze.run_detect_candidates(fake_context, branded_source)
    clips = list(fake_db.clips.values())
    assert len(clips) == len(ids) >= 1
    assert sorted(c["candidate_id"] for c in clips) == sorted(ids)  # je Kandidat genau einer
    for clip in clips:
        assert clip["aspect"] == "9:16"  # immer Hochformat, unabhängig von der Plattform
        assert clip["platform"] == "tiktok" and clip["destination"] == "tiktok"
        assert clip["status"] == "draft" and clip["created_by"] is None
        assert clip["delete_after"] is None  # setzt der Trigger aus Migration 0006
        cand = next(c for c in fake_db.candidates if c["id"] == clip["candidate_id"])
        assert clip["composition"] == cand["segments"]
        assert cand["human_verdict"] == "accepted" and cand["verdict_reason"] == analyze.AUTO_VERDICT_REASON
        assert cand["verdict_by"] is None  # kein Mensch beteiligt
    assert fake_db.events_for("detect_candidates")[-1]["payload"]["clips"] == len(ids)


def test_clip_takes_title_card_and_ad_label_from_candidate_and_brief(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, country="DE", default_platform="linkedin")
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief={**BRIEF, "is_ad": True}, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    _fixed_report(monkeypatch, [_result(1.0, 20.0, gate_passed=True, risk_flags=[])])

    analyze.run_detect_candidates(fake_context, sid)
    clip = next(iter(fake_db.clips.values()))
    assert clip["title_card"] == "Drei Fehler" and clip["ad_label"] == "Anzeige"
    assert clip["platform"] == "linkedin" and clip["aspect"] == "9:16"  # Plattform aus dem Profil, Format fest


def test_second_run_creates_no_duplicate_clips(fake_db, fake_context, branded_source):
    first = analyze.run_detect_candidates(fake_context, branded_source)
    clips_after_first = {c["id"] for c in fake_db.clips.values()}
    assert len(clips_after_first) == len(first)

    second = analyze.run_detect_candidates(fake_context, branded_source)
    clips = list(fake_db.clips.values())
    assert len(clips) == len(second) == len(first)  # keine Doppel-Clips
    windows = [(c["start_s"], c["end_s"]) for c in fake_db.candidates]
    assert len(windows) == len(set(windows))  # und auch keine Doppel-Kandidaten
    assert {c["candidate_id"] for c in clips} == set(second)


def test_rendered_clip_survives_rerun_without_second_clip(fake_db, fake_context, branded_source):
    analyze.run_detect_candidates(fake_context, branded_source)
    done = next(iter(fake_db.clips.values()))
    done["status"] = "rendered"

    analyze.run_detect_candidates(fake_context, branded_source)
    assert done["id"] in fake_db.clips
    windows = [(fake_db.clips[c]["id"], _cand_window(fake_db, c)) for c in fake_db.clips]
    assert len({w for _cid, w in windows}) == len(windows)  # jedes Fenster genau einmal belegt


def _cand_window(fake_db, clip_id: str) -> tuple[float, float]:
    clip = fake_db.clips[clip_id]
    cand = next(c for c in fake_db.candidates if c["id"] == clip["candidate_id"])
    return round(float(cand["start_s"]), 1), round(float(cand["end_s"]), 1)


def test_candidate_with_hints_gets_a_clip_too(fake_db, fake_context, branded_source, monkeypatch):
    """Gründerentscheidung: auch Kandidaten mit Einwand oder Risikohinweis werden gerendert."""
    flagged = _result(1.0, 20.0, gate_passed=False, risk_flags=["claim", "sensitive_topic"])
    clean = _result(30.0, 55.0, gate_passed=True, risk_flags=[])
    _fixed_report(monkeypatch, [flagged, clean])

    ids = analyze.run_detect_candidates(fake_context, branded_source)
    assert len(ids) == 2 and len(fake_db.clips) == 2
    flagged_row = next(c for c in fake_db.candidates if not c["gate_passed"])
    assert flagged_row["risk_flags"] == ["claim", "sensitive_topic"]
    assert flagged_row["human_verdict"] == "accepted"
    assert any(c["candidate_id"] == flagged_row["id"] for c in fake_db.clips.values())


def test_platform_falls_back_to_reels_without_brand_profile(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/in.mp4", brief=BRIEF, status="analyzing")  # kein brand_profile_id
    fake_db.add_transcript_version(sid, demo_words())

    ids = analyze.run_detect_candidates(fake_context, sid)
    assert ids and fake_db.clips
    for clip in fake_db.clips.values():
        assert clip["platform"] == "reels" and clip["destination"] == "reels"
        assert clip["aspect"] == "9:16"


def test_platform_falls_back_to_reels_when_profile_has_no_default(fake_db, fake_context, source):
    """Markenprofil ohne ``default_platform`` (Fake-Profil der Fixture) landet ebenfalls bei ``reels``."""
    analyze.run_detect_candidates(fake_context, source)
    assert {c["platform"] for c in fake_db.clips.values()} == {"reels"}


def test_temporal_activity_creates_the_clips_too(fake_db, fake_context, branded_source):
    """Beide Wege laufen durch ``run_detect_candidates``: der lokale Worker direkt, Temporal über die
    Activity ``detect_candidates``. Deshalb hängt die Clip-Erzeugung nur an dieser einen Stelle."""
    ids = analyze.detect_candidates(branded_source)  # Activity-Einstieg, Kontext kommt aus der Fixture
    assert ids and len(fake_db.clips) == len(ids)
    assert {c["aspect"] for c in fake_db.clips.values()} == {"9:16"}


def test_local_worker_picks_up_the_auto_clips(fake_db, fake_context, branded_source):
    """Die Warteschlange des Renderers (draft + angenommener Kandidat) ist ohne Zutun gefüllt."""
    from chopstr_worker import local_worker

    ids = analyze.run_detect_candidates(fake_context, branded_source)
    rows = fake_db.execute(local_worker.SQL_PENDING_CLIPS, (10,)).fetchall()
    assert len(rows) == len(ids)
    assert {str(r[1]) for r in rows} == set(ids)
    assert {r[2] for r in rows} == {"tiktok"}
