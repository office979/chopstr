"""Einstiege vergleichen und Kritiker im Lauf (AP6b), Fassung 2 aus einer Kopie der Richtlinie, spaCy fest aus."""

from __future__ import annotations

import json

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import segment, story_engine
from tests.test_critic import SEARCH_OFF, brain, llm, wired  # noqa: F401  (Fixtures)
from tests.test_story_engine import BRIEF, DEFAULT_WEIGHTS
from tests.transcript_fixtures import demo_words, make_words


def distinct_script(chapters: int, sentences_per_chapter: int = 20, sentence_s: float = 12.0) -> list[tuple[str, str, float]]:
    """Viele Kapitel mit Sätzen aus verschiedenen Wörtern (nur Buchstaben), damit die Redundanzprüfung keine
    Spanne zusammenlegt."""

    def tag(n: int) -> str:
        letters = "bcdfghklmnprstvz"
        return letters[n // 256 % 16] + letters[n // 16 % 16] + letters[n % 16]

    return [
        ("SPEAKER_00", f"Kunde{tag(3 * n)} kauft Ware{tag(3 * n + 1)} trotz Preis{tag(3 * n + 2)}.", sentence_s)
        for n in range(chapters * sentences_per_chapter)
    ]


def _moment(first: int, last: int) -> dict:
    return {"first_sent": first, "last_sent": last, "structure": "hook_build_payoff", "why": "x"}


def test_alternatives_are_in_the_rubric_json(brain, llm, wired):  # noqa: F811
    wired(**SEARCH_OFF)
    brain.moments = lambda sents: [_moment(0, 5)]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    (c,) = report.candidates
    choice = c.rubric["opening_choice"]
    assert choice["chosen"] == choice["previous"] == c.first_sent == 0 and choice["changed"] is False
    alts = c.rubric["alternatives_considered"]
    assert 1 <= len(alts) <= story_engine.MAX_OPENINGS - 1 and choice["options"] == len(alts) + 1
    assert len({a["opening_sent"] for a in alts} | {c.first_sent}) == choice["options"], "verschiedene Sätze"
    for a in alts:
        assert a["reason"] and a["last_sent"] == c.last_sent and a["first_sent"] == a["opening_sent"] > 0
        assert set(a) >= {"opening_sent", "duration_s", "strength", "gates_failed", "length_allowed", "length_good", "reason"}
    row = json.loads(json.dumps(report.to_json(), ensure_ascii=False))["candidates"][0]
    assert row["rubric"]["alternatives_considered"] == alts


def test_opening_that_fails_a_gate_is_not_chosen(wired, monkeypatch):  # noqa: F811
    pol = wired(**SEARCH_OFF)
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    base = story_engine._run_gates

    # Der stärkste Einstieg reißt ein Gate: gewählt wird er trotzdem nicht.
    found = story_engine.compare_openings(words, sents, 0, 5, None, pol)
    alts = [a["opening_sent"] for a in found["alternatives_considered"]]
    strong = alts[0]
    monkeypatch.setattr(story_engine, "satz_staerke", lambda s, p, h: 99.0 if s.idx == strong else 0.0)
    monkeypatch.setattr(story_engine, "_run_gates", lambda w, s, a, b, p: {**base(w, s, a, b, p), "failed": ["reported_speech"]} if a == strong else {**base(w, s, a, b, p), "failed": []})
    out = story_engine.compare_openings(words, sents, 0, 5, None, pol)
    assert out["chosen"] == 0 and out["changed"] is False
    rejected = next(a for a in out["alternatives_considered"] if a["opening_sent"] == strong)
    assert rejected["reason"] == "reißt Gates: reported_speech"

    # Reißt dagegen der bisherige Einstieg ein Gate und ein anderer besteht alle, gilt der andere.
    monkeypatch.setattr(story_engine, "satz_staerke", lambda s, p, h: 0.0)
    monkeypatch.setattr(story_engine, "_run_gates", lambda w, s, a, b, p: {**base(w, s, a, b, p), "failed": ["unresolved_pronoun"] if a == 0 else []})
    out = story_engine.compare_openings(words, sents, 0, 5, None, pol)
    assert out["changed"] is True and out["chosen"] != 0
    assert out["reason"] == "bisheriger Einstieg reißt Gates: unresolved_pronoun"


def test_stronger_opening_needs_the_policy_margin(wired, monkeypatch):  # noqa: F811
    """Bei gleichen Gates und gleicher Länge bleibt der bisherige Einstieg, bis ein anderer um
    ``hook_vorziehen.mindest_vorsprung`` stärker ist (sonst wäre der Wechsel Selbstzweck)."""
    pol = wired(**SEARCH_OFF)
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    monkeypatch.setattr(story_engine, "_run_gates", lambda w, s, a, b, p: {"failed": []})
    monkeypatch.setattr(story_engine, "start_defects", lambda w, s, i, p: [])
    monkeypatch.setattr(story_engine, "_length_reason", lambda dur, mit_zugabe=False: None)
    monkeypatch.setattr(editorial.Policy, "laenge_ok", lambda self, sekunden: True)
    margin = float(pol.hook_vorziehen["mindest_vorsprung"])
    other = story_engine.compare_openings(words, sents, 0, 5, None, pol)["alternatives_considered"][0]["opening_sent"]

    monkeypatch.setattr(story_engine, "satz_staerke", lambda s, p, h: (margin - 0.5) if s.idx == other else 0.0)
    out = story_engine.compare_openings(words, sents, 0, 5, None, pol)
    assert out["chosen"] == 0
    assert next(a for a in out["alternatives_considered"] if a["opening_sent"] == other)["reason"].startswith("nicht deutlich stärker")

    monkeypatch.setattr(story_engine, "satz_staerke", lambda s, p, h: margin if s.idx == other else 0.0)
    out = story_engine.compare_openings(words, sents, 0, 5, None, pol)
    assert out["chosen"] == other and out["reason"].startswith("deutlich stärkerer Einstieg")
    assert next(a for a in out["alternatives_considered"] if a["opening_sent"] == 0)["reason"].startswith("schwächerer Einstieg")


def test_evaluate_span_takes_the_gate_clean_opening(brain, llm, wired):  # noqa: F811
    """Echte Gates: der Vorschlag beginnt mit Satz 7 und reißt boundary_negation_condition, Satz 8 besteht."""
    wired(**SEARCH_OFF)
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    out = story_engine.evaluate_span(words, sents, _moment(7, 13), BRIEF, llm, DEFAULT_WEIGHTS)
    assert isinstance(out, story_engine.CandidateResult)
    assert out.first_sent == 8 and out.rubric["opening_choice"]["changed"] is True
    (alt,) = [a for a in out.rubric["alternatives_considered"] if a["opening_sent"] == 7]
    assert alt["reason"].startswith("reißt Gates: ") and "boundary_negation_condition" in alt["gates_failed"]
    scored = [s for s in brain.calls if s[0] == "score_clip"]
    assert len(scored) == 2, "neuer Einstieg: genau eine Neubewertung"


def test_compare_openings_off_is_the_rollback(brain, llm, wired):  # noqa: F811
    wired(**{**SEARCH_OFF, "search.compare_openings": False})
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    out = story_engine.evaluate_span(words, sents, _moment(7, 13), BRIEF, llm, DEFAULT_WEIGHTS)
    assert out.first_sent == 7 and "alternatives_considered" not in out.rubric and "opening_choice" not in out.rubric
    assert editorial.compare_openings_enabled(editorial.load(1)) is False
    with pytest.raises(editorial.PolicyError, match="compare_openings"):
        editorial.compare_openings_enabled(wired(**{"search.compare_openings": "ja"}))


def test_v1_rubric_has_no_ap6b_keys(brain, llm, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    brain.moments = lambda sents: [_moment(0, 5)]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    for c in report.candidates:
        assert not {"alternatives_considered", "opening_choice", "critic", "critic_findings"} & set(c.rubric)
    assert not [t for t, _v in brain.calls if t == "critique_clip"]


@pytest.mark.parametrize("k", [1, 3])
def test_critic_runs_at_most_k_times(brain, llm, wired, k):  # noqa: F811
    wired(**SEARCH_OFF)
    words = make_words(distinct_script(6))

    def two_per_chapter(sents_in_prompt):
        a = sents_in_prompt[0]["idx"]
        return [_moment(a, a + 1), _moment(a + 3, a + 4)]

    brain.moments = two_per_chapter
    brain.confirm = {"misleading_without": False, "reason": "-", "repair": "none"}
    report = story_engine.run(words, BRIEF, {}, None, llm, max_candidates=k)
    calls = [t for t, _v in brain.calls if t == "critique_clip"]
    assert len(report.candidates) == k and len(calls) == k
    assert all(c.rubric["critic"]["status"] == "checked" for c in report.candidates)
    assert all("critic" not in c.rubric for c in report.verworfen), "verworfene Kandidaten sieht der Kritiker nicht"


def test_apply_critic_stops_at_the_limit(brain, llm, wired):  # noqa: F811
    pol = wired(**SEARCH_OFF)
    words = make_words(distinct_script(3))
    brain.moments = lambda sents: [_moment(sents[0]["idx"], sents[0]["idx"] + 1)]
    report = story_engine.run(words, BRIEF, {}, None, llm)
    brain.calls.clear()
    for c in report.candidates:
        c.rubric.pop("critic", None)
    sents = segment.sentences_from_words(words, rule="v2")
    story_engine.apply_critic(report, words, sents, llm, pol, 1, evaluated=len(report.candidates))
    assert [t for t, _v in brain.calls] == ["critique_clip"]
    assert [c.rubric["critic"]["status"] for c in report.candidates][1:] == ["not_checked"] * (len(report.candidates) - 1)
