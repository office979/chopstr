"""Decision Log: Einträge aus detect_candidates, copy_engine und Reframe-Strategie."""

from __future__ import annotations

import pytest

from chopstr_worker import config, decision_log, providers_llm
from chopstr_worker.activities import analyze
from chopstr_worker.pipeline import copy_de, copy_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler mit Zahlen", "exclude": "Werbung", "platform": "tiktok"}
CLIP = "Ehrlich gesagt war das der teuerste Fehler meiner Karriere. Wir haben 40 Prozent Marge verloren. Der Grund war ein falsches Preismodell."


def test_record_validates_and_returns_id(fake_db):
    did = decision_log.record(fake_db, "ws", "caption_preset", {"preset": "tiktok_karaoke"}, [{"preset": "linkedin_static"}], {"preset": "tiktok_karaoke"}, actor_type="user", clip_id="c1")
    assert did and fake_db.decision_log[0]["decision_type"] == "caption_preset" and fake_db.decision_log[0]["actor_type"] == "user"
    assert fake_db.decision_log[0]["alternatives"] == [{"preset": "linkedin_static"}]
    with pytest.raises(ValueError):
        decision_log.record(fake_db, "ws", "unknown", {}, [], {})
    with pytest.raises(ValueError):
        decision_log.record(fake_db, "ws", "publish", {}, [], {}, actor_type="robot")


def test_detect_candidates_logs_proposals_and_scores(fake_db, fake_context, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    fake_context.settings = config.reload()
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief=BRIEF, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    ids = analyze.run_detect_candidates(fake_context, sid)
    scored = [d for d in fake_db.decision_log if d["decision_type"] == "candidate_scored"]
    proposed = [d for d in fake_db.decision_log if d["decision_type"] == "candidate_proposed"]
    assert len(scored) == len(ids) and {d["candidate_id"] for d in scored} == set(ids)
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert len(proposed) == len(ids) + len(fin["discarded"]) and fin["decisions"] == len(scored) + len(proposed)
    d = scored[0]
    assert d["workspace_id"] == wid and d["brand_profile_id"] == pid and d["source_id"] == sid and d["actor_type"] == "ai"
    assert set(d["features"]["scores"]) == {"hook", "payoff", "specificity", "tension", "audience_fit"}
    assert set(d["features"]["gates"]) == {"standalone", "fidelity", "sentence_boundaries", "verb_bracket", "no_open_loop"}
    assert d["features"]["platform"] == "tiktok" and d["features"]["duration_s"] > 0 and d["features"]["structure"]
    assert "heuristic_only" in d["features"]["risk_flags"] and abs(sum(d["features"]["weights"].values()) - 1) < 0.01
    assert d["model_id"] == "heuristic-v1" and d["prompt_version"] == "score_clip_v1"
    assert d["chosen"]["candidate_id"] == d["candidate_id"]
    kept = [p for p in proposed if p["chosen"]["kept"]]
    assert len(kept) == len(ids) and all(p["candidate_id"] for p in kept)
    assert all(p["chosen"]["reason"] for p in proposed if not p["chosen"]["kept"])
    # Outbox: candidates.ready vor source.ready, beide ohne Transkriptinhalte
    assert [e["event"] for e in fake_db.outbox_events] == ["candidates.ready", "source.ready"]
    assert fake_db.outbox_events[0]["payload"] == {"source_id": sid, "candidates": len(ids), "gate_passed": fin["gate_passed"]}


def _heuristic() -> LLM:
    return LLM(Tenant(id="ws"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def test_copy_engine_decisions_and_pattern_order(fake_db):
    brand = copy_de.BrandProfile(address="du", country="AT", platform="tiktok")
    res = copy_engine.write_copy(_heuristic(), CLIP, brand, platforms=("tiktok",))
    assert [d["decision_type"] for d in res.decisions] == ["hook_variant_shown", "hook_selected"]
    shown, selected = res.decisions
    assert shown["features"]["patterns"] == list(copy_engine.HOOK_PATTERNS) and shown["features"]["n"] == 5 and shown["features"]["order_from_learning"] is False
    assert selected["chosen"]["pattern"] == res.pattern and selected["chosen"]["spoken"] == res.spoken_hook
    assert len(selected["alternatives"]) == 4 and res.pattern not in {a["pattern"] for a in selected["alternatives"]}
    assert selected["features"]["rule"] == "first_without_claim_issues" and selected["features"]["chosen_index"] == 0

    order = ["results_first", "mistake_warning", "contrarian", "open_loop", "identity_call"]
    res2 = copy_engine.write_copy(_heuristic(), CLIP, brand, platforms=("tiktok",), pattern_order=order)
    assert [v["pattern"] for v in res2.variants] == order and res2.pattern == "results_first"
    assert res2.decisions[0]["features"]["order_from_learning"] is True

    ids = decision_log.record_copy_result(fake_db, "ws", "clip-1", res2, brand_profile_id="bp", source_id="src", candidate_id="cand")
    assert len(ids) == 2
    rows = fake_db.decision_log
    assert rows[1]["decision_type"] == "hook_selected" and rows[1]["clip_id"] == "clip-1" and rows[1]["brand_profile_id"] == "bp"
    assert rows[1]["model_id"] == res2.model_id and rows[1]["prompt_version"] == "hooks_v1" and rows[1]["features"]["platform"] == "tiktok"


def test_order_variants_keeps_unknown_patterns_last():
    vs = [copy_engine.HookVariant(p, p, p) for p in ("identity_call", "unknown", "contrarian")]
    assert [v.pattern for v in copy_engine.order_variants(vs, ["contrarian", "identity_call"])] == ["contrarian", "identity_call", "unknown"]
    assert copy_engine.order_variants(vs, None) == vs


def test_record_reframe_strategy(fake_db):
    plan = {"platform": "tiktok", "aspect": "9:16", "reframe": {"strategy": "talking_head", "confidence": 0.8, "notes": ["x"]}}
    decision_log.record_reframe_strategy(fake_db, "ws", "clip-1", plan, source_id="s", candidate_id="c")
    row = fake_db.decision_log[-1]
    assert row["decision_type"] == "reframe_strategy" and row["chosen"] == {"strategy": "talking_head"} and row["actor_type"] == "ai"
    assert {a["strategy"] for a in row["alternatives"]} == {"two_speakers", "neutral", "slide_pip"}
    assert row["features"]["confidence"] == 0.8 and row["features"]["notes"] == 1 and row["features"]["platform"] == "tiktok"
    decision_log.record_reframe_strategy(fake_db, "ws", "clip-1", plan, override="slide_pip")
    row = fake_db.decision_log[-1]
    assert row["chosen"] == {"strategy": "slide_pip"} and row["actor_type"] == "user" and row["features"]["override"] == "slide_pip"
