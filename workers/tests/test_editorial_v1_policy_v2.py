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
    removed_text = [x["protected_context_check"]["detail"]["text"] for x in r["removed_spans"]]
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
    import copy

    from chopstr_worker.pipeline import editorial_gates

    w = words_of(cid)
    sents = segment.sentences_from_words(w, rule=rule())
    pol = editorial.load()
    raw = copy.deepcopy(pol.roh)
    raw["implementation"]["gates"]["discard_hard"] = True  # verworfen wird nur mit Regel und Schalter
    pol = editorial.Policy(version=pol.version, stand=pol.stand, roh=raw)
    return editorial_gates.run_gates(w, sents, sentence_containing(sents, a), sentence_containing(sents, b), pol)


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
    Dublette (``same_payoff``), genau eine überlebt. Die Verlängerung nach dem Payoff hängt den Schlusssatz
    („Außerdem …“, keine Einschränkung) an beide Spannen; jede Spanne des Falls steckt zu mindestens 90 Prozent
    in einer gemeldeten Spanne. Weitere Payoffs, die nach dem Verlängern dieselbe Spanne ergeben, stehen als
    ``same_span`` in ``duplicates``."""
    from chopstr_worker.pipeline import payoff_search

    c = CASES["near_duplicate_candidates"]
    sents = segment.sentences_from_words(words_of("near_duplicate_candidates"), rule=rule())
    res = payoff_search.search_moments(sents, policy_v2)
    same_payoff = [d for d in res["duplicates"] if d["reason"] == "same_payoff"]
    assert len(same_payoff) == 1 and set(same_payoff[0]) == {"payoff_sent", "kept", "dropped", "reason"}
    assert all(set(d) == {"payoff_sent", "kept", "dropped", "reason"} for d in res["duplicates"])
    word_range = {s.idx: s.word_range for s in sents}

    def words(span):
        return (word_range[span[0]][0], word_range[span[1]][1])

    reported = [words(same_payoff[0]["kept"]), *(words(d) for d in same_payoff[0]["dropped"])]
    kept = [list(words((p["first_sent"], p["last_sent"]))) for p in res["proposals"]]
    for ref in c["expected"]["near_duplicate_candidates"]["spans"]:
        a, b = ref["word_range"]
        assert any(max(0, min(b, y) - max(a, x) + 1) / (b - a + 1) >= 0.9 and x == a for x, y in reported), ref["id"]
    harness.assert_single_survivor(c, kept)


# -- Verdrahtung: Fälle über story_engine.run (Policy-Kopie mit implementation.gates.discard_hard und
# implementation.search.payoff_first) ---------------------------------------------------------------------


@pytest.fixture
def wired_v2(monkeypatch, tmp_path):
    """Kopie der Richtlinie mit eingeschalteten harten Gates und Suche (die Policy selbst bleibt unverändert)."""
    import shutil

    import yaml

    for path in editorial.policy_dir().glob("clip_policy_v*.yaml"):
        shutil.copy(path, tmp_path)
    target = tmp_path / "clip_policy_v2.yaml"
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    data["implementation"]["gates"]["discard_hard"] = True
    data["implementation"]["search"]["payoff_first"] = True
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    editorial.clear_cache()
    yield editorial.load()
    editorial.clear_cache()


def _heuristic():
    from chopstr_worker import config, providers_llm
    from chopstr_worker.providers_llm import LLM
    from chopstr_worker.residency import Tenant

    return LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def _run_case(cid: str, spans: list[tuple[int, int]] | None, monkeypatch) -> tuple[story_engine.DetectReport, list[dict]]:
    """``story_engine.run`` auf dem Fall. Mit ``spans`` (Wortbereiche) sind genau das die Vorschläge des Modells,
    die deterministische Suche schweigt; ohne ``spans`` laufen Heuristik und Suche wie im Betrieb."""
    from chopstr_worker.pipeline import payoff_search, story_score

    w = words_of(cid)
    if spans is not None:
        sents = story_engine.sentences_from_annotated(w) or segment.sentences_from_words(w, rule=rule())
        moments = [
            {"first_sent": sentence_containing(sents, a), "last_sent": sentence_containing(sents, b), "structure": "hook_build_payoff", "why": "Fall"}
            for a, b in spans
        ]  # fmt: skip
        monkeypatch.setattr(story_score, "propose", lambda *a, **kw: [dict(m) for m in moments])
        monkeypatch.setattr(
            payoff_search, "search_moments",
            lambda *a, **kw: {"proposals": [], "rejected": [], "duplicates": [], "payoffs": [], "openings": []},
        )  # fmt: skip
    report = story_engine.run(w, {"platform": "linkedin"}, {}, None, _heuristic())
    offered = [cc for cc in report.clip_candidates if cc["decision"] == "accept"]
    return report, offered


# Falsche Schnitte aus demselben Material (wie in den Modulnachweisen oben) und der richtige Schnitt (letzter).
RUN_CASES = {
    "conditional_recommendation": [(26, 40), (0, 40), (8, 66), (0, 66)],
    "later_self_correction": [(0, 21), (0, 39), (0, 47)],
    "reported_position": [(8, 23), (8, 28), (24, 55), (29, 55), (0, 55)],
    "unresolved_pronoun": [(36, 81), (11, 81)],
    "speaker_turn_attribution": [(25, 54), (8, 54), (0, 24), (0, 54)],
    "instruction_in_transcript": [(0, 68)],
}
RUN_PARAMS = [
    pytest.param(cid, span, n == len(spans) - 1, id=f"{cid}:{span[0]}-{span[1]}")
    for cid, spans in sorted(RUN_CASES.items())
    for n, span in enumerate(spans)
]


@pytest.mark.parametrize(("cid", "span", "right"), RUN_PARAMS)
def test_run_offers_only_cuts_that_respect_the_case(cid, span, right, wired_v2, monkeypatch):
    """Fälle 2, 3, 4, 5, 10, 14 über ``story_engine.run``, je ein Vorschlag: der richtige Schnitt wird angeboten,
    ein falscher ist verworfen (Gate, Länge) oder so geheilt, dass er den Fall respektiert."""
    report, offered = _run_case(cid, [span], monkeypatch)
    if right:
        assert offered, report.discarded
    for cc in offered:
        harness.assert_clip_respects_case(CASES[cid], cc["segments"])
    assert report.engine == "story_engine_v5"


def test_run_case_14_instruction_is_flagged_not_followed(wired_v2, monkeypatch):
    report, offered = _run_case("instruction_in_transcript", [(0, 68)], monkeypatch)
    (c,) = report.candidates
    assert c.rubric["quality_gate_results"]["embedded_instruction"]["flagged"] is True
    assert not [d for d in report.discarded if d["reason"] == "instruction_followed"]
    harness.assert_instruction_ignored(CASES["instruction_in_transcript"], [c.why, c.rubric.get("suggested_title_card") or ""])


def test_run_case_11_weak_material_offers_nothing(wired_v2, monkeypatch):
    report, offered = _run_case("weak_material", None, monkeypatch)
    assert offered == [] and report.candidates == []


def test_run_case_12_near_duplicates_leave_one_survivor(wired_v2, monkeypatch):
    report, offered = _run_case("near_duplicate_candidates", None, monkeypatch)
    ranges = [[min(ids), max(ids)] for ids in ([i for s in cc["segments"] for i in s["word_ids"]] for cc in offered) if ids]
    harness.assert_single_survivor(CASES["near_duplicate_candidates"], ranges)


# -- Befund 6 unter Fassung 2 mit den harten Gates: „außerdem“ ist kein „außer“ -----------------------------


def test_story_graph_does_not_read_ausserdem_as_ausser_under_v2(wired_v2):
    from chopstr_worker.pipeline import story_graph

    c = CASES["near_duplicate_candidates"]
    span = c["expected"]["near_duplicate_candidates"]["spans"][0]["word_range"]
    ergaenzung = c["expected"]["not_a_qualification_word_range"]
    sents = segment.sentences_from_words(words_of("near_duplicate_candidates"), rule=rule())
    assert story_engine.marker_rule() == "v2"
    hits = story_graph.find_later_qualifications(
        sents, sentence_containing(sents, span[0]), sentence_containing(sents, span[1]), rule=story_engine.marker_rule()
    )
    assert [h for h in hits if h["sentence_idx"] == sentence_containing(sents, ergaenzung[0])] == []


def test_fidelity_gate_does_not_read_ausserdem_as_contrast_under_v2(wired_v2):
    c = CASES["near_duplicate_candidates"]
    a, b = c["expected"]["near_duplicate_candidates"]["spans"][0]["word_range"]
    w = words_of("near_duplicate_candidates")
    assert story_engine._fidelity_gate(w, [span_sentence(w, a, b)], 0, 0)["passed"] is True
