"""T2 Stufen A bis C: mehrstufige Engine mit gemockten Modellen (kein Netz, keine Keys)."""

from __future__ import annotations

import re

import pytest

from chopstr_worker import config, costlog, editorial, heuristic_llm
from chopstr_worker.pipeline import mm_scan, segment, story_engine, tiered_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant

from .transcript_fixtures import demo_words, long_script, make_words

BRIEF = {"audience": "Gründer", "wanted": "Fehler mit Zahlen", "exclude": "-", "platform": "tiktok"}


class FakeTiers:
    """Antworten je Tool, merkt sich Stufe, Cache-Blöcke und Aufrufe. ``edit`` liefert die Editor-Antwort."""

    provider = "fake"
    is_heuristic = False

    def __init__(self, spans=((0, 3),), tier="base", log=None, edit=None):
        self.tier, self.spans = tier, list(spans)
        self.log = log if log is not None else []
        self.edit = edit

    def with_tier(self, tier):
        return FakeTiers(self.spans, tier, self.log, self.edit)

    def model(self):
        return f"fake-{self.tier}"

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score", policy_block=None, cache_prefix=None, stage=None):
        self.log.append({"tier": self.tier, "tool": tool_name, "prompt": prompt_version, "user": user,
                         "policy_block": policy_block, "cache_prefix": cache_prefix, "stage": stage})  # fmt: skip
        if tool_name == "prefilter_moments":
            nums = [int(x) for x in re.findall(r"^\[(\d+)\]", cache_prefix or "", re.MULTILINE)]
            return {"candidates": [
                {"first_sent": a, "last_sent": b, "type": "story", "why": "Fehler [LACHT] mit Zahl", "score": 8}
                for a, b in self.spans if a in nums and b in nums
            ]}  # fmt: skip
        if tool_name == "edit_clip":
            words = {int(i): w for i, w in re.findall(r"(\d+):(\S+)", user)}
            note = re.search(r"Satz (\d+) bis (\d+)", user)
            a, b = int(note.group(1)), int(note.group(2))
            if self.edit is not None:
                return self.edit(a, b, words)
            sents = segment.sentences_from_words(demo_words())
            sw, ew = sents[a].word_range[0], sents[b].word_range[1]
            return {
                "keep": True, "start_word": sw, "end_word": ew,
                "hook": {"start_word": sw, "end_word": sents[a].word_range[1], "text": "Der teuerste Fehler [LACHT]"},
                "title": "Teurer Fehler [SCHREI]", "onscreen_text": "40 Prozent weg",
                "post_text": {"tiktok": "Der teuerste Fehler. [LACHT] #gründen", "reels": "Marge weg.", "shorts": "Preis falsch."},
                "scores": {"hook": 8, "payoff": 7, "specificity": 9, "tension": 6, "audience_fit": 8},
                "evidence": {"hook": "teuerste Fehler"}, "needs_earlier_context": False, "ends_before_answer": False,
                "unresolved_references": [], "is_humor": False, "sensitive_topic": False, "why": "Zahl und Fehler.",
            }  # fmt: skip
        if tool_name == "score_clip":
            sents = heuristic_llm.parse_numbered(user)
            first = " ".join(sents[0]["text"].split()[:4]) if sents else ""
            return {"unresolved_references": [], "needs_earlier_context": False, "ends_before_answer": False,
                    **{k: 6 for k in story_engine.SCORE_KEYS}, **{f"{k}_evidence": first for k in story_engine.SCORE_KEYS},
                    "is_humor": False, "sensitive_topic": False, "suggested_title_card": "", "why": "Richter."}  # fmt: skip
        if tool_name == "confirm_qualification":
            return {"misleading_without": False, "reason": "passt", "repair": None}
        if tool_name == "critique_clip":
            return {"findings": [], "confirmed": False}
        if tool_name == "compare_clips":
            return {"winner": "tie", "reason": "gleich"}
        raise AssertionError(tool_name)

    def calls(self, tool):
        return [c for c in self.log if c["tool"] == tool]


@pytest.fixture(autouse=True)
def _no_engine_env(monkeypatch):
    monkeypatch.delenv("CHOPSTR_ENGINE", raising=False)
    monkeypatch.delenv("CHOPSTR_POLICY_VERSION", raising=False)


def test_engine_mode_env_and_policy(monkeypatch):
    assert tiered_engine.engine_mode(editorial.load(2)) == "classic"
    monkeypatch.setenv("CHOPSTR_ENGINE", "tiered")
    assert tiered_engine.engine_mode(editorial.load(1)) == "tiered"
    monkeypatch.setenv("CHOPSTR_ENGINE", "classic")
    assert tiered_engine.engine_mode(editorial.load(2)) == "classic"
    monkeypatch.setenv("CHOPSTR_ENGINE", "turbo")
    with pytest.raises(ValueError):
        tiered_engine.engine_mode()


def test_output_count_scales_with_length():
    cfg = tiered_engine.engine_settings(editorial.load(2))
    assert cfg["min_len_s"] == 8.0 and cfg["candidates_per_source_hour"] == 12.0
    assert tiered_engine.output_count(600, cfg) == 3  # Minimum
    assert tiered_engine.output_count(3600, cfg) == 12
    assert tiered_engine.output_count(3 * 3600, cfg) == 36
    assert tiered_engine.output_count(10 * 3600, cfg) == 40  # Maximum


def test_tiered_run_uses_tiers_cache_blocks_and_editor_scores():
    fake = FakeTiers(spans=[(0, 3), (4, 5)])
    events = [{"t_start": 24.0, "t_end": 25.0, "type": "laughter", "intensity": 0.9, "note": "", "source": "local"}]
    report = tiered_engine.run(demo_words(), BRIEF, {"country": "AT", "address": "du"}, {"seeds": [3]}, fake, events=events)
    pre, ed = fake.calls("prefilter_moments"), fake.calls("edit_clip")
    assert len(pre) == 1 and pre[0]["tier"] == "prefilter" and pre[0]["stage"] == "prefilter"
    assert pre[0]["policy_block"] and "<block>" in pre[0]["cache_prefix"] and "[LACHT] (00:24, stark)" in pre[0]["cache_prefix"]
    assert {c["tier"] for c in ed} == {"editor"} and len(ed) == 2
    assert ed[0]["cache_prefix"] == pre[0]["cache_prefix"]  # gleicher Block, gleicher Cache-Präfix
    # Die Bewertung des Editors ersetzt score_clip für seine Spanne
    assert fake.calls("score_clip") == []
    spans = {(c.first_sent, c.last_sent) for c in report.candidates}
    assert (0, 3) in spans
    # Short-Form: Satz 4 bis 5 dauert unter der harten Untergrenze der Richtlinie, aber über min_len_s
    sents = segment.sentences_from_words(demo_words())
    assert sents[5].end - sents[4].start < editorial.load().hart_min_s
    assert (4, 5) in spans
    c = next(c for c in report.candidates if (c.first_sent, c.last_sent) == (0, 3))
    t = c.rubric["tiered"]
    assert t["editor"]["title"] == "Teurer Fehler" and "[LACHT]" not in t["editor"]["post_text"]["tiktok"]
    assert "[LACHT]" not in t["editor"]["hook"]["text"] and "[LACHT]" not in t["prefilter"]["why"]
    assert c.rubric["scores"]["specificity"]["value"] == 9
    info = report.search["tiered"]
    assert info["version"] == "tiered_engine_v1" and info["output_count"] == 3
    assert report.engine == "tiered_engine_v1"
    assert report.prompt_versions[:2] == ["prefilter_v1", "editor_v1"]


def test_editor_word_outside_window_is_rejected():
    def bad(a, b, words):
        return {"keep": True, "start_word": 9999, "end_word": 10000, "hook": {"start_word": 0, "end_word": 0, "text": ""},
                "title": "", "post_text": {p: "" for p in ("tiktok", "reels", "shorts")},
                "scores": {k: 5 for k in story_engine.SCORE_KEYS}}  # fmt: skip

    fake = FakeTiers(spans=[(0, 3)], edit=bad)
    report = tiered_engine.run(demo_words(), BRIEF, {}, None, fake)
    assert report.candidates == []
    assert any(d["reason"] == "editor_rejected" for d in report.discarded)


def test_malformed_model_answers_fall_back_instead_of_aborting():
    def garbage(a, b, words):
        sents = segment.sentences_from_words(demo_words())
        return {"keep": True, "start_word": sents[a].word_range[0], "end_word": sents[b].word_range[1], "hook": "kein Objekt",
                "title": "T", "post_text": "auch kein Objekt", "scores": {"hook": "8/10", "payoff": float("nan")}}  # fmt: skip

    report = tiered_engine.run(demo_words(), BRIEF, {}, None, FakeTiers(spans=[(0, 3)], edit=garbage))
    c = next(c for c in report.candidates if (c.first_sent, c.last_sent) == (0, 3))
    assert c.rubric["tiered"]["editor"]["scores"]["hook"] == 0 and c.rubric["tiered"]["editor"]["post_text"]["tiktok"] == ""

    class Broken(FakeTiers):
        def with_tier(self, tier):
            return Broken(self.spans, tier, self.log, self.edit)

        def structured(self, *a, **k):
            if a[3] in ("prefilter_moments", "edit_clip"):
                raise RuntimeError("429 zu viele Anfragen")
            return super().structured(*a, **k)

    report = tiered_engine.run(demo_words(), BRIEF, {}, {"seeds": [3]}, Broken(spans=[(0, 3)]))
    info = report.search["tiered"]
    assert info["prefilter"]["errors"] and info["prefilter"]["errors"][0]["error"] == "RuntimeError"


def test_apply_editor_marks_cut_inside_sentence_and_snaps():
    sents = segment.sentences_from_words(demo_words())
    a0 = sents[0].word_range[0]
    out = {"keep": True, "start_word": a0 + 1, "end_word": sents[2].word_range[1], "hook": {"start_word": 9999, "end_word": 0, "text": "x"},
           "title": "T", "post_text": {}, "scores": {}}  # fmt: skip
    ed = tiered_engine.apply_editor(out, sents, 0, 4)
    assert (ed["first_sent"], ed["last_sent"]) == (0, 2) and ed["cut_inside_sentence"] == ["start"]
    assert ed["hook"]["start_word"] == sents[0].word_range[0]  # ungültiger Hook fällt auf den ersten Satz
    assert tiered_engine.apply_editor({**out, "keep": False}, sents, 0, 4) is None


def test_budget_exhausted_skips_model_stages_and_reports():
    fake = FakeTiers(spans=[(0, 3)])
    ledger = costlog.RunLedger(budget_tokens=10, s=config.Settings())
    ledger({"stage": "vorher", "model": "m", "in": 50})
    report = tiered_engine.run(demo_words(), BRIEF, {}, {"seeds": [3]}, fake, ledger=ledger)
    assert fake.calls("prefilter_moments") == [] and fake.calls("edit_clip") == []
    stages = {s["stage"] for s in report.search["tiered"]["skipped"]}
    assert {"prefilter", "editor"} <= stages


def test_heuristic_provider_runs_end_to_end_under_policy_v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    config.reload()
    llm = LLM(Tenant(id="ws", tier="standard"), s=config.settings())
    words = make_words(long_script(3, sentences_per_chapter=12, sentence_s=6.0))
    report = tiered_engine.run(words, BRIEF, {}, {"seeds": [30, 200]}, llm)
    info = report.search["tiered"]
    assert info["prefilter"]["local"] is True and info["prefilter"]["calls"] == 0 and info["editor"]["calls"] == 0
    assert report.to_json()["engine"] == "tiered_engine_v1"
    for c in report.candidates:
        assert c.rubric["tiered"]["editor"]["local"] is True


def test_tiered_run_under_policy_v2_with_fake_models(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    fake = FakeTiers(spans=[(0, 3), (12, 15)])
    report = tiered_engine.run(demo_words(), BRIEF, {"country": "AT"}, {"seeds": [3]}, fake)
    assert report.search["tiered"]["editor"]["calls"] == 2
    assert [(c.first_sent, c.last_sent) for c in report.candidates] == [(0, 3), (12, 15)]
    assert all(c.gate_passed for c in report.candidates)
    assert len(report.clip_candidates) == 2  # Vertrag clip_candidate_v1 wie im bisherigen Pfad
    # Kritiker und Bestätigung späterer Relativierungen laufen weiter, über die Richter-Stufe
    critic = fake.calls("critique_clip")
    assert len(critic) == 2 and {c["tier"] for c in critic} == {"judge"}
    assert fake.calls("score_clip") == []
    for c in report.candidates:
        assert "tiered" in c.rubric and c.rubric.get("quality_gate_decision")


def test_detect_activity_switches_to_tiered_by_env(fake_db, fake_context, monkeypatch):
    from chopstr_worker.activities import analyze

    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    config.reload()
    fake_context.settings = config.settings()
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief=BRIEF, audio_key="audio/x.wav", duration_s=80.0, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    fake_context.store.put_json("derived", analyze.heatmap_key_for("audio/x.wav", True), {"bin_s": 1, "n_bins": 80, "values": [], "seeds": [3, 50]})
    analyze.run_detect_candidates(fake_context, sid)
    classic = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert classic["prompt_versions"][0] == "propose_moments_v1"
    monkeypatch.setenv("CHOPSTR_ENGINE", "tiered")
    analyze.run_detect_candidates(fake_context, sid)
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["prompt_versions"][:3] == ["tiered_engine_v1", "prefilter_v1", "editor_v1"]
    assert fin["key"] != classic["key"] and fin["cached"] is False
    report = story_engine.DetectReport.from_json(fake_context.store.get_json("derived", fin["key"]))
    costs = report.search["tiered"]["costs"]
    assert costs["eur"] == 0.0 and costs["budget_eur"] is None and costs["source_hours"] == pytest.approx(80 / 3600, abs=1e-3)


def test_pseudo_sentences_never_become_word_indices():
    sents = segment.sentences_from_words(demo_words())
    events = [{"t_start": 6.0, "t_end": 7.0, "type": "shout", "intensity": 0.9}]
    text = tiered_engine.candidate_words_text(demo_words(), sents, 0, 2, events, 0.3)
    pseudo = [ln for ln in text.splitlines() if "[SCHREI]" in ln]
    assert pseudo and not re.search(r"\d+:", pseudo[0].split(")", 1)[-1])
    assert mm_scan.strip_pseudo(pseudo[0]) == ""
