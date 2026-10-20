"""Lane P2 (Launch Phase 2): Trichter im DetectReport (Vertrag für die Abdeckungsmessung an drei Stellen, Review 2E)
und Ausbeute bei wenigen oder keinen Kandidaten (Regel 15)."""

from __future__ import annotations

import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import dach_nlp, payoff_search, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.test_story_engine import BRIEF, SEARCH_ON, SEARCH_SCRIPT, brain, llm, wired  # noqa: F401
from tests.transcript_fixtures import demo_words, make_words

STAGE_KEYS = {"start_s", "end_s", "chapter", "source"}

WEAK_SCRIPT = [
    ("SPEAKER_01", "Hallo und herzlich willkommen zur heutigen Folge.", 4.0),
    ("SPEAKER_00", "Danke, schön dass ich da sein darf.", 3.0),
    ("SPEAKER_01", "Wo sitzt du gerade, im Büro oder zuhause?", 4.0),
    ("SPEAKER_00", "Ich sitze heute im Büro in Wien.", 3.0),
    ("SPEAKER_01", "Hört man mich gut, ist der Ton in Ordnung?", 4.0),
    ("SPEAKER_00", "Ja, alles gut, ich höre dich gut.", 3.0),
    ("SPEAKER_01", "Gut, dann starten wir gleich nach der kurzen Pause.", 4.0),
]


def _heuristic() -> LLM:
    return LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    editorial.clear_cache()
    yield editorial.load()
    editorial.clear_cache()


def _fixed_search(proposals, rejected=(), duplicates=()):
    return lambda chapter, pol, heat=None, gate_fn=None, words=None: {
        "proposals": [dict(p) for p in proposals], "rejected": [dict(r) for r in rejected],
        "duplicates": [dict(d) for d in duplicates], "payoffs": [], "openings": [],
    }  # fmt: skip


def test_funnel_has_three_stages_with_the_contract_fields(v2):
    report = story_engine.run(demo_words(), BRIEF, {}, None, _heuristic())
    funnel = report.funnel
    assert set(funnel) == {"pool", "after_gates", "offered"}
    for stage in funnel.values():
        for entry in stage:
            assert set(entry) >= STAGE_KEYS, entry
            assert entry["source"] in ("search", "model")
            assert isinstance(entry["start_s"], float) and entry["end_s"] > entry["start_s"]
    counts = report.funnel_counts
    assert counts["pool"] == len(funnel["pool"]) >= counts["after_gates"] == len(funnel["after_gates"])
    assert counts["after_gates"] >= counts["offered"] == len(funnel["offered"]) == len(report.candidates)
    assert [e["rank"] for e in funnel["offered"]] == list(range(1, len(report.candidates) + 1))
    assert {(e["first_sent"], e["last_sent"]) for e in funnel["offered"]} == {(c.first_sent, c.last_sent) for c in report.candidates}
    # Jeder nicht angebotene Vorschlag im Pool nennt seinen Grund; angebotene tragen keinen.
    offered = {(e["first_sent"], e["last_sent"]) for e in funnel["offered"]}
    dropped = [e for e in funnel["pool"] if "reason" in e]
    assert dropped and all(e["reason"] for e in dropped)
    assert counts["pool_reasons"] == {r: sum(1 for e in dropped if e["reason"] == r) for r in counts["pool_reasons"]}
    assert all("_key" not in e for e in funnel["pool"])
    assert offered


def test_funnel_reasons_come_from_the_existing_structures(brain, llm, wired, monkeypatch):  # noqa: F811
    """Modell und Suche schlagen dieselbe Aussage vor: der Modellvorschlag fällt als Dublette (Art aus
    ``search.duplicates``), die Dublette der Suche und der zu kurze Vorschlag tragen ihren Grund, der Verworfene ohne
    Spanne zählt nur in ``pool_without_span``."""
    wired(**SEARCH_ON)
    search = {"first_sent": 1, "last_sent": 3, "opening_sent": 1, "payoff_sent": 3, "required_context_sents": [], "direction": "payoff_only",
              "payoff_type": "lesson", "hook_type": None, "evidence_sent": 3, "duration_s": 21.8, "narrative_type": "insight"}  # fmt: skip
    rejected = [
        {"opening_sent": 0, "hook_type": "recognizable_problem", "reason": "promise_unfulfilled"},
        {"first_sent": 2, "last_sent": 3, "payoff_sent": 3, "reason": "too_short", "duration_s": 14.0},
    ]
    duplicates = [{"payoff_sent": 3, "kept": [1, 3], "dropped": [[2, 3]], "reason": "same_span"}]
    monkeypatch.setattr(payoff_search, "search_moments", _fixed_search([search], rejected, duplicates))
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 3, "structure": "hook_build_payoff", "why": "Modell", "payoff_sent": 3}]
    report = story_engine.run(make_words(SEARCH_SCRIPT), BRIEF, {}, {"seeds": [8.0]}, llm)
    pool = {(e["source"], e["first_sent"], e["last_sent"], e.get("reason")) for e in report.funnel["pool"]}
    assert ("model", 0, 3, "duplicate_payoff") in pool
    assert ("search", 1, 3, None) in pool
    assert ("search", 2, 3, "same_span") in pool
    assert ("search", 2, 3, "too_short") in pool
    assert report.funnel_counts["pool_without_span"] == 1
    assert report.funnel_counts["pool_without_span_reasons"] == {"promise_unfulfilled": 1}
    assert report.funnel_counts["pool_by_source"] == {"model": 1, "search": 3}
    # Die Gründe gibt es schon im Bericht: nichts wird doppelt erfunden.
    assert report.search["duplicate_counts"] == {"duplicate_payoff": 1, "same_span": 1}
    assert [(e["first_sent"], e["last_sent"]) for e in report.funnel["offered"]] == [(1, 3)]
    assert report.funnel["after_gates"][0]["source"] == "search"


def test_funnel_after_gates_keeps_limit_and_drops_quality_filters(brain, llm, wired, monkeypatch):  # noqa: F811
    """Wer nur an der Obergrenze scheitert, steht nach den Qualitätsfiltern noch im Trichter (``reason`` ``limit``);
    wer überlappt, nicht."""
    wired(**{"implementation.search.payoff_first": False, "implementation.output.max_candidates": False})
    from tests.transcript_fixtures import long_script

    w = make_words(long_script(3, sentences_per_chapter=20, sentence_s=12.0))

    def moments(sents):
        a = sents[0]["idx"]
        return [{"first_sent": a, "last_sent": a + 2, "structure": "hook_build_payoff", "why": "x"},
                {"first_sent": a + 1, "last_sent": a + 3, "structure": "hook_build_payoff", "why": "y"}]  # fmt: skip

    brain.moments = moments
    report = story_engine.run(w, BRIEF, {}, None, llm, max_candidates=1)
    reasons = {e.get("reason") for e in report.funnel["after_gates"]}
    assert reasons <= {None, "limit"} and "limit" in reasons
    assert len(report.funnel["offered"]) == 1
    pool_reasons = report.funnel_counts["pool_reasons"]
    assert pool_reasons.get("overlap", 0) >= 1 and pool_reasons.get("limit", 0) >= 1
    assert all(e["source"] == "model" for e in report.funnel["pool"])


def test_funnel_and_yield_survive_to_json_and_from_json(v2):
    report = story_engine.run(demo_words(), BRIEF, {}, None, _heuristic())
    data = report.to_json()
    assert data["funnel"] == report.funnel and data["funnel_counts"] == report.funnel_counts
    assert data["yield"] == report.yield_ and "yield_" not in data
    back = story_engine.DetectReport.from_json(data)
    assert back.funnel == report.funnel and back.funnel_counts == report.funnel_counts and back.yield_ == report.yield_
    assert back.to_json() == data


def test_v1_report_has_no_funnel_keys():
    editorial.clear_cache()
    report = story_engine.run(demo_words(), BRIEF, {}, None, _heuristic())
    data = report.to_json()
    for key in ("funnel", "funnel_counts", "yield", "chapter_meta", "heat", "ranking"):
        assert key not in data
    assert story_engine.DetectReport.from_json(data).yield_ == {}


def test_yield_counts_offered_per_hour_and_distinct(v2):
    report = story_engine.run(demo_words(), BRIEF, {}, None, _heuristic())
    y = report.yield_
    assert y["offered"] == len(report.candidates) > 0
    assert y["distinct"] <= y["offered"] and y["distinct_jaccard"] == 0.6
    w = demo_words()
    assert y["viable_per_source_hour"] == round(y["offered"] / ((w[-1]["end"] - w[0]["start"]) / 3600.0), 2)
    assert y["min_candidates_enforced"] is False and "reason" not in y


def test_yield_distinct_uses_the_jaccard_rule():
    """Zwei angebotene Kandidaten mit derselben Aussage zählen als einer (Lemma-Jaccard ab der Schwelle)."""

    def cand(first, text, total):
        return story_engine.CandidateResult(
            segments=[], start_s=float(first * 30), end_s=float(first * 30 + 20), first_sent=first, last_sent=first, structure="x",
            rubric={"text": text}, gates={}, story_graph_flags=[], risk_flags=[], total=total, gate_passed=True, why="",
            model_id="m", prompt_version=None,
        )  # fmt: skip

    same = "Unsere Preise waren viel zu niedrig, deshalb fehlte am Ende die Marge komplett."
    report = story_engine.DetectReport(candidates=[cand(0, same, 9.0), cand(5, same, 8.0), cand(9, "Recruiting dauert bei uns zwei Termine statt fünf.", 7.0)])
    sents = [type("S", (), {"start": 0.0, "end": 1800.0})()]
    y = story_engine.yield_summary(report, sents, editorial.load(1))
    assert y["offered"] == 3 and y["distinct"] == 2 and y["viable_per_source_hour"] == 6.0


def test_no_candidates_is_allowed_with_a_reason(v2):
    """Regel 15: schwaches Material ergibt null Kandidaten, ehrlich begründet; nichts wird aufgefüllt."""
    report = story_engine.run(make_words(WEAK_SCRIPT), {}, {}, None, _heuristic())
    assert report.candidates == []
    assert report.rejected_chapters and report.rejected_chapters[0]["reason"] == "no_viable_moment"
    assert any(d["reason"] == "no_viable_moment" for d in report.discarded)
    y = report.to_json()["yield"]
    assert y["offered"] == 0 and y["distinct"] == 0 and y["min_candidates_enforced"] is False
    assert "zulässig (Regel 15)" in y["reason"] and "no_viable_moment" in y["reason"]
    assert "—" not in y["reason"] and "–" not in y["reason"]
    assert report.funnel_counts["offered"] == 0


def test_no_minimum_candidate_rule_exists_in_the_policy(v2):
    assert "min_candidates" not in (v2.roh.get("output") or {})
