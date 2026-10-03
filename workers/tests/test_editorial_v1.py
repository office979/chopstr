"""Redaktioneller Testsatz editorial_v1 gegen die heute vorhandene Logik.

Die Fälle stehen unter ``tests/editorial_v1/cases`` (Master-Prompt Abschnitt 27). Geprüft wird hier,
was der heutige Code schon leisten soll: Satzende und Satzzerlegung, Satzgrenzen-Tor,
Kontextzugabe, Verbklammer, Füllwort- und Schutzklassen, Open-Loop, Story-Graph, Claim-Check der
Hooks, Auswahl und Heuristik-Provider. Was heute an einem bekannten Defekt scheitert, ist mit
``xfail(strict=True)`` und der Nummer aus ``docs/RESEARCH-CLIPPING-KERN.md`` Abschnitt 2 markiert.
Wird ein solcher Test grün, ist der Marker zu entfernen.

Der zweite Teil prüft den Harness (``tests/editorial_v1/harness.py``) mit synthetischen guten und
schlechten Schnittplänen. Die Harness-Funktionen sind für spätere Arbeitspakete gedacht, die das
``ClipCandidate``-Schema aus Abschnitt 21 liefern.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from chopstr_worker import editorial, heuristic_llm
from chopstr_worker.pipeline import compose, dach_nlp, fidelity, segment, story_engine, story_graph
from chopstr_worker.pipeline.segment import Sentence
from tests.editorial_v1 import harness

CASES = {c["id"]: c for c in harness.load_cases()}


def known_defect(nr: int) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        strict=True, reason=f"bekannter Defekt, RESEARCH-CLIPPING-KERN Abschnitt 2 Nr. {nr}"
    )


# -- Hilfen ----------------------------------------------------------------------------------------


def words_of(cid: str) -> list[dict]:
    """Frische Kopie der Wortliste (``annotate`` und ``classify_fillers`` schreiben in die Dicts)."""
    return copy.deepcopy(CASES[cid]["words"])


def text_of(words: list[dict], a: int, b: int) -> str:
    return " ".join(str(w["text"]) for w in words[a : b + 1])


def span_sentence(words: list[dict], a: int, b: int) -> Sentence:
    """Eine einzige Satzspanne über die Wörter ``a`` bis ``b``, unabhängig von der Satzzerlegung.

    So prüfen die Tore genau die Schnittkante, die der Fall vorgibt, auch wenn die Zerlegung dort
    heute anders trennt."""
    return Sentence(
        idx=0,
        text=text_of(words, a, b),
        start=float(words[a]["start"]),
        end=float(words[b]["end"]),
        speaker=words[a].get("speaker"),
        word_range=(a, b),
    )


def sentence_containing(sents: list[Sentence], i: int) -> int:
    return next(s.idx for s in sents if s.word_range[0] <= i <= s.word_range[1])


def grammatical_sentence(words: list[dict], i: int) -> tuple[int, int]:
    """Satz um Wort ``i`` nach Satzzeichen allein, ohne Pausen und Sprecherwechsel."""
    a = i
    while a > 0 and not harness.is_sentence_final(words[a - 1]["text"]):
        a -= 1
    b = i
    while b < len(words) - 1 and not harness.is_sentence_final(words[b]["text"]):
        b += 1
    return a, b


def candidate_from_words(
    words: list[dict], a: int, b: int, total: float, gates: dict | None = None
) -> story_engine.CandidateResult:
    """Kandidat über die Wörter ``a`` bis ``b``; die Tore kommen aus ``deterministic_gates``."""
    if gates is None:
        gates = story_engine.deterministic_gates(words, [span_sentence(words, a, b)], 0, 0, {})
    return story_engine.CandidateResult(
        segments=[{"start": float(words[a]["start"]), "end": float(words[b]["end"]), "role": "body"}],
        start_s=float(words[a]["start"]),
        end_s=float(words[b]["end"]),
        first_sent=a,
        last_sent=b,
        structure="hook_build_payoff",
        rubric={},
        gates=gates,
        story_graph_flags=[],
        risk_flags=[],
        total=total,
        gate_passed=all(bool(g["passed"]) for g in gates.values()),
        why="",
        model_id="test",
        prompt_version=None,
    )


PASSED_GATES = {
    k: {"passed": True, "detail": "test"}
    for k in ("standalone", "fidelity", "sentence_boundaries", "verb_bracket", "no_open_loop")
}


def params(rows, defects: dict[tuple[str, str], int]):
    """pytest-Parameter mit xfail-Marker für bekannte Defekte, Schlüssel (Fall, Worttext)."""
    out = []
    for cid, i, text in rows:
        nr = defects.get((cid, text))
        marks = [known_defect(nr)] if nr else []
        out.append(pytest.param(cid, i, id=f"{cid}:{i}:{text}", marks=marks))
    return out


# == Teil 1: Fixtures =============================================================================


def test_all_fourteen_required_cases_exist():
    assert sorted(CASES) == sorted(harness.REQUIRED_CASE_IDS)


@pytest.mark.parametrize("cid", sorted(CASES))
def test_case_passes_structural_validation(cid):
    assert harness.validate_case(CASES[cid]) == []


@pytest.mark.parametrize("cid", sorted(CASES))
def test_case_file_name_matches_id(cid):
    assert (harness.CASES_DIR / f"{cid}.json").is_file()


@pytest.mark.parametrize("cid", sorted(CASES))
def test_speech_rate_is_about_three_words_per_second(cid):
    w = CASES[cid]["words"]
    rate = len(w) / (float(w[-1]["end"]) - float(w[0]["start"]))
    assert 2.0 <= rate <= 3.6, f"{rate:.2f} Wörter je Sekunde"


@pytest.mark.parametrize("cid", sorted(CASES))
def test_german_texts_have_no_dashes(cid):
    c = CASES[cid]
    texts = [c["title"], c["description"], *(w["text"] for w in c["words"])]
    texts += re.findall(r'"(?:note|reason|description)": "([^"]*)"', json.dumps(c, ensure_ascii=False))
    assert not [t for t in texts if "–" in t or "—" in t or " - " in t]


def test_near_duplicate_spans_are_contained_in_each_other():
    nd = CASES["near_duplicate_candidates"]["expected"]["near_duplicate_candidates"]
    (a0, a1), (b0, b1) = (s["word_range"] for s in nd["spans"])
    assert a0 <= b0 and b1 <= a1


# == Teil 2: heutige Logik ========================================================================

# -- Satzende und Satzzerlegung (Nr. 1) ----------------------------------------------------------

SENTENCE_END_DEFECTS = {
    ("negation_sentence_end", "so."): 1,
    ("misrecognized_number_or_name", "i."): 1,
    ("silent_demonstration", "So."): 1,
}
NO_SENTENCE_END_DEFECTS = {
    ("negation_sentence_end", "uns"): 1,
    ("later_self_correction", "stattdessen"): 1,
    ("emotional_pause", "dann"): 1,
    ("emotional_pause", "ja,"): 1,
}


def _rows(key: str):
    for cid, c in sorted(CASES.items()):
        for i in c["expected"].get(key, []) or []:
            yield cid, i, c["words"][i]["text"]


@pytest.mark.parametrize(("cid", "i"), params(_rows("sentence_end_after"), SENTENCE_END_DEFECTS))
def test_sentence_end_is_detected(cid, i):
    assert dach_nlp.is_sentence_end(CASES[cid]["words"], i) is True


@pytest.mark.parametrize(("cid", "i"), params(_rows("no_sentence_end_after"), NO_SENTENCE_END_DEFECTS))
def test_no_sentence_end_inside_a_sentence(cid, i):
    assert dach_nlp.is_sentence_end(CASES[cid]["words"], i) is False


SEGMENTATION_DEFECT_CASES = {
    "negation_sentence_end": 1,
    "later_self_correction": 1,
    "misrecognized_number_or_name": 1,
    "silent_demonstration": 1,
    "emotional_pause": 1,
}


@pytest.mark.parametrize(
    "cid",
    [
        pytest.param(
            cid,
            marks=[known_defect(SEGMENTATION_DEFECT_CASES[cid])] if cid in SEGMENTATION_DEFECT_CASES else [],
        )
        for cid in sorted(CASES)
    ],
)
def test_segmentation_matches_expected_sentence_ends(cid):
    """Die Satzzerlegung endet genau dort, wo der Fall Satzenden erwartet, und nirgends dort, wo er
    keines erwartet (dramatische Pause, Zögern vor einer Verneinung, Pause in der Verbklammer)."""
    exp = CASES[cid]["expected"]
    ends = {s.word_range[1] for s in segment.sentences_from_words(words_of(cid))}
    assert set(exp.get("sentence_end_after", [])) <= ends
    assert not ends & set(exp.get("no_sentence_end_after", []) or [])


@pytest.mark.parametrize(
    "span_no",
    [pytest.param(0, marks=known_defect(1)), pytest.param(1, marks=known_defect(1))],
)
def test_dramatic_pause_stays_inside_one_sentence(span_no):
    c = CASES["emotional_pause"]
    pauses = [p for p in c["expected"]["protected_spans"] if p["type"] == "pause_dramatic"]
    a, b = pauses[span_no]["word_range"]
    sents = segment.sentences_from_words(words_of("emotional_pause"))
    assert sentence_containing(sents, a) == sentence_containing(sents, b)


@known_defect(1)
def test_hesitation_before_negation_does_not_split_the_clause():
    c = CASES["negation_sentence_end"]
    span = next(p for p in c["expected"]["protected_spans"] if p["type"] == "negation")
    a, b = span["word_range"]
    sents = segment.sentences_from_words(words_of("negation_sentence_end"))
    assert sentence_containing(sents, a) == sentence_containing(sents, b)


def test_ordinal_and_abbreviation_do_not_end_sentences():
    """Gegenprobe zu Nr. 1: „1. März“ und „z. B.“ funktionieren heute."""
    sents = segment.sentences_from_words(words_of("imprecise_timestamps"))
    assert sents[0].text.startswith("Seit dem 1. März")
    sents = segment.sentences_from_words(words_of("conditional_recommendation"))
    assert any("z. B. die Urlaubsvertretung" in s.text for s in sents)


# -- Satzgrenzen-Tor -------------------------------------------------------------------------------


def _mid_sentence_out_points():
    for cid, c in sorted(CASES.items()):
        for i in c["expected"]["forbidden_out_points"]:
            if not harness.is_sentence_final(c["words"][i]["text"]):
                yield pytest.param(cid, i, id=f"{cid}:{i}:{c['words'][i]['text']}")


def _mid_sentence_in_points():
    for cid, c in sorted(CASES.items()):
        for i in c["expected"]["forbidden_in_points"]:
            if i > 0 and not harness.is_sentence_final(c["words"][i - 1]["text"]):
                yield pytest.param(cid, i, id=f"{cid}:{i}:{c['words'][i]['text']}")


@pytest.mark.parametrize(("cid", "i"), list(_mid_sentence_out_points()))
def test_sentence_gate_rejects_forbidden_out_point_mid_sentence(cid, i):
    w = words_of(cid)
    g = story_engine._satzgrenzen_gate(w, [span_sentence(w, 0, i)], 0, 0)
    assert g["passed"] is False
    assert "endet mitten im Satz" in g["detail"]


@pytest.mark.parametrize(("cid", "i"), list(_mid_sentence_in_points()))
def test_sentence_gate_rejects_forbidden_in_point_mid_sentence(cid, i):
    w = words_of(cid)
    g = story_engine._satzgrenzen_gate(w, [span_sentence(w, i, len(w) - 1)], 0, 0)
    assert g["passed"] is False
    assert "mitten im Satz an" in g["detail"]


@pytest.mark.parametrize("cid", sorted(CASES))
def test_sentence_gate_accepts_the_whole_case(cid):
    w = words_of(cid)
    assert story_engine._satzgrenzen_gate(w, [span_sentence(w, 0, len(w) - 1)], 0, 0)["passed"] is True


# -- Kontextzugabe (Nr. 6) -------------------------------------------------------------------------


def _softening_setup():
    c = CASES["conditional_recommendation"]
    w = words_of("conditional_recommendation")
    sents = segment.sentences_from_words(w)
    soft_a, _soft_b = c["expected"]["softening_word_range"]
    last = sentence_containing(sents, soft_a - 1)
    return c, w, sents, last


def test_context_extension_heals_end_before_softening():
    """Ein Clip, der direkt vor „Wobei“ endet, reißt das Sinntreue-Tor und wird nach hinten verlängert."""
    _c, w, sents, last = _softening_setup()
    vorher = story_engine.deterministic_gates(w, sents, 0, last, {})
    assert vorher["fidelity"]["passed"] is False
    neu, zugabe = story_engine.kontext_verlaengern(w, sents, 0, last, {})
    assert neu > last and zugabe is not None
    assert "fidelity" in zugabe["behoben"]


@known_defect(6)
def test_context_extension_does_not_end_on_softening_sentence():
    """Policy ``ausstieg.vor_der_abschwaechung``: nicht auf dem „Wobei“-Satz enden."""
    c, w, sents, last = _softening_setup()
    neu, _zugabe = story_engine.kontext_verlaengern(w, sents, 0, last, {})
    letztes_wort = sents[neu].word_range[1]
    assert letztes_wort not in c["expected"]["forbidden_out_points"], f"endet auf „{w[letztes_wort]['text']}“"


# -- Verbklammer (Nr. 2) ---------------------------------------------------------------------------


def _bracket():
    c = CASES["later_self_correction"]
    w = words_of("later_self_correction")
    br = c["expected"]["verb_brackets"][0]
    return w, br["finite"], br["nonfinite"]


def test_cut_is_legal_respects_given_ranges():
    w, fin, nonfin = _bracket()
    sperre = [(float(w[fin]["end"]), float(w[nonfin]["start"]))]
    mitten = float(w[nonfin - 1]["end"])
    assert dach_nlp.cut_is_legal(mitten, sperre) is False
    assert dach_nlp.cut_is_legal(float(w[nonfin]["end"]), sperre) is True


@known_defect(2)
def test_verb_bracket_forbidden_ranges_cover_the_bracket():
    """„Wir haben dann stattdessen … Newsletter gemacht“: kein Schnitt zwischen „haben“ und „gemacht“."""
    w, fin, nonfin = _bracket()
    a, b = grammatical_sentence(w, fin)
    ranges = dach_nlp.forbidden_cut_ranges(text_of(w, a, b), w[a : b + 1])
    assert dach_nlp.cut_is_legal(float(w[nonfin - 2]["end"]), ranges) is False


@known_defect(2)
def test_verb_bracket_gate_rejects_cut_inside_the_bracket():
    w, fin, nonfin = _bracket()
    a, _b = grammatical_sentence(w, fin)
    sents = [span_sentence(w, a, nonfin - 2)]  # endet auf „stattdessen“
    assert story_engine._verb_bracket_gate(w, sents, 0, 0)["passed"] is False


def test_verb_bracket_gate_reports_its_availability():
    w, fin, nonfin = _bracket()
    a, _b = grammatical_sentence(w, fin)
    g = story_engine._verb_bracket_gate(w, [span_sentence(w, a, nonfin - 2)], 0, 0)
    assert g["available"] is bool(dach_nlp.verb_bracket_available)
    if not g["available"]:
        assert "nicht verfügbar" in g["detail"]


# -- Füllwort- und Schutzklassen (Nr. 5) -----------------------------------------------------------


def _word_spans():
    for cid, c in sorted(CASES.items()):
        for n, p in enumerate(c["expected"]["protected_spans"]):
            if p["type"] in harness.WORD_SPAN_TYPES:
                yield pytest.param(cid, n, id=f"{cid}:{p['type']}:{n}")


@pytest.mark.parametrize(("cid", "n"), list(_word_spans()))
def test_filler_removal_keeps_every_word_of_protected_spans(cid, n):
    w = dach_nlp.classify_fillers(words_of(cid))
    keep = dach_nlp.auto_remove_ranges(w)
    kept = {i for a, b in keep for i in range(a, b + 1)}
    a, b = CASES[cid]["expected"]["protected_spans"][n]["word_range"]
    assert [i for i in range(a, b + 1) if i not in kept] == []


TIME_SPAN_DEFECTS = {"silent_demonstration": 5}


def _time_spans():
    for cid, c in sorted(CASES.items()):
        for n, p in enumerate(c["expected"]["protected_spans"]):
            if p["type"] in harness.TIME_SPAN_TYPES:
                marks = [known_defect(TIME_SPAN_DEFECTS[cid])] if cid in TIME_SPAN_DEFECTS else []
                yield pytest.param(cid, n, id=f"{cid}:{p['type']}:{n}", marks=marks)


@pytest.mark.parametrize(("cid", "n"), list(_time_spans()))
def test_filler_cut_keeps_protected_pauses_and_silent_demonstrations(cid, n):
    """Füller-Schnitte (``auto_remove_ranges`` plus ``from_keep_ranges``) dürfen eine dramatische Pause
    oder eine stille Demonstration nicht herausschneiden. Es gibt keine Pausenklassen: steht ein „äh“
    vor der Stille, fällt die Stille mit heraus."""
    w = dach_nlp.classify_fillers(words_of(cid))
    comp = compose.from_keep_ranges(w, dach_nlp.auto_remove_ranges(w))
    t0, t1 = CASES[cid]["expected"]["protected_spans"][n]["time_range"]
    assert any(s.start <= t0 and t1 <= s.end for s in comp.segments)


@pytest.mark.parametrize(
    "cid",
    [
        cid
        for cid, c in sorted(CASES.items())
        if any(p["type"] == "negation" for p in c["expected"]["protected_spans"])
    ],
)
def test_negations_in_protected_spans_are_flagged(cid):
    w = dach_nlp.classify_fillers(words_of(cid))
    for p in CASES[cid]["expected"]["protected_spans"]:
        if p["type"] != "negation":
            continue
        a, b = p["word_range"]
        assert any(w[i]["negation"] for i in range(a, b + 1)), text_of(w, a, b)
        for i in range(a, b + 1):
            if dach_nlp.core_token(w[i]["text"]) in dach_nlp.NEGATIONS:
                assert w[i]["negation"] is True


@pytest.mark.parametrize("cid", sorted(CASES))
def test_modal_particles_of_the_speaker_are_kept(cid):
    w = dach_nlp.classify_fillers(words_of(cid))
    for i, x in enumerate(w):
        tok = dach_nlp.core_token(x["text"])
        nachbarn = {w[j]["speaker"] for j in (i - 1, i + 1) if 0 <= j < len(w)}
        if tok in dach_nlp.MODAL_PARTICLES and x["speaker"] in nachbarn:
            assert x["filler"] == "modal_keep", f"„{x['text']}“ (Wort {i})"


def test_backchannel_of_the_host_is_classified_as_removable():
    c = CASES["speaker_turn_attribution"]
    w = dach_nlp.classify_fillers(words_of("speaker_turn_attribution"))
    for i in c["expected"]["backchannel_words"]:
        assert w[i]["filler"] == "backchannel"
    # Die einsilbige Antwort des Gastes zwischen zwei Fragen ist kein Rückkanal und bleibt stehen.
    a, b = c["expected"]["speaker_turns"][0]["answer_word_range"]
    assert all(w[i]["filler"] is None for i in range(a, b + 1))
    assert any(w[i]["negation"] for i in range(a, b + 1))


def test_hesitation_before_silent_demonstration_is_a_hard_filler():
    c = CASES["silent_demonstration"]
    w = dach_nlp.classify_fillers(words_of("silent_demonstration"))
    aeh = c["expected"]["protected_spans"][0]["word_range"][0]
    assert w[aeh]["filler"] == "hard"


# -- Open-Loop -------------------------------------------------------------------------------------


def _connector_out_points():
    for cid, c in sorted(CASES.items()):
        for i in c["expected"]["forbidden_out_points"]:
            if dach_nlp.core_token(c["words"][i]["text"]) in dach_nlp.OPEN_LOOP_END:
                yield pytest.param(cid, i, id=f"{cid}:{i}:{c['words'][i]['text']}")


@pytest.mark.parametrize(("cid", "i"), list(_connector_out_points()))
def test_open_loop_detected_at_connector_out_points(cid, i):
    w = CASES[cid]["words"]
    a, _b = grammatical_sentence(w, i)
    assert dach_nlp.ends_with_open_loop(text_of(w, a, i)) is True


@pytest.mark.parametrize("cid", sorted(CASES))
def test_complete_sentences_are_not_open_loops(cid):
    w = CASES[cid]["words"]
    for i in CASES[cid]["expected"].get("sentence_end_after", []):
        a, _b = grammatical_sentence(w, i)
        assert dach_nlp.ends_with_open_loop(text_of(w, a, i)) is False, text_of(w, a, i)


# -- Story-Graph (Nr. 6) ---------------------------------------------------------------------------


def test_story_graph_finds_the_later_self_correction():
    c = CASES["later_self_correction"]
    lq = c["expected"]["later_qualification"]
    sents = segment.sentences_from_words(words_of("later_self_correction"))
    first = sentence_containing(sents, lq["claim_word_range"][0])
    last = sentence_containing(sents, lq["claim_word_range"][1])
    ziel = sentence_containing(sents, lq["qualification_word_range"][0])
    hits = story_graph.find_later_qualifications(sents, first, last)
    assert any(h["sentence_idx"] == ziel and h["marker"] == lq["marker"] for h in hits)


@known_defect(6)
def test_story_graph_does_not_read_ausserdem_as_ausser():
    c = CASES["near_duplicate_candidates"]
    span = c["expected"]["near_duplicate_candidates"]["spans"][0]["word_range"]
    ergaenzung = c["expected"]["not_a_qualification_word_range"]
    sents = segment.sentences_from_words(words_of("near_duplicate_candidates"))
    hits = story_graph.find_later_qualifications(
        sents, sentence_containing(sents, span[0]), sentence_containing(sents, span[1])
    )
    assert [h for h in hits if h["sentence_idx"] == sentence_containing(sents, ergaenzung[0])] == []


@known_defect(6)
def test_fidelity_gate_does_not_read_ausserdem_as_contrast():
    """Derselbe Wortgrenzenfehler wie im Story-Graph, hier im Sinntreue-Tor (``CONTRAST_STARTS``)."""
    c = CASES["near_duplicate_candidates"]
    a, b = c["expected"]["near_duplicate_candidates"]["spans"][0]["word_range"]
    w = words_of("near_duplicate_candidates")
    assert story_engine._fidelity_gate(w, [span_sentence(w, a, b)], 0, 0)["passed"] is True


# -- Claim-Check der Hooks (Nr. 7) -----------------------------------------------------------------


def _hook_rows(kind: str, defect: int | None = None):
    c = CASES["misrecognized_number_or_name"]
    marks = [known_defect(defect)] if defect else []
    return [pytest.param(h, id=h["hook"], marks=marks) for h in c["expected"]["hook_claims"][kind]]


def _clip_text(cid: str) -> str:
    w = CASES[cid]["words"]
    return text_of(w, 0, len(w) - 1)


# Behoben mit AP6a in ``hook_claim_check_v2`` (Zahlen als Wert und Einheit); ``hook_claim_check`` bleibt
# für Fassung 1 unverändert und vergleicht weiter per Teilstring.
@pytest.mark.parametrize("hook", _hook_rows("must_flag"))
def test_hook_claim_check_flags_numbers_not_in_the_clip(hook):
    issues = fidelity.hook_claim_check_v2(hook["hook"], _clip_text("misrecognized_number_or_name"))
    for num in hook["unsupported_numbers"]:
        assert any(f"'{num}'" in x for x in issues), f"„{num}“ nicht beanstandet: {issues}"


@pytest.mark.parametrize("hook", _hook_rows("must_pass"))
def test_hook_claim_check_accepts_numbers_that_are_in_the_clip(hook):
    assert fidelity.hook_claim_check(hook["hook"], _clip_text("misrecognized_number_or_name")) == []
    assert fidelity.hook_claim_check_v2(hook["hook"], _clip_text("misrecognized_number_or_name")) == []


def test_hook_does_not_use_the_uncertain_number(monkeypatch):
    """Fall misrecognized_number_or_name: „40.000“ hat niedrige Erkennungssicherheit und darf in keinem Hook
    stehen, auch nicht im Rückfall; ein Hook mit dieser Zahl wird verworfen (Fassung 2, AP6a)."""
    from chopstr_worker.pipeline import copy_de, copy_engine

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    c = CASES["misrecognized_number_or_name"]
    words = [{**w, "prob": w["asr_confidence"]} for w in words_of("misrecognized_number_or_name")]
    clip = _clip_text("misrecognized_number_or_name")
    assert fidelity.uncertain_number_tokens(words) == ["40.000 Euro gespart.", "40.000"]

    class FakeLLM:
        def model(self):
            return "fake"

        def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
            if tool_name == "write_post_caption":
                return {"text": "Rund 40.000 Euro gespart.", "cta": "Wie macht ihr das?"}
            hooks = ["Rund 40.000 Euro gespart", "40.000 Euro im ersten Jahr", "Bei uns 40 Euro gespart",
                     "In 4 Wochen den Einkauf umgebaut", "Jedes Unternehmen spart so"]  # fmt: skip
            return {"variants": [{"pattern": p, "spoken": h, "onscreen": h} for p, h in zip(copy_engine.HOOK_PATTERNS, hooks)]}

    try:
        res = copy_engine.write_copy(FakeLLM(), clip, copy_de.BrandProfile(), platforms=("linkedin",), words=words)
    finally:
        editorial.clear_cache()
    assert all(v["claim_issues"] for v in res.variants), res.variants
    assert res.pattern == "native" and res.onscreen_hook in clip
    assert "40.000" not in res.onscreen_hook and "40 000" not in res.onscreen_hook
    assert res.spoken_hook == "Wer hat bei euch den Einkauf neu aufgestellt?"
    # Post-Captions schreibt das Modell frei; die unsichere Zahl darin wird gemeldet, nicht still gelassen.
    unsicher = "Zahl '40.000' ist im Clip unsicher erkannt und darf nicht in den Hook (am Audio prüfen)"
    assert f"linkedin: {unsicher}" in res.claim_issues
    expected = {u["text"] for u in c["expected"]["uncertain_words"]}
    assert "40.000" in expected


# -- Auswahl (Nr. 4) -------------------------------------------------------------------------------


def test_select_best_drops_gate_violator_despite_top_score():
    c = CASES["negation_sentence_end"]
    w = words_of("negation_sentence_end")
    start = c["expected"]["must_include_word_ranges"][0][0] - 2  # „Ehrlich gesagt,“
    out_point = c["expected"]["forbidden_out_points"][0]  # vor „nicht viel.“
    clean_end = c["expected"]["sentence_end_after"][1]
    bad = candidate_from_words(w, start, out_point, total=13.5)
    good = candidate_from_words(w, start, clean_end, total=9.0)
    assert bad.gate_passed is False and good.gate_passed is True
    kept, dropped = story_engine.select_best([bad, good], limit=5)
    assert kept == [good]
    assert [d["reason"] for d in dropped] == ["gate"]


def test_select_best_keeps_only_one_of_the_near_duplicates():
    c = CASES["near_duplicate_candidates"]
    w = words_of("near_duplicate_candidates")
    spans = c["expected"]["near_duplicate_candidates"]["spans"]
    cands = [
        candidate_from_words(w, *s["word_range"], total=9.0 - n, gates=PASSED_GATES)
        for n, s in enumerate(spans)
    ]
    kept, dropped = story_engine.select_best(cands, limit=5)
    harness.assert_single_survivor(c, [(k.first_sent, k.last_sent) for k in kept])
    assert [d["reason"] for d in dropped] == ["overlap"]


def _weak_candidate():
    c = CASES["weak_material"]
    w = words_of("weak_material")
    sents = segment.sentences_from_words(w)
    r = heuristic_llm.score_clip(segment.numbered(sents))
    gates = story_engine.deterministic_gates(w, sents, 0, len(sents) - 1, r)
    dur = sents[-1].end - sents[0].start
    total = story_engine.policy_total({"rubric_points": r["rubrik"]}, dur)
    return c, r, candidate_from_words(w, 0, len(w) - 1, total=total, gates=gates)


def test_heuristic_rates_weak_material_below_the_discard_threshold():
    _c, r, cand = _weak_candidate()
    pol = editorial.load()
    assert r["organisatorisch"] is True
    assert r["punkte"] < pol.schwelle_verwerfen
    assert cand.total < pol.schwelle_verwerfen


@known_defect(4)
def test_weak_material_is_honestly_rejected():
    c, _r, cand = _weak_candidate()
    kept, dropped = story_engine.select_best([cand], limit=5)
    decision = {
        "decision": "accepted" if kept else "rejected",
        "decision_reason": "; ".join(str(d.get("reason")) for d in dropped),
    }
    harness.assert_rejected(c, decision)


# -- Heuristik-Provider (Nr. 6, Nr. 11) ------------------------------------------------------------


def test_heuristic_does_not_follow_instruction_in_transcript():
    c = CASES["instruction_in_transcript"]
    w = words_of("instruction_in_transcript")
    sents = segment.sentences_from_words(w)
    r = heuristic_llm.score_clip(segment.numbered(sents))
    hooks = heuristic_llm.write_hooks("CLIP: " + text_of(w, 0, len(w) - 1))
    pol = editorial.load()
    harness.assert_instruction_ignored(
        c, {"hooks": hooks, "why": r["why"]}, rubric=r["rubrik"], scale_max=pol.skala_max
    )


def test_heuristic_proposals_stay_inside_the_transcript_despite_instruction():
    w = words_of("instruction_in_transcript")
    sents = segment.sentences_from_words(w)
    out = heuristic_llm.propose_moments(segment.numbered(sents))
    for m in out["moments"]:
        assert 0 <= m["first_sent"] <= m["last_sent"] < len(sents)


def _punchline_rubric():
    c = CASES["punchline_setup"]
    w = words_of("punchline_setup")
    sents = segment.sentences_from_words(w)
    first = sentence_containing(sents, c["expected"]["setup_word_range"][0])
    last = sentence_containing(sents, c["expected"]["payoff_word_range"][1])
    span = sents[first : last + 1]
    r = heuristic_llm.score_clip(segment.numbered(span))
    return c, r, " ".join(s.text for s in span)


@known_defect(11)
def test_heuristic_flags_punchline_as_humor():
    c, r, text = _punchline_rubric()
    harness.assert_humor_flagged(
        c, {"rubric": r, "risk_flags": story_engine.risk_flags_for(r, text, heuristic=True)}
    )


def _pronoun_spans():
    c = CASES["unresolved_pronoun"]
    w = words_of("unresolved_pronoun")
    sents = segment.sentences_from_words(w)
    p = next(
        x for x in c["expected"]["pronouns_to_resolve"] if x["word"] in c["expected"]["forbidden_in_points"]
    )
    a = sentence_containing(sents, p["word"])
    assert sents[a].word_range[0] == p["word"], "der Satz muss mit dem Pronomen beginnen"
    return w, sents, a


def test_heuristic_penalizes_pronoun_start():
    _w, sents, a = _pronoun_spans()
    mit_pronomen = heuristic_llm.score_clip(segment.numbered(sents[a:]))
    mit_namen = heuristic_llm.score_clip(segment.numbered(sents[a - 1 :]))
    assert mit_pronomen["rubrik"]["standalone"] < mit_namen["rubrik"]["standalone"]


@known_defect(6)
def test_pronoun_start_violates_the_standalone_gate():
    w, sents, a = _pronoun_spans()
    r = heuristic_llm.score_clip(segment.numbered(sents[a:]))
    gates = story_engine.deterministic_gates(w, sents, a, len(sents) - 1, r)
    assert gates["standalone"]["passed"] is False


# -- Zeitstempel, stille Demonstration, Sprecherwechsel --------------------------------------------


def test_degenerate_timestamps_do_not_split_the_sentence():
    c = CASES["imprecise_timestamps"]
    a, b = c["expected"]["boundary_confidence"]["word_range"]
    sents = segment.sentences_from_words(words_of("imprecise_timestamps"))
    assert sentence_containing(sents, a) == sentence_containing(sents, b)


@pytest.mark.parametrize("cid", sorted(CASES))
def test_sentence_times_are_copied_from_word_times(cid):
    """Keine erfundene Präzision: Satzgrenzen sind exakt die Zeiten der Randwörter."""
    w = words_of(cid)
    for s in segment.sentences_from_words(w):
        a, b = s.word_range
        assert (s.start, s.end) == (float(w[a]["start"]), float(w[b]["end"]))


def test_filler_cut_on_degenerate_timestamps_yields_no_negative_segments():
    w = dach_nlp.classify_fillers(words_of("imprecise_timestamps"))
    comp = compose.from_keep_ranges(w, dach_nlp.auto_remove_ranges(w))
    assert comp.segments and all(s.end > s.start for s in comp.segments)


def test_sentence_span_around_silent_demonstration_covers_it():
    c = CASES["silent_demonstration"]
    ev = c["visual_events"][0]
    a, b = c["expected"]["must_include_word_ranges"][0]
    sents = segment.sentences_from_words(words_of("silent_demonstration"))
    first, last = sentence_containing(sents, a), sentence_containing(sents, b)
    assert sents[first].start <= ev["start"] and ev["end"] <= sents[last].end


def test_speaker_turns_are_separate_sentences_with_the_right_speaker():
    c = CASES["speaker_turn_attribution"]
    sents = segment.sentences_from_words(words_of("speaker_turn_attribution"))
    for t in c["expected"]["speaker_turns"]:
        q = sents[sentence_containing(sents, t["question_word_range"][0])]
        ans = sents[sentence_containing(sents, t["answer_word_range"][0])]
        assert q.speaker == t["question_speaker"] and ans.speaker == t["answer_speaker"]
        assert q.word_range[1] == t["question_word_range"][1]


# == Teil 3: Harness mit synthetischen Gut- und Schlecht-Beispielen ================================


def only(cid: str, *keep: str) -> dict:
    """Kopie eines Falls, in der nur die genannten Erwartungen gelten. Isoliert eine Regel."""
    c = copy.deepcopy(CASES[cid])
    for k, v in list(c["expected"].items()):
        if k in keep or k == "expect_reject":
            continue
        c["expected"][k] = [] if isinstance(v, list) else None
    return c


def seg(cid_or_case, a: int, b: int, **extra) -> dict:
    case = CASES[cid_or_case] if isinstance(cid_or_case, str) else cid_or_case
    return harness.segment_from_word_range(case, a, b, **extra)


def full_candidate(segments: list[dict], **extra) -> dict:
    cand = {k: None for k in harness.CANDIDATE_FIELDS}
    cand.update(
        {
            "candidate_id": "c1",
            "segments": segments,
            "removed_spans": [],
            "decision": "accepted",
            "decision_reason": "trägt eigenständig",
            "assessment_uncertainties": [],
        }
    )
    cand.update(extra)
    return cand


def test_harness_accepts_a_clip_that_respects_the_negation_case():
    c = CASES["negation_sentence_end"]
    start = c["expected"]["must_include_word_ranges"][0][0] - 2
    harness.assert_clip_respects_case(c, [seg(c, start, len(c["words"]) - 1)])


def test_harness_rejects_out_point_before_negation():
    c = only("negation_sentence_end", "forbidden_out_points")
    out = c["expected"]["forbidden_out_points"][0]
    with pytest.raises(AssertionError, match="verbotenem Out-Point"):
        harness.assert_clip_respects_case(c, [seg(c, 12, out)])


def test_harness_rejects_clip_missing_required_range():
    c = only("negation_sentence_end", "must_include_word_ranges")
    with pytest.raises(AssertionError, match="Pflichtbereich"):
        harness.assert_clip_respects_case(c, [seg(c, 23, 41)])


def test_harness_rejects_forbidden_in_point():
    c = only("reported_position", "forbidden_in_points")
    i = c["expected"]["forbidden_in_points"][0]
    with pytest.raises(AssertionError, match="verbotenem In-Point"):
        harness.assert_clip_respects_case(c, [seg(c, i, len(c["words"]) - 1)])


def test_harness_rejects_partially_cut_condition():
    c = only("conditional_recommendation", "protected_spans")
    a, b = c["expected"]["protected_spans"][0]["word_range"]
    with pytest.raises(AssertionError, match="nur teilweise"):
        harness.assert_clip_respects_case(c, [seg(c, 8, a)])
    harness.assert_clip_respects_case(c, [seg(c, 8, b)])


def test_harness_rejects_pronoun_without_antecedent():
    c = only("emotional_pause", "pronouns_to_resolve")
    p = c["expected"]["pronouns_to_resolve"][0]
    with pytest.raises(AssertionError, match="Pronomen"):
        harness.assert_clip_respects_case(c, [seg(c, p["word"], len(c["words"]) - 1)])
    harness.assert_clip_respects_case(c, [seg(c, 0, len(c["words"]) - 1)])


def test_harness_rejects_cut_out_dramatic_pause():
    c = only("emotional_pause", "protected_spans")
    a, b = c["expected"]["protected_spans"][0]["word_range"]
    n = len(c["words"]) - 1
    with pytest.raises(AssertionError, match="herausgeschnitten"):
        harness.assert_clip_respects_case(c, [seg(c, 0, a), seg(c, b, n)])
    harness.assert_clip_respects_case(c, [seg(c, 0, n)])


def test_harness_rejects_cut_out_demonstration_even_without_the_filler():
    c = only("silent_demonstration", "protected_spans")
    aeh, so = c["expected"]["protected_spans"][0]["word_range"]
    with pytest.raises(AssertionError, match="herausgeschnitten"):
        harness.assert_clip_respects_case(c, [seg(c, 0, aeh - 1), seg(c, so, len(c["words"]) - 1)])


def test_harness_rejects_false_question_answer_pairing():
    c = only("speaker_turn_attribution", "speaker_turns")
    q1, _a1, _q2, a2 = (
        c["expected"]["speaker_turns"][0]["question_word_range"],
        c["expected"]["speaker_turns"][0]["answer_word_range"],
        c["expected"]["speaker_turns"][1]["question_word_range"],
        c["expected"]["speaker_turns"][1]["answer_word_range"],
    )
    with pytest.raises(AssertionError, match="statt ihrer Antwort|ohne ihre Frage"):
        harness.assert_clip_respects_case(c, [seg(c, *q1), seg(c, *a2)])
    harness.assert_clip_respects_case(c, [seg(c, 0, len(c["words"]) - 1)])


def test_harness_rejects_clip_ending_before_the_punchline():
    c = only("punchline_setup", "payoff_word_range", "setup_word_range")
    setup = c["expected"]["setup_word_range"]
    payoff = c["expected"]["payoff_word_range"]
    with pytest.raises(AssertionError, match="payoff_word_range"):
        harness.assert_clip_respects_case(c, [seg(c, setup[0], payoff[0] - 1)])
    harness.assert_clip_respects_case(c, [seg(c, setup[0], payoff[1])])


def test_harness_segment_word_ids_fall_back_to_times():
    c = CASES["imprecise_timestamps"]
    s = seg(c, 0, 20)
    s["word_ids"] = None
    assert harness.segment_word_ids(c, s) == list(range(0, 21))


def test_harness_assert_rejected_good_and_bad():
    c = CASES["weak_material"]
    harness.assert_rejected(c, {"decision": "rejected", "decision_reason": "reines Organisationsgespräch"})
    with pytest.raises(AssertionError, match="erwartet wird Verwerfen"):
        harness.assert_rejected(c, {"decision": "accepted", "decision_reason": "Punkte 0,9"})
    with pytest.raises(AssertionError, match="ohne decision_reason"):
        harness.assert_rejected(c, {"decision": "rejected", "decision_reason": ""})
    with pytest.raises(AssertionError, match="falsch eingesetzt"):
        harness.assert_rejected(CASES["punchline_setup"], {"decision": "rejected", "decision_reason": "x"})


def test_harness_assert_not_rejected_good_and_bad():
    c = CASES["punchline_setup"]
    harness.assert_not_rejected(c, {"decision": "accepted"})
    with pytest.raises(AssertionError, match="verworfen"):
        harness.assert_not_rejected(c, {"decision": "rejected", "decision_reason": "zu kurz"})


def test_harness_protected_spans_kept_good_and_bad():
    c = CASES["silent_demonstration"]
    aeh = c["expected"]["protected_spans"][0]["word_range"][0]
    w = c["words"]
    filler_only = {
        "source_in": w[aeh]["start"],
        "source_out": w[aeh]["end"],
        "removal_reason": "hard_filler",
        "protected_context_check": "ok",
    }
    harness.assert_protected_spans_kept(c, [filler_only])
    t0, t1 = c["expected"]["protected_spans"][0]["time_range"]
    stille = {
        "source_in": t0,
        "source_out": t1,
        "removal_reason": "technical_pause",
        "protected_context_check": "ok",
    }
    with pytest.raises(AssertionError, match="trifft Schutzbereich visual_demonstration"):
        harness.assert_protected_spans_kept(c, [filler_only, stille])
    with pytest.raises(AssertionError, match="ohne Felder"):
        harness.assert_protected_spans_kept(c, [{"source_in": 0.0, "source_out": 0.1}])


def test_harness_protected_spans_kept_catches_removed_negation():
    c = CASES["negation_sentence_end"]
    a, b = c["expected"]["protected_spans"][0]["word_range"]
    w = c["words"]
    neg = {
        "source_in": w[b - 1]["start"],
        "source_out": w[b]["end"],
        "removal_reason": "tightening",
        "protected_context_check": None,
    }
    with pytest.raises(AssertionError, match="trifft Schutzbereich negation"):
        harness.assert_protected_spans_kept(c, [neg])


def test_harness_boundary_confidence_good_and_bad():
    c = CASES["imprecise_timestamps"]
    a, _b = c["expected"]["boundary_confidence"]["word_range"]
    cut_in_region = a + 2
    harness.assert_boundary_confidence_honest(c, [seg(c, 0, cut_in_region, boundary_confidence="low")])
    harness.assert_boundary_confidence_honest(c, [seg(c, 0, cut_in_region, boundary_confidence=0.3)])
    harness.assert_boundary_confidence_honest(c, [seg(c, 0, len(c["words"]) - 1, boundary_confidence=0.95)])
    for erfunden in (0.95, "high", None):
        with pytest.raises(AssertionError, match="unsicheren Bereich"):
            harness.assert_boundary_confidence_honest(
                c, [seg(c, 0, cut_in_region, boundary_confidence=erfunden)]
            )


def test_harness_single_survivor_good_and_bad():
    c = CASES["near_duplicate_candidates"]
    a, b = (s["word_range"] for s in c["expected"]["near_duplicate_candidates"]["spans"])
    harness.assert_single_survivor(c, [a])
    harness.assert_single_survivor(c, [b])
    with pytest.raises(AssertionError, match="Dubletten nicht reduziert"):
        harness.assert_single_survivor(c, [a, b])
    with pytest.raises(AssertionError, match="ganz verloren"):
        harness.assert_single_survivor(c, [])


def test_harness_uncertainty_marked_good_and_bad():
    c = CASES["misrecognized_number_or_name"]
    segs = [seg(c, 8, len(c["words"]) - 1)]
    ok = full_candidate(
        segs,
        assessment_uncertainties=[
            {"word_id": u["word"], "reason": u["reason"]} for u in c["expected"]["uncertain_words"]
        ],
    )
    harness.assert_uncertainty_marked(c, ok)
    by_text = full_candidate(
        segs, assessment_uncertainties=["Name Meier am Audio prüfen", "Zahl 40.000 unsicher"]
    )
    harness.assert_uncertainty_marked(c, by_text)
    with pytest.raises(AssertionError, match="nicht als Unsicherheit markiert"):
        harness.assert_uncertainty_marked(
            c, full_candidate(segs, assessment_uncertainties=["Name Meier am Audio prüfen"])
        )


def test_harness_instruction_ignored_good_and_bad():
    c = CASES["instruction_in_transcript"]
    harness.assert_instruction_ignored(
        c,
        {"title": "So viel Rabatt bekommen Stammkunden"},
        rubric={"hook": 1.4, "standalone": 2.0},
        scale_max=2,
    )
    with pytest.raises(AssertionError, match="folgt der Anweisung"):
        harness.assert_instruction_ignored(c, {"title": "GRATISGUTSCHEIN"})
    with pytest.raises(AssertionError, match="Höchstpunktzahl"):
        harness.assert_instruction_ignored(c, ["Rabatt"], rubric={"hook": 2, "standalone": 2.0}, scale_max=2)


def test_harness_humor_flag_good_and_bad():
    c = CASES["punchline_setup"]
    harness.assert_humor_flagged(c, {"risk_flags": ["humor"]})
    harness.assert_humor_flagged(c, {"rubric": {"is_humor": True}})
    with pytest.raises(AssertionError, match="ohne Humor-Markierung"):
        harness.assert_humor_flagged(c, {"risk_flags": ["claim"], "rubric": {"is_humor": False}})


def test_harness_clip_candidate_schema_good_and_bad():
    c = CASES["punchline_setup"]
    harness.assert_clip_candidate_schema(full_candidate([seg(c, 5, 63)]))
    reject = full_candidate([], decision="rejected", decision_reason="kein Payoff")
    harness.assert_clip_candidate_schema(reject)
    unvollstaendig = full_candidate([seg(c, 5, 63)])
    del unvollstaendig["policy_version"]
    with pytest.raises(AssertionError, match="ohne Felder"):
        harness.assert_clip_candidate_schema(unvollstaendig)
    with pytest.raises(AssertionError, match="ohne Segmente"):
        harness.assert_clip_candidate_schema(full_candidate([]))
    kaputtes_segment = seg(c, 5, 63)
    del kaputtes_segment["boundary_confidence"]
    with pytest.raises(AssertionError, match="Segment"):
        harness.assert_clip_candidate_schema(full_candidate([kaputtes_segment]))


def test_harness_validate_case_reports_problems():
    c = copy.deepcopy(CASES["negation_sentence_end"])
    c["words"] = c["words"][:10]
    c["expected"]["forbidden_out_points"] = [99]
    c["expected"]["protected_spans"].append({"type": "irony", "word_range": [0, 1]})
    del c["expected"]["boundary_confidence"]
    problems = harness.validate_case(c)
    assert any("40 bis 180" in p for p in problems)
    assert any("forbidden_out_points" in p for p in problems)
    assert any("unbekannter Typ" in p for p in problems)
    assert any("boundary_confidence fehlt" in p for p in problems)


def test_harness_load_case_unknown_id_raises():
    with pytest.raises(KeyError):
        harness.load_case("does_not_exist")
