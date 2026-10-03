"""AP5: deterministische Suche vom Payoff rückwärts und vom Einstieg vorwärts (payoff_search)."""

from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import payoff_search, segment
from tests.editorial_v1 import harness


@pytest.fixture
def pol():
    return editorial.load(2)


def sents_of(rows: list[tuple[str, str, float]]) -> list[dict]:
    """Sätze mit fortlaufenden Zeiten: ``(Sprecher, Text, Dauer)``."""
    out, t = [], 0.0
    for i, (speaker, text, dur) in enumerate(rows):
        out.append({"idx": i, "text": text, "speaker": speaker, "start": t, "end": t + dur})
        t += dur + 0.3
    return out


def case_sents(cid: str) -> tuple[dict, list[segment.Sentence]]:
    case = harness.load_case(cid)
    return case, segment.sentences_from_words(case["words"], rule="v2")


PRONOUN_STORY = [
    ("A", "Unsere neue Lagerleiterin Frau Brenner kam direkt aus der Gastronomie.", 6.0),
    ("A", "Sie hat in den ersten drei Monaten jede Schicht selbst mitgemacht.", 6.0),
    ("A", "Am Ende des Jahres lief das Lager ruhiger als je zuvor.", 5.0),
    ("A", "Deshalb stellen wir heute nach Haltung ein und nicht nach Lebenslauf.", 6.0),
]


def test_v1_has_no_search_section_and_fails_loudly():
    assert editorial.search_settings(editorial.load(1)) is None
    with pytest.raises(editorial.PolicyError, match="Abschnitt search"):
        payoff_search.find_payoffs(sents_of(PRONOUN_STORY), editorial.load(1))


def test_search_settings_come_from_policy_v2(pol):
    cfg = editorial.search_settings(pol)
    assert cfg["payoff_first"] is True and cfg["opening_first"] is True
    assert cfg["chapter_overlap_s"] == 30.0 and cfg["max_llm_calls_per_source_hour"] >= 1
    assert set(cfg["hook_type_markers"]) == set(editorial.SEARCH_HOOK_TYPES) == set(payoff_search.HOOK_FULFILLED_BY)
    assert cfg["wired"] is False  # implementation.search.payoff_first bleibt bis zur Verdrahtung aus


def test_payoff_is_found_with_type_and_evidence(pol):
    hits = {h["payoff_sent"]: h for h in payoff_search.find_payoffs(sents_of(PRONOUN_STORY), pol)}
    assert hits[3]["payoff_type"] == "consequence" and hits[3]["evidence_sent"] == 3
    assert hits[3]["needs_sents"] == [2]  # „Deshalb“ braucht den Satz davor


def test_resolution_and_punchline_from_fixtures(pol):
    _case, sents = case_sents("instruction_in_transcript")
    hits = {h["payoff_sent"]: h for h in payoff_search.find_payoffs(sents, pol)}
    assert hits[4]["payoff_type"] == "resolution" and hits[4]["evidence_sent"] == 3  # Antwort auf die W-Frage
    _case, sents = case_sents("punchline_setup")
    hits = {h["payoff_sent"]: h for h in payoff_search.find_payoffs(sents, pol)}
    assert hits[3]["payoff_type"] == "punchline" and hits[3]["evidence_sent"] == 1  # Setup „neben den Toiletten“


def test_laughter_counts_only_when_the_heatmap_has_it(pol):
    rows = sents_of([("A", "Wir standen also mit drei Leuten vor einer leeren Halle.", 4.0)])
    assert payoff_search.find_payoffs(rows, pol) == []
    hit = payoff_search.find_payoffs(rows, pol, heat={"bin_s": 1.0, "laughter": [0, 0, 0, 0, 1]})
    assert hit[0]["payoff_type"] == "laughter"


def test_backtrack_stops_before_the_pronoun(pol):
    """Der Einstieg „Sie hat …“ hat keinen Bezug; der Rückweg geht einen Satz weiter zu „Frau Brenner“."""
    rows = sents_of(PRONOUN_STORY)
    assert payoff_search.opening_defects(rows, 1, pol) == ["Pronomen ohne Bezug am Anfang („Sie“)"]
    back = payoff_search.backtrack_opening(rows, 3, pol)
    assert back["opening_sent"] == 0 and back["first_sent"] == 0 and back["last_sent"] == 3
    assert back["required_context_sents"] == [2]


def test_backtrack_follows_the_given_gate(pol):
    rows = sents_of(PRONOUN_STORY)
    back = payoff_search.backtrack_opening(rows, 3, pol, gate_fn=lambda n: n == 2)
    assert back["opening_sent"] == 2
    assert payoff_search.backtrack_opening(rows, 3, pol, gate_fn=lambda n: False) is None


def test_backtrack_does_not_open_on_another_speakers_question(pol):
    case, sents = case_sents("punchline_setup")
    back = payoff_search.backtrack_opening(sents, 5, pol)
    assert back["opening_sent"] == 1  # nicht die Gastgeberfrage 0, aber mit dem Setup der Pointe
    a, b = sents[back["first_sent"]].word_range[0], sents[back["last_sent"]].word_range[1]
    harness.assert_clip_respects_case(case, [harness.segment_from_word_range(case, a, b)])


def test_reconcile_discards_opening_without_payoff_and_marks_both():
    payoff_first = [{"payoff_sent": 6, "opening_sent": 3, "first_sent": 3, "last_sent": 6, "payoff_type": "lesson"}]
    opening_first = [
        {"opening_sent": 3, "hook_type": "scene_with_stakes", "payoff_sent": 6, "first_sent": 3, "last_sent": 6, "payoff_type": "lesson"},
        {"opening_sent": 9, "hook_type": "recognizable_problem", "payoff_sent": None},
        {"opening_sent": 11, "hook_type": "decision_rule", "payoff_sent": 14, "first_sent": 11, "last_sent": 14, "payoff_type": "explanation"},
    ]  # fmt: skip
    res = payoff_search.reconcile(payoff_first, opening_first)
    assert [(p["first_sent"], p["last_sent"], p["direction"]) for p in res["proposals"]] == [(3, 6, "both"), (11, 14, "opening_only")]
    assert res["rejected"] == [{"opening_sent": 9, "hook_type": "recognizable_problem", "reason": "promise_unfulfilled"}]
    assert res["duplicates"] == []
    only = payoff_search.reconcile(payoff_first, [])
    assert only["proposals"][0]["direction"] == "payoff_only"


def test_opening_without_payoff_in_material_is_unfulfilled(pol):
    rows = sents_of(
        [
            ("A", "Kennst du das, wenn dein Kalender voll ist und nichts vorangeht?", 5.0),
            ("A", "Ich mach mir gleich noch einen Kaffee, Moment.", 3.0),
            ("A", "Der Termin am Nachmittag fällt übrigens aus.", 4.0),
        ]
    )
    res = payoff_search.search_moments(rows, pol)
    assert res["proposals"] == []
    assert {"opening_sent": 0, "hook_type": "recognizable_problem", "reason": "promise_unfulfilled"} in res["rejected"]


def test_weak_material_yields_no_proposal(pol):
    _case, sents = case_sents("weak_material")
    res = payoff_search.search_moments(sents, pol)
    assert res["payoffs"] == [] and res["proposals"] == []


def test_duplicates_of_the_same_statement_are_reported(pol):
    case, sents = case_sents("near_duplicate_candidates")
    res = payoff_search.search_moments(sents, pol)
    assert res["duplicates"] == [{"payoff_sent": 4, "kept": [0, 4], "dropped": [[1, 4]], "reason": "same_payoff"}]
    assert [(p["first_sent"], p["last_sent"]) for p in res["proposals"]] == [(0, 4)]


def test_instruction_in_transcript_is_neither_payoff_nor_opening(pol):
    case, sents = case_sents("instruction_in_transcript")
    a, b = case["expected"]["instruction_must_be_ignored"]["word_range"]
    instr = {s.idx for s in sents if s.word_range[0] <= b and s.word_range[1] >= a}
    res = payoff_search.search_moments(sents, pol)
    assert instr == {1}
    assert not instr & {h["payoff_sent"] for h in res["payoffs"]}
    assert not instr & {o["opening_sent"] for o in res["openings"]}
    assert res["proposals"] and all(p["opening_sent"] not in instr and p["payoff_sent"] not in instr for p in res["proposals"])
    p = res["proposals"][0]
    assert (p["first_sent"], p["payoff_sent"], p["payoff_type"]) == (0, 4, "resolution")  # Zuordnung „ich les sie mal vor“
    s0, s1 = sents[p["first_sent"]].word_range[0], sents[p["last_sent"]].word_range[1]
    harness.assert_clip_respects_case(case, [harness.segment_from_word_range(case, s0, s1)])


def test_every_proposal_on_the_test_set_respects_its_case(pol):
    for case in harness.load_cases():
        sents = segment.sentences_from_words(case["words"], rule="v2")
        for p in payoff_search.search_moments(sents, pol)["proposals"]:
            a, b = sents[p["first_sent"]].word_range[0], sents[p["last_sent"]].word_range[1]
            harness.assert_clip_respects_case(case, [harness.segment_from_word_range(case, a, b)])
            assert p["narrative_type"] in payoff_search.NARRATIVE_TYPES


def test_alternative_openings_are_different_sentences(pol):
    _case, sents = case_sents("near_duplicate_candidates")
    alts = payoff_search.alternative_openings(sents, 0, 4, pol)
    assert 1 <= len(alts) <= 3
    assert alts[0]["opening_sent"] == 0
    assert len({a["opening_sent"] for a in alts}) == len(alts)
    assert all(a["last_sent"] == 4 and a["opening_sent"] < 4 for a in alts)
    rows = sents_of(PRONOUN_STORY)
    assert [a["opening_sent"] for a in payoff_search.alternative_openings(rows, 0, 3, pol)] == [0, 2]  # 1 hat kein Bezug


def test_search_is_deterministic(pol):
    _case, sents = case_sents("punchline_setup")
    assert payoff_search.search_moments(sents, pol) == payoff_search.search_moments(sents, pol)
