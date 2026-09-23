"""Heuristik-Provider ``local-heuristic``: deterministisch, schema-konform, ohne Netz und ohne Residency-Hook."""

from __future__ import annotations

import pytest

from chopstr_worker import config, heuristic_llm, providers_llm, residency
from chopstr_worker.pipeline import segment, story_engine, story_graph, story_score
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer", "wanted": "Zahlen", "exclude": "Werbung", "platform": "linkedin"}


@pytest.fixture
def no_network(monkeypatch):
    """Jeder Weg ins Netz (Host-Prüfung, HTTP-Client, boto3) würde den Test sofort abbrechen."""

    def boom(*a, **kw):
        raise AssertionError("Heuristik-Provider darf nie ins Netz oder in den Residency-Hook")

    monkeypatch.setattr(residency, "assert_eu_host", boom)
    monkeypatch.setattr(residency, "guarded_client", boom)
    monkeypatch.setattr(residency, "guarded_async_client", boom)


def _llm(tier: str = "standard") -> LLM:
    return LLM(Tenant(id="ws", tier=tier), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def test_provider_is_allowed_for_both_tiers_and_selected_by_env(monkeypatch):
    assert "local-heuristic" in residency.EU_OK and "local-heuristic" in residency.NON_US_CHAIN
    assert _llm("standard").model() == "heuristic-v1"
    assert _llm("sovereign").model() == "heuristic-v1"
    assert _llm().is_heuristic is True
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    config.reload()
    assert providers_llm.select_provider(Tenant(id="ws", tier="standard")) == "local-heuristic"
    assert providers_llm.select_provider(Tenant(id="ws", tier="sovereign")) == "local-heuristic"


def test_propose_is_deterministic_and_schema_conform(no_network):
    llm = _llm()
    sents = segment.sentences_from_words(demo_words())
    m1 = story_score.propose(sents, BRIEF, llm)
    m2 = story_score.propose(sents, BRIEF, llm)
    assert m1 == m2
    assert 1 <= len(m1) <= 3
    valid = {s.idx for s in sents}
    spans = []
    for m in m1:
        assert m["first_sent"] in valid and m["last_sent"] in valid and m["first_sent"] <= m["last_sent"]
        assert m["structure"] in story_score.STRUCTURES
        assert m["why"].startswith("Heuristik ohne Sprachmodell")
        assert m["prompt_version"] == "propose_moments_v1"
        est = heuristic_llm.estimate_seconds([{"text": s.text} for s in sents[m["first_sent"] : m["last_sent"] + 1]])
        assert 15.0 <= est <= 60.0
        spans.append((m["first_sent"], m["last_sent"]))
    for a, b in spans:
        for c, d in spans:
            assert (a, b) == (c, d) or b < c or d < a  # keine Überlappung


def test_score_fields_ranges_and_grounded_evidence(no_network):
    llm = _llm()
    sents = segment.sentences_from_words(demo_words())
    costs = []
    llm.cost_sink = costs.append
    r = story_score.score(sents[0:4], BRIEF, llm)
    for k in story_score.RUBRIC_SCHEMA["required"]:
        assert k in r
    for k in ("hook", "payoff", "specificity", "tension", "audience_fit"):
        assert isinstance(r[k], int) and 0 <= r[k] <= 10
    assert r["ungrounded_evidence"] == []  # Belege sind wörtliche Satzanfänge
    assert r["model_id"] == "heuristic-v1" and r["prompt_version"] == "score_clip_v2"
    assert r["is_humor"] is False and r["gate_passed"] is True
    assert r["specificity"] >= 6  # 40 Prozent, 2019, 30 Prozent
    assert costs and costs[0]["in"] == 0 and costs[0]["provider"] == "local-heuristic"
    assert story_score.score(sents[0:4], BRIEF, llm)["total"] == r["total"]

    # Frage am Anfang und Open-Loop-Ende werden erkannt.
    # Sätze 12 bis 13 beginnen mit der Frage eines ANDEREN Sprechers („Was würdest du heute anders
    # machen?“, SPEAKER_01). Seit die Heuristik aus der redaktionellen Grundlage liest, ist das kein
    # Hook mehr, sondern Anlauf (einstieg.keine_gastgeberfrage). Früher stand hier
    # ``r2["hook"] >= r["hook"] - 1``; die Erwartung ist mit der Regel gekippt.
    r2 = story_score.score(sents[12:14], BRIEF, llm)
    assert r2["gastgeberfrage"] is True
    assert r2["hook"] < r["hook"]
    r3 = story_score.score(sents[9:11], BRIEF, llm)
    assert r3["ends_before_answer"] is True and r3["gate_passed"] is False
    r4 = story_score.score(sents[9:10], BRIEF, llm)
    assert r4["needs_earlier_context"] is True  # „Und dann ...“


def test_confirm_returns_no_verdict(no_network):
    out = story_graph.confirm(_llm(), "Kernaussage", "Das heißt aber nicht, dass das gilt.", 21.0)
    assert out["misleading_without"] is None
    assert out["repair"] == "none" and out["reason"]
    assert out["prompt_version"] == "story_graph_confirm_v1"


def test_engine_with_heuristic_marks_results(no_network):
    report = story_engine.run(demo_words(), BRIEF, {}, {"seeds": [2]}, _llm("sovereign"))
    assert report.provider == "local-heuristic" and report.model_id == "heuristic-v1"
    assert report.candidates, report.discarded
    for c in report.candidates:
        assert c.model_id == "heuristic-v1"
        assert c.prompt_version == "score_clip_v2"
        assert "heuristic_only" in c.risk_flags
        assert c.why.endswith("Bewertung ohne Sprachmodell.")
        assert 12.0 <= c.duration_s <= 90.0
        for f in c.story_graph_flags:
            assert f["confirmed"] is None


def test_unknown_tool_raises_and_parse_ignores_noise():
    with pytest.raises(RuntimeError, match="kennt das Tool"):
        heuristic_llm.answer("unknown_tool", "x")
    parsed = heuristic_llm.parse_numbered("Zielgruppe: x\n[3] (SPEAKER_01) Hallo Welt.\nkein Satz\n[4] (?) Noch einer?")
    assert parsed == [{"idx": 3, "speaker": "SPEAKER_01", "text": "Hallo Welt."}, {"idx": 4, "speaker": "?", "text": "Noch einer?"}]
    assert heuristic_llm.propose_moments("nur Text ohne Sätze") == {"moments": []}
