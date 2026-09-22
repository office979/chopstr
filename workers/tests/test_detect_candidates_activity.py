"""Activity ``detect_candidates`` mit Fake-DB, lokalem Storage und Heuristik-Provider (kein Netz, kein Modell)."""

from __future__ import annotations

import re

import pytest

from chopstr_worker import config
from chopstr_worker.activities import analyze
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
    assert row["model_id"] == "heuristic-v1" and row["prompt_version"] == "score_clip_v1"
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
    assert fin["prompt_versions"] == ["propose_moments_v1", "score_clip_v1", "story_graph_confirm_v1"]
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
    judged["human_verdict"] = "accepted"

    def boom(*a, **kw):
        raise AssertionError("zweiter Lauf darf kein LLM aufrufen")

    monkeypatch.setattr(LLM, "structured", boom)
    second = analyze.run_detect_candidates(fake_context, source)
    assert len(second) == len(first)
    assert judged["id"] in [c["id"] for c in fake_db.candidates]
    assert len(fake_db.candidates) == len(first) + 1
    assert not set(second) & set(first)  # neue Zeilen, alte ohne Urteil sind weg
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
