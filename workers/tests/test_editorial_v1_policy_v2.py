"""Testsatz editorial_v1 unter Fassung 2 (AP2, AP3): die Defekte zu Befund 1, 2 und 6 sind dort behoben.

``test_editorial_v1.py`` läuft unter der Standardfassung 1 und muss dort byte-gleich bleiben; seine
xfail-Marker zu Befund 1, 2 und 6 bleiben deshalb stehen. Hier laufen dieselben Prüfungen mit
``CHOPSTR_POLICY_VERSION=2`` und der Satzende-Regel der aktiven Richtlinie, ohne die Fälle zu ändern.
spaCy ist fest aus, damit der Rückfall geprüft wird (wie im Golden-Snapshot).

Was unter Fassung 2 noch rot ist, steht als ``xfail(strict=True)`` mit dem Paket, das es behebt.
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
    assert note["verworfen"] == "ends_on_qualification"
    assert neu == last
    skipped = note["saetze"][0]
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
