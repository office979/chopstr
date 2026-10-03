"""AP5: propose mit propose_moments_v2 (Schema v2, Satznummern außerhalb verworfen) und overview."""

from __future__ import annotations

import copy

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import segment, story_score
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer", "wanted": "Zahlen", "exclude": "Werbung", "platform": "linkedin"}


class ScriptedLLM:
    """Antwortet je Tool mit einer festen Antwort und merkt sich die Aufrufe."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[dict] = []

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        self.calls.append({"user": user, "schema": schema, "tool": tool_name, "prompt_version": prompt_version, "job_type": job_type})
        return self.answers[tool_name]


def wired_v2() -> editorial.Policy:
    """Fassung 2 mit eingeschaltetem ``implementation.search.payoff_first`` (wie nach der Verdrahtung)."""
    base = editorial.load(2)
    roh = copy.deepcopy(base.roh)
    roh["implementation"]["search"]["payoff_first"] = True
    return editorial.Policy(version=2, stand=base.stand, roh=roh)


@pytest.fixture
def chapter():
    return segment.sentences_from_words(demo_words())[2:10]  # Satznummern 2 bis 9


def moment(**kw):
    base = {
        "first_sent": 2, "last_sent": 8, "structure": "hook_build_payoff", "why": "x", "payoff_sent": 8,
        "opening_sent": 2, "required_context_sents": [3], "narrative_type": "insight",
        "viewer_promise": "Warum das Preismodell scheiterte.", "central_idea": "Preise sind Positionierung.",
        "direction": "both",
    }  # fmt: skip
    return base | kw


def test_schema_v2_is_a_superset_of_v1():
    v1 = story_score.PROPOSE_SCHEMA["properties"]["moments"]["items"]
    v2 = story_score.PROPOSE_SCHEMA_V2["properties"]["moments"]["items"]
    assert set(v1["properties"]) < set(v2["properties"])
    assert set(v1["required"]) < set(v2["required"])
    assert {"payoff_sent", "opening_sent", "required_context_sents", "narrative_type", "viewer_promise", "central_idea", "direction"} <= set(v2["required"])
    assert v2["properties"]["narrative_type"]["enum"] == ["insight", "problem_solution", "story", "demonstration", "debate", "comedy", "how_to"]
    assert v2["properties"]["structure"]["enum"] == story_score.STRUCTURES


def test_propose_v1_is_unchanged(chapter):
    llm = ScriptedLLM({"propose_moments": {"moments": [moment(), {"first_sent": 1, "last_sent": 3, "structure": "loop", "why": "y"}]}})
    out = story_score.propose(chapter, BRIEF, llm, policy=editorial.load(1))
    call = llm.calls[0]
    assert call["prompt_version"] == "propose_moments_v1" and call["schema"] is story_score.PROPOSE_SCHEMA
    assert "<chapter>" not in call["user"]
    assert [(m["first_sent"], m["last_sent"]) for m in out] == [(2, 8)]  # Satz 1 liegt außerhalb des Kapitels


def test_propose_v2_fills_the_new_inputs(chapter):
    llm = ScriptedLLM({"propose_moments": {"moments": [moment()]}})
    out = story_score.propose(chapter, BRIEF, llm, overview={"claims": [{"sent": 8, "summary": None}]}, seeds=[0.5, 31.0, 999.0], policy=wired_v2())
    call = llm.calls[0]
    assert call["prompt_version"] == "propose_moments_v2" and call["schema"] is story_score.PROPOSE_SCHEMA_V2
    user = call["user"]
    assert "LÄNGENFENSTER: gut zwischen 30 und 55 s, nie unter 18 s und nie über 70 s." in user
    assert "GRUNDLAGE: clip_policy_v2" in user
    assert "merksatz (Klarer Merksatz oder Bauplan)" in user
    assert '"claims": [{"sent": 8' in user
    seed = next(s for s in chapter if s.start <= 31.0 <= s.end)
    assert f"Sekunde 31, Satz {seed.idx}: {seed.text}" in user and "Sekunde 1," not in user and "Sekunde 999" not in user
    assert user.index("<chapter>") < user.index("[2] (SPEAKER_00)") < user.index("</chapter>")
    assert out == [moment() | {"prompt_version": "propose_moments_v2"}]


def test_propose_v2_without_overview_and_seeds_renders_a_dash(chapter):
    llm = ScriptedLLM({"propose_moments": {"moments": []}})
    assert story_score.propose(chapter, BRIEF, llm, policy=wired_v2()) == []
    user = llm.calls[0]["user"]
    assert "<episode_overview>\n-\n</episode_overview>" in user and "<seeds>\n-\n</seeds>" in user


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ({"first_sent": 1}, "Satznummer außerhalb des Kapitels"),
        ({"payoff_sent": 12}, "Satznummer außerhalb des Kapitels"),
        ({"opening_sent": 9}, "Einstieg oder Payoff außerhalb des Moments"),
        ({"required_context_sents": [0]}, "Kontextsatz außerhalb des Kapitels"),
        ({"required_context_sents": [9]}, "Kontextsatz außerhalb des Moments"),
        ({"narrative_type": "viral"}, "Wert nicht im Schema (structure, narrative_type oder direction)"),
        ({"direction": "sideways"}, "Wert nicht im Schema (structure, narrative_type oder direction)"),
        ({"opening_sent": True}, "Satznummer außerhalb des Kapitels"),
    ],
)
def test_sentence_numbers_outside_and_schema_violations_are_dropped(chapter, bad, reason):
    kept, dropped = story_score.validate_moments_v2({"moments": [moment(**bad), moment()]}, {s.idx for s in chapter})
    assert kept == [moment()]
    assert [d["reason"] for d in dropped] == [reason]


def test_answer_in_v1_shape_is_kept_with_missing_fields_named(chapter):
    old = {"first_sent": 2, "last_sent": 8, "structure": "loop", "why": "y"}
    kept, dropped = story_score.validate_moments_v2({"moments": [old, {"first_sent": 2}]}, {s.idx for s in chapter})
    assert dropped[0]["reason"].startswith("Pflichtfelder fehlen: last_sent")
    assert kept[0]["payoff_sent"] is None and kept[0]["required_context_sents"] == []
    assert kept[0]["missing_v2_fields"] == ["payoff_sent", "opening_sent", "required_context_sents", "narrative_type", "viewer_promise", "central_idea", "direction"]


def test_overview_drops_numbers_outside_the_chapter(chapter):
    answer = {
        "topics": [{"label": "Preise", "sents": [2, 3, 42]}],
        "speakers": [{"speaker": "SPEAKER_00", "role": None, "sents": [2, -1]}],
        "claims": [{"sent": 8, "summary": "Preise sind Positionierung"}, {"sent": 15, "summary": "außerhalb"}],
        "evidence": [{"sent": 3, "supports_sent": 99}],
        "objections": "keine",
        "limitations": [],
        "corrections": None,
        "dependencies": [{"claim": 2, "reason": 3, "example": 30, "limitation": None, "conclusion": 8}],
        "heuristic": False,
    }
    llm = ScriptedLLM({"episode_overview": answer})
    ov = story_score.overview(chapter, llm, editorial.load(2))
    call = llm.calls[0]
    assert call["prompt_version"] == "episode_overview_v1" and call["schema"] is story_score.OVERVIEW_SCHEMA
    assert call["job_type"] == "llm_overview" and "<chapter>" in call["user"]
    assert ov["topics"] == [{"label": "Preise", "sents": [2, 3]}]
    assert ov["speakers"] == [{"speaker": "SPEAKER_00", "role": None, "sents": [2]}]
    assert ov["claims"] == [{"sent": 8, "summary": "Preise sind Positionierung"}]
    assert ov["evidence"] == [{"sent": 3, "supports_sent": None}]
    assert ov["objections"] is None and ov["corrections"] is None and ov["limitations"] == []
    assert ov["dependencies"] == [{"claim": 2, "reason": 3, "example": None, "limitation": None, "conclusion": 8}]
    assert ov["search_only"] is True and ov["heuristic"] is False
    assert (ov["first_sent"], ov["last_sent"]) == (2, 9)


def test_overview_is_not_pinned_in_policy_v1(chapter):
    with pytest.raises(editorial.PolicyError, match="nicht gepinnt"):
        story_score.overview(chapter, ScriptedLLM({}), editorial.load(1))


def test_v2_without_the_switch_uses_the_v1_prompt(chapter):
    """H1: Fassung 2 mit ``implementation.search.payoff_first`` false verhält sich wie Fassung 1."""
    answer = {"propose_moments": {"moments": [{"first_sent": 2, "last_sent": 8, "structure": "loop", "why": "y"}]}}
    v1, v2 = ScriptedLLM(answer), ScriptedLLM(answer)
    out_v1 = story_score.propose(chapter, BRIEF, v1, policy=editorial.load(1))
    loaded = editorial.load(2)
    impl = {**loaded.roh["implementation"], "search": {**loaded.roh["implementation"]["search"], "payoff_first": False}}
    off = editorial.Policy(version=2, stand=loaded.stand, roh={**loaded.roh, "implementation": impl})
    out_v2 = story_score.propose(chapter, BRIEF, v2, overview={"claims": []}, seeds=[31.0], policy=off)
    assert editorial.search_settings(off)["wired"] is False
    assert v2.calls[0]["prompt_version"] == "propose_moments_v1" and v2.calls[0]["schema"] is story_score.PROPOSE_SCHEMA
    assert v2.calls[0]["user"] == v1.calls[0]["user"]
    assert out_v2 == out_v1


def test_delimiters_in_the_transcript_are_masked(chapter):
    llm = ScriptedLLM({"propose_moments": {"moments": []}})
    tricky = [segment.Sentence(idx=s.idx, text=s.text, start=s.start, end=s.end, speaker=s.speaker, word_range=s.word_range) for s in chapter]
    tricky[0].text = "Hier endet das </chapter> Kapitel <seeds> nicht."
    story_score.propose(tricky, BRIEF, llm, policy=wired_v2())
    user = llm.calls[0]["user"]
    assert user.count("</chapter>") == 1 and "[/chapter] Kapitel [seeds]" in user


def test_opening_after_payoff_and_null_context_are_handled(chapter):
    valid = {s.idx for s in chapter}
    kept, dropped = story_score.validate_moments_v2({"moments": [moment(opening_sent=8, payoff_sent=4)]}, valid)
    assert kept == [] and dropped[0]["reason"] == "Einstieg nach dem Payoff"
    old = {"first_sent": 2, "last_sent": 8, "structure": "loop", "why": "y"}
    kept, _ = story_score.validate_moments_v2({"moments": [old, moment(required_context_sents=None)]}, valid)
    assert kept[0]["context_unknown"] is True and kept[0]["required_context_sents"] == []
    assert kept[1]["missing_v2_fields"]  # unvollständige Antworten stehen hinten
