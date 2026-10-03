"""Testsatz editorial_v1 unter Fassung 2 (AP2, AP3): die Defekte zu Befund 1, 2 und 6 sind dort behoben.

``test_editorial_v1.py`` läuft unter der Standardfassung 1 und muss dort byte-gleich bleiben; seine
xfail-Marker zu Befund 1, 2 und 6 bleiben deshalb stehen. Hier laufen dieselben Prüfungen mit
``CHOPSTR_POLICY_VERSION=2`` und der Satzende-Regel der aktiven Richtlinie, ohne die Fälle zu ändern.
spaCy ist fest aus, damit der Rückfall geprüft wird (wie im Golden-Snapshot).

Hier stehen nur die Prüfungen zu Befund 1, 2 und 6, die unter Fassung 2 grün sind; einen xfail-Marker
gibt es in dieser Datei nicht. Was auch unter Fassung 2 noch rot ist (``forbidden_cut_ranges`` ohne
spaCy-Modell, „außerdem“ gegen „außer“, Pronomen-Tor der Heuristik), steht weiter als xfail in
``test_editorial_v1.py`` und gehört zu AP4 oder braucht das Modell im Image.
"""

from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import dach_nlp, segment, story_engine
from tests.editorial_v1 import harness
from tests.test_editorial_v1 import (
    CASES,
    _bracket,
    _mid_sentence_in_points,
    _mid_sentence_out_points,
    _rows,
    _softening_setup,
    grammatical_sentence,
    sentence_containing,
    span_sentence,
    words_of,
)


@pytest.fixture(autouse=True)
def policy_v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    yield editorial.load()
    editorial.clear_cache()


def rule() -> str:
    return editorial.sentence_rule(editorial.load())


def test_policy_v2_uses_sentence_rule_v2():
    assert rule() == "v2"


# -- Befund 1: Satzende und Satzzerlegung ----------------------------------------------------------


@pytest.mark.parametrize(("cid", "i"), [pytest.param(c, i, id=f"{c}:{i}:{t}") for c, i, t in _rows("sentence_end_after")])
def test_sentence_end_is_detected(cid, i):
    assert dach_nlp.is_sentence_end(CASES[cid]["words"], i, rule=rule()) is True


@pytest.mark.parametrize(("cid", "i"), [pytest.param(c, i, id=f"{c}:{i}:{t}") for c, i, t in _rows("no_sentence_end_after")])
def test_no_sentence_end_inside_a_sentence(cid, i):
    assert dach_nlp.is_sentence_end(CASES[cid]["words"], i, rule=rule()) is False


@pytest.mark.parametrize("cid", sorted(CASES))
def test_segmentation_matches_expected_sentence_ends(cid):
    exp = CASES[cid]["expected"]
    ends = {s.word_range[1] for s in segment.sentences_from_words(words_of(cid), rule=rule())}
    assert set(exp.get("sentence_end_after", [])) <= ends
    assert not ends & set(exp.get("no_sentence_end_after", []) or [])


@pytest.mark.parametrize("span_no", [0, 1])
def test_dramatic_pause_stays_inside_one_sentence(span_no):
    c = CASES["emotional_pause"]
    pauses = [p for p in c["expected"]["protected_spans"] if p["type"] == "pause_dramatic"]
    a, b = pauses[span_no]["word_range"]
    sents = segment.sentences_from_words(words_of("emotional_pause"), rule=rule())
    assert sentence_containing(sents, a) == sentence_containing(sents, b)


def test_hesitation_before_negation_does_not_split_the_clause():
    span = next(p for p in CASES["negation_sentence_end"]["expected"]["protected_spans"] if p["type"] == "negation")
    a, b = span["word_range"]
    sents = segment.sentences_from_words(words_of("negation_sentence_end"), rule=rule())
    assert sentence_containing(sents, a) == sentence_containing(sents, b)


def test_ordinal_and_abbreviation_do_not_end_sentences():
    sents = segment.sentences_from_words(words_of("imprecise_timestamps"), rule=rule())
    assert sents[0].text.startswith("Seit dem 1. März")
    sents = segment.sentences_from_words(words_of("conditional_recommendation"), rule=rule())
    assert any("z. B. die Urlaubsvertretung" in s.text for s in sents)


@pytest.mark.parametrize(("cid", "i"), [p.values for p in _mid_sentence_out_points()])
def test_sentence_gate_rejects_forbidden_out_point_mid_sentence(cid, i):
    w = words_of(cid)
    g = story_engine._satzgrenzen_gate(w, [span_sentence(w, 0, i)], 0, 0)
    assert g["passed"] is False
    assert "endet mitten im Satz" in g["detail"]


@pytest.mark.parametrize(("cid", "i"), [p.values for p in _mid_sentence_in_points()])
def test_sentence_gate_rejects_forbidden_in_point_mid_sentence(cid, i):
    w = words_of(cid)
    g = story_engine._satzgrenzen_gate(w, [span_sentence(w, i, len(w) - 1)], 0, 0)
    assert g["passed"] is False
    assert "mitten im Satz an" in g["detail"]


@pytest.mark.parametrize("cid", sorted(CASES))
def test_sentence_gate_accepts_the_whole_case(cid):
    w = words_of(cid)
    assert story_engine._satzgrenzen_gate(w, [span_sentence(w, 0, len(w) - 1)], 0, 0)["passed"] is True


# -- Befund 6: Ende nicht auf der Abschwächung ------------------------------------------------------


def test_context_extension_does_not_end_on_softening_sentence():
    """Unter Fassung 1 endet die Heilung auf „…vor Ort.“ (Wortindex 58, verbotener Out-Point). Unter
    Fassung 2 endet sie nie auf dem „Wobei“-Satz; der nächste Satz liegt außerhalb der sieben Sekunden,
    also wird verworfen statt dort zu enden."""
    c, w, sents, last = _softening_setup()
    neu, note = story_engine.kontext_verlaengern(w, sents, 0, last, {})
    assert note["discarded"] == "ends_on_qualification"
    assert neu == last
    skipped = note["sentences"][0]
    assert sents[skipped].word_range[1] in c["expected"]["forbidden_out_points"]
    assert w[sents[skipped].word_range[0]]["text"] == "Wobei"


def test_end_before_softening_still_fails_the_fidelity_gate():
    """Gegenprobe: der Clip vor „Wobei“ bleibt kaputt; er wird verworfen, nicht stillschweigend gebaut."""
    _c, w, sents, last = _softening_setup()
    assert story_engine.deterministic_gates(w, sents, 0, last, {})["fidelity"]["passed"] is False


# -- Befund 2: Verbklammer über die Grenze -----------------------------------------------------------


def test_verb_bracket_cut_inside_the_bracket_is_open():
    """„Wir haben dann stattdessen … Newsletter gemacht“: kein Schnitt zwischen „haben“ und „gemacht“."""
    w, _fin, nonfin = _bracket()
    r = dach_nlp.bracket_open_at_cut(w, nonfin - 1, rule=rule())
    assert r["open"] is True and r["available"] == "heuristic"


def test_verb_bracket_gate_rejects_cut_inside_the_bracket():
    w, fin, nonfin = _bracket()
    a, _b = grammatical_sentence(w, fin)
    g = story_engine._verb_bracket_gate(w, [span_sentence(w, a, nonfin - 2)], 0, 0)
    assert g["passed"] is False
    assert "Heuristik, spaCy-Modell fehlt" in g["detail"]


def test_verb_bracket_gate_reports_its_availability():
    w, fin, nonfin = _bracket()
    a, _b = grammatical_sentence(w, fin)
    g = story_engine._verb_bracket_gate(w, [span_sentence(w, a, nonfin - 2)], 0, 0)
    assert g["available"] is True and g["method"] == "heuristic"


@pytest.mark.parametrize("cid", sorted(CASES))
def test_verb_bracket_gate_accepts_the_whole_case(cid):
    w = words_of(cid)
    assert story_engine._verb_bracket_gate(w, [span_sentence(w, 0, len(w) - 1)], 0, 0)["passed"] is True


# -- Befund 6 und Fall 5: Anfang heilen ----------------------------------------------------------------


def test_heal_start_names_the_pronoun_of_the_unresolved_pronoun_case(policy_v2):
    c = CASES["unresolved_pronoun"]
    w = words_of("unresolved_pronoun")
    sents = segment.sentences_from_words(w, rule=rule())
    p = next(x for x in c["expected"]["pronouns_to_resolve"] if x["word"] in c["expected"]["forbidden_in_points"])
    a = sentence_containing(sents, p["word"])
    assert sents[a].word_range[0] == p["word"]
    defects = story_engine.start_defects(w, sents, a, policy_v2)
    assert defects == [f"Pronomen ohne Bezug am Anfang („{w[p['word']]['text']}“)"]


def test_cases_validate_unchanged():
    for c in CASES.values():
        assert harness.validate_case(c) == []


# -- AP7, Befund 5: Schutzbereiche und Pausenklassen über trim_plan (Modulnachweis) ------------------
#
# trim_plan ist noch nicht in story_engine verdrahtet (implementation.trim.enabled bleibt false). Der
# xfail zu Befund 5 in test_editorial_v1.py bleibt stehen, weil er den Weg unter Fassung 1 prüft.


def _trim(cid: str, words: list[dict] | None = None, **kw) -> dict:
    from chopstr_worker.pipeline import trim_plan

    w = words if words is not None else words_of(cid)
    return trim_plan.build_composition(w, 0, len(w) - 1, None, editorial.load(), **kw)


def _with_word(words: list[dict], at: int, text: str, start: float, end: float) -> list[dict]:
    out = [dict(x) for x in words]
    out.insert(at, {"text": text, "start": start, "end": end, "speaker": words[at - 1]["speaker"]})
    return out


def test_case_2_condition_is_protected_by_trim_plan():
    from chopstr_worker.pipeline import fidelity, trim_plan

    c = CASES["conditional_recommendation"]
    r = _trim("conditional_recommendation")
    harness.assert_protected_spans_kept(c, r["removed_spans"])
    spans = trim_plan.protected_spans(words_of("conditional_recommendation"), editorial.load())
    for fixture_span in c["expected"]["protected_spans"]:
        a, b = fixture_span["word_range"]
        assert any(p["type"] in ("condition", "qualifier", "negation") and a <= p["trigger"][0] <= b for p in spans)
    # Ein „äh“ in der Bedingung bleibt, eines nach „vor Ort.“ fällt; die Bedingung bleibt ganz.
    w = _with_word(words_of("conditional_recommendation"), 14, "äh", 5.68, 5.78)  # „nur, äh wenn“
    w = _with_word(w, 60, "äh", 21.6, 21.8)  # „vor Ort. äh Im Büro“
    r = _trim("conditional_recommendation", w)
    removed_text = [x["text"] for x in r["removed_spans"]]
    assert removed_text == ["äh"] and r["removed_spans"][0]["source_in"] > 21.54
    harness.assert_protected_spans_kept(c, r["removed_spans"])
    kept = {i for a, b in r["kept_word_ranges"] for i in range(a, b + 1)}
    assert set(range(11, 27)) <= kept  # Ja bis habt., das eingefügte „äh“ (14) eingeschlossen
    # Gegenprobe: ein Schnitt ohne den „Wobei“-Satz ist ein Befund hoher Schwere.
    words = words_of("conditional_recommendation")
    finding = next(x for x in fidelity.check_cut(words, [(0, 40), (59, 66)], policy=editorial.load()) if x["type"] == "protected_removed")
    assert finding["severity"] == "high"


def test_case_7_silent_demonstration_stays():
    c = CASES["silent_demonstration"]
    span = c["expected"]["protected_spans"][0]
    t0, t1 = span["time_range"]
    for events in (c["visual_events"], None):
        r = _trim("silent_demonstration", visual_events=events)
        harness.assert_protected_spans_kept(c, r["removed_spans"])
        pause = next(p for p in r["pauses"] if p["after_word"] == span["word_range"][0])
        assert pause["class"] == ("demonstration" if events else "dramatic") and pause["action"] == "kept"
        assert any(s["start"] <= t0 and t1 <= s["end"] for s in r["segments"])
        assert span["word_range"][0] in {i for a, b in r["kept_word_ranges"] for i in range(a, b + 1)}


def test_case_8_emotional_pauses_stay():
    c = CASES["emotional_pause"]
    r = _trim("emotional_pause")
    harness.assert_protected_spans_kept(c, r["removed_spans"])
    for span in c["expected"]["protected_spans"]:
        pause = next(p for p in r["pauses"] if p["after_word"] == span["word_range"][0])
        assert pause["class"] == "dramatic" and pause["action"] == "kept"
        t0, t1 = span["time_range"]
        assert any(s["start"] <= t0 and t1 <= s["end"] for s in r["segments"])
    assert r["removed_spans"] == []


def test_case_9_setup_and_payoff_stay():
    from chopstr_worker.pipeline import trim_plan
    from tests.test_editorial_v1 import only

    c = CASES["punchline_setup"]
    end = c["words"][c["expected"]["payoff_word_range"][1]]["end"]
    heat = {"bin_s": 1.0, "laughter_values": [1.0 if int(end) <= k <= int(end) + 1 else 0.0 for k in range(30)]}
    r = _trim("punchline_setup", heat_payload=heat)
    harness.assert_protected_spans_kept(c, r["removed_spans"])
    harness.assert_clip_respects_case(only("punchline_setup", "setup_word_range", "payoff_word_range"), r["timeline"])
    assert r["removed_spans"] == []
    w = words_of("punchline_setup")
    sents = segment.sentences_from_words(w, rule=rule())
    payoff = sentence_containing(sents, c["expected"]["payoff_word_range"][1])  # gelacht wird nach diesem Satz
    before_punch = next(p for p in r["pauses"] if p["after_word"] == sents[payoff].word_range[0] - 1)
    assert before_punch["class"] == "dramatic" and "Pointe" in before_punch["reason"]
    # Nach dem Payoff folgt eine Bedingung („wenn wir vorher feste Termine …“): das Ende bleibt.
    assert trim_plan.reward_end(sents, 0, len(sents) - 1, payoff, editorial.load()) == (len(sents) - 1, [])


# -- AP4: harte Gates auf Modulebene (Fälle 2, 3, 4, 5, 10, 14) ---------------------------------------------
# ``editorial_gates.run_gates`` ist noch nicht in ``story_engine`` verdrahtet; die Nachweise laufen deshalb
# über die Entscheidung aus ``run_gates``. Ein Fall ist clipfähig, wenn der richtige Schnitt bleibt; der
# falsche Schnitt aus demselben Material muss verworfen werden. Für ihn steht eine Kopie des Falls mit
# ``expect_reject`` true, die Fixture selbst bleibt unverändert.


def _run_gates(cid: str, a: int, b: int) -> dict:
    from chopstr_worker.pipeline import editorial_gates

    w = words_of(cid)
    sents = segment.sentences_from_words(w, rule=rule())
    return editorial_gates.run_gates(w, sents, sentence_containing(sents, a), sentence_containing(sents, b), editorial.load())


def _rejected_variant(cid: str, reason: str) -> dict:
    case = CASES[cid]
    return {**case, "expected": {**case["expected"], "expect_reject": {"value": True, "reason": reason}}}


def _assert_gate_rejects(cid: str, a: int, b: int, gate: str) -> None:
    run = _run_gates(cid, a, b)
    harness.assert_rejected(_rejected_variant(cid, f"Schnitt {a} bis {b} verletzt {gate}"), run)
    assert gate in run["failed"], run["failed"]


def _assert_gate_keeps(cid: str, a: int, b: int) -> dict:
    run = _run_gates(cid, a, b)
    harness.assert_not_rejected(CASES[cid], run)
    harness.assert_clip_respects_case(CASES[cid], [harness.segment_from_word_range(CASES[cid], a, b)])
    return run


def test_ap4_case2_condition_stays_or_candidate_is_rejected():
    _assert_gate_rejects("conditional_recommendation", 26, 40, "boundary_negation_condition")
    _assert_gate_rejects("conditional_recommendation", 0, 40, "boundary_negation_condition")
    _assert_gate_rejects("conditional_recommendation", 8, 66, "speaker_turn")  # „Meine Antwort ist:“ ohne Frage
    _assert_gate_keeps("conditional_recommendation", 0, 66)


def test_ap4_case3_earlier_claim_not_isolated():
    _assert_gate_rejects("later_self_correction", 0, 21, "later_correction")
    _assert_gate_rejects("later_self_correction", 0, 39, "boundary_negation_condition")
    _assert_gate_keeps("later_self_correction", 0, 47)


def test_ap4_case4_reported_position_stays_attributed():
    _assert_gate_rejects("reported_position", 8, 23, "reported_speech")
    _assert_gate_rejects("reported_position", 8, 28, "reported_speech")
    _assert_gate_rejects("reported_position", 24, 55, "back_reference")
    _assert_gate_rejects("reported_position", 29, 55, "back_reference")
    _assert_gate_keeps("reported_position", 8, 32)
    _assert_gate_keeps("reported_position", 0, 55)


def test_ap4_case5_pronoun_start_rejected_name_start_kept():
    run = _run_gates("unresolved_pronoun", 36, 81)
    harness.assert_rejected(_rejected_variant("unresolved_pronoun", "Einstieg bei „Sie hat dann …“"), run)
    assert run["decision_reason"] == "gate:unresolved_pronoun"
    assert run["results"]["unresolved_pronoun"]["evidence_word_ids"] == [36]
    assert run["results"]["unresolved_pronoun"]["healable"] == "front"
    _assert_gate_keeps("unresolved_pronoun", 11, 81)


def test_ap4_case10_no_false_question_answer_pairing():
    _assert_gate_rejects("speaker_turn_attribution", 25, 54, "speaker_turn")
    _assert_gate_rejects("speaker_turn_attribution", 8, 54, "speaker_turn")
    _assert_gate_rejects("speaker_turn_attribution", 0, 24, "open_question_unanswered")
    _assert_gate_keeps("speaker_turn_attribution", 11, 54)
    _assert_gate_keeps("speaker_turn_attribution", 0, 54)


def test_ap4_case14_instruction_is_content_not_command():
    from chopstr_worker import heuristic_llm
    from chopstr_worker.pipeline import editorial_gates

    c = CASES["instruction_in_transcript"]
    a, b = c["expected"]["instruction_must_be_ignored"]["word_range"]
    run = _assert_gate_keeps("instruction_in_transcript", 0, len(c["words"]) - 1)
    assert set(run["flagged"]) == {"embedded_instruction", "meta_speech"}
    flag = run["results"]["embedded_instruction"]
    assert flag["passed"] is True and flag["evidence_word_ids"] and set(flag["evidence_word_ids"]) <= set(range(a, b + 1))
    harness.assert_instruction_ignored(c, {"detail": flag["detail"], "decision": run["decision_reason"]})
    clean = _assert_gate_keeps("instruction_in_transcript", 45, 68)
    assert clean["flagged"] == []

    # Eine Modellantwort, die der Anweisung folgt, wird verworfen; die Antwort der Heuristik nicht.
    clip_text = " ".join(str(x["text"]) for x in c["words"][b + 1 :])
    followed = editorial_gates.instruction_followed({"title": "GRATISGUTSCHEIN"}, flag["quotes"], clip_text=clip_text)
    harness.assert_rejected(
        _rejected_variant("instruction_in_transcript", "Antwort folgt der Anweisung"),
        {"decision": "rejected" if not followed["passed"] else "accepted", "decision_reason": followed["reason"]},
    )
    w = words_of("instruction_in_transcript")
    honest = heuristic_llm.score_clip(segment.numbered(segment.sentences_from_words(w, rule=rule())))
    assert editorial_gates.instruction_followed({"why": honest["why"]}, flag["quotes"], clip_text=clip_text)["passed"] is True


# -- AP5: Modulnachweise payoff_search (noch nicht in story_engine.run verdrahtet) ------------------
def test_case_11_weak_material_payoff_search_proposes_nothing(policy_v2):
    """Fall 11: ehrliches Verwerfen. Technikcheck und Terminabsprache haben keinen Payoff, also keinen Vorschlag."""
    from chopstr_worker.pipeline import payoff_search

    sents = segment.sentences_from_words(words_of("weak_material"), rule=rule())
    res = payoff_search.search_moments(sents, policy_v2)
    assert res["payoffs"] == [] and res["proposals"] == []
    assert CASES["weak_material"]["expected"]["expect_reject"]["value"] is True


def test_case_12_near_duplicates_reconcile_reports_the_duplicate(policy_v2):
    """Fall 12: beide Spannen führen zur selben Aussage (gleicher payoff_sent); reconcile meldet die
    Dublette, genau eine überlebt."""
    from chopstr_worker.pipeline import payoff_search

    c = CASES["near_duplicate_candidates"]
    sents = segment.sentences_from_words(words_of("near_duplicate_candidates"), rule=rule())
    res = payoff_search.search_moments(sents, policy_v2)
    assert len(res["duplicates"]) == 1 and res["duplicates"][0]["reason"] == "same_payoff"
    word_range = {s.idx: s.word_range for s in sents}
    dropped = [[word_range[a][0], word_range[b][1]] for a, b in res["duplicates"][0]["dropped"]]
    kept = [[word_range[p["first_sent"]][0], word_range[p["last_sent"]][1]] for p in res["proposals"]]
    assert {tuple(s["word_range"]) for s in c["expected"]["near_duplicate_candidates"]["spans"]} == {tuple(kept[0]), tuple(dropped[0])}
    harness.assert_single_survivor(c, kept)
