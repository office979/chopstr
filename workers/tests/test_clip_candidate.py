"""ClipCandidate (AP8, Vertrag ``clip_candidate_v1``): Schema, Wortgrenzen, Ausgabe-Timeline, Null-Regeln.

Läuft ``story_engine.run`` mit dem Heuristik-Provider auf ``transcript_fixtures.DEMO_SCRIPT`` und den 14
Fällen aus ``editorial_v1``, unter Fassung 1 und 2. spaCy ist fest aus, wie im Golden-Snapshot.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import clip_candidate, compose, dach_nlp, story_engine
from chopstr_worker.pipeline.clip_candidate import ClipCandidate, SchemaError
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.editorial_v1 import harness
from tests.transcript_fixtures import demo_words

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "packages" / "schema" / "clip_candidate_v1.json"
BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler mit Zahlen", "exclude": "Werbung", "platform": "linkedin"}
SCENARIOS = {"demo": demo_words, **{c["id"]: (lambda c=c: copy.deepcopy(c["words"])) for c in harness.load_cases()}}


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    monkeypatch.setattr(dach_nlp, "verb_bracket_available", False)


@pytest.fixture(params=["1", "2"])
def version(request, monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", request.param)
    editorial.clear_cache()
    yield int(request.param)
    editorial.clear_cache()


def _llm() -> LLM:
    return LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def _run(name: str, brief: dict | None = None, **kwargs) -> tuple[list[dict], story_engine.DetectReport, list[ClipCandidate]]:
    words = SCENARIOS[name]()
    report = story_engine.run(words, dict(BRIEF if brief is None else brief), {}, None, _llm(), **kwargs)
    ccs = clip_candidate.from_report(report, words, editorial.load(), source={"id": name, "version": 3}, brief=brief if brief is not None else BRIEF)
    return words, report, ccs


# -- Schema ----------------------------------------------------------------------------------------


def test_schema_file_is_the_embedded_schema():
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == clip_candidate.SCHEMA
    assert clip_candidate.SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_requires_every_field_of_section_21():
    required = set(clip_candidate.SCHEMA["required"])
    assert set(harness.CANDIDATE_FIELDS) <= required
    assert {"externally_verified", "calibration", "contract"} <= required
    assert set(harness.SEGMENT_FIELDS) == set(clip_candidate.SCHEMA["$defs"]["segment"]["required"])
    assert set(harness.REMOVED_SPAN_FIELDS) == set(clip_candidate.SCHEMA["$defs"]["removed_span"]["required"])
    assert {f.name for f in dataclasses.fields(ClipCandidate)} == set(clip_candidate.SCHEMA["properties"])


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_candidate_is_valid(version, name):
    _words, report, ccs = _run(name)
    assert len(ccs) == len(report.candidates) + len(report.verworfen)
    for cc in ccs:
        data = cc.to_dict()
        assert clip_candidate.validate(data) == []
        harness.assert_clip_candidate_schema(data)
        assert data["policy_version"] == f"clip_policy_v{version}"
        assert data["externally_verified"] is None
        assert data["calibration"] == "uncalibrated"


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_round_trip(version, name):
    for cc in _run(name)[2]:
        assert ClipCandidate.from_dict(cc.to_dict()) == cc
        assert ClipCandidate.from_dict(json.loads(json.dumps(cc.to_dict(), ensure_ascii=False))) == cc


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_source_times_lie_on_word_boundaries(version, name):
    words, _report, ccs = _run(name)
    starts = {float(w["start"]) for w in words}
    ends = {float(w["end"]) for w in words}
    for cc in ccs:
        spans = [cc.opening_source_span, cc.payoff_source_span, *cc.required_context_spans]
        spans += [{"source_in": d["source_in"], "source_out": d["source_out"]} for d in cc.meaning_dependencies]
        for seg in cc.segments:
            assert seg.source_in is None or seg.source_in in starts
            assert seg.source_out is None or seg.source_out in ends
            assert seg.word_ids == sorted(seg.word_ids)
            assert seg.verbatim_text == " ".join(str(words[i]["text"]) for i in seg.word_ids)
            if seg.word_ids:
                assert seg.source_in == float(words[seg.word_ids[0]]["start"])
                assert seg.source_out == float(words[seg.word_ids[-1]]["end"])
        for span in filter(None, spans):
            assert span["source_in"] is None or span["source_in"] in starts
            assert span["source_out"] is None or span["source_out"] in ends


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_output_timeline_is_deterministic_and_gapless(version, name):
    first = [cc.to_dict() for cc in _run(name)[2]]
    second = [cc.to_dict() for cc in _run(name)[2]]
    assert first == second
    for data in first:
        end = 0.0
        for seg in data["segments"]:
            assert seg["output_in"] == pytest.approx(end, abs=1e-3)
            assert seg["output_out"] - seg["output_in"] == pytest.approx(seg["source_out"] - seg["source_in"], abs=2e-3)
            end = seg["output_out"]


def test_heuristic_is_uncalibrated_and_says_so(version):
    _words, _report, ccs = _run("demo")
    assert ccs
    for cc in ccs:
        assert cc.calibration == "uncalibrated"
        assert cc.model_version == providers_llm.HEURISTIC_MODEL_ID
        kinds = {u["kind"] for u in cc.assessment_uncertainties}
        assert {"heuristic_only", "nlp_unavailable", "boundary_confidence_missing"} <= kinds
        assert all(s.boundary_confidence is None for s in cc.segments)


def test_versions_name_every_pinned_prompt(version):
    pol = editorial.load()
    for cc in _run("demo")[2]:
        assert cc.prompt_version == {n: f"{n}_v{v}" for n, v in pol.prompt_pins.items()}
    if version == 2:
        assert cc.prompt_version["hooks"] == "hooks_v2"


# -- Null-Regeln ----------------------------------------------------------------------------------


def test_audience_only_from_the_brief(version):
    with_brief = _run("demo")[2][0]
    assert with_brief.audience_context == BRIEF["audience"]
    assert with_brief.audience_context_provenance == "explicit"
    assert with_brief.objective is None  # wanted ist kein Kommunikationsziel
    assert _run("demo", brief={**BRIEF, "objective": "Vertrauen in Preise"})[2][0].objective == "Vertrauen in Preise"
    without = _run("demo", brief={})[2][0]
    assert without.audience_context is None and without.audience_context_provenance is None
    assert without.objective is None
    assert without.central_idea is None and without.viewer_promise is None


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_low_confidence_words_in_the_clip_are_always_marked(version, name):
    """Jedes Wort mit ``prob`` (Fixtures: ``asr_confidence``) unter der Schwelle, das eine Zahl oder ein Name
    ist und im Clip liegt, steht mit ``word_id`` in ``assessment_uncertainties``, ob angenommen oder verworfen."""
    words, _report, ccs = _run(name)
    for cc in ccs:
        ids = {i for s in cc.segments for i in s.word_ids}
        expected = {u["word_id"] for u in clip_candidate.low_confidence_uncertainties(words, sorted(ids))}
        marked = {u["word_id"] for u in cc.assessment_uncertainties if u["word_id"] is not None}
        assert marked == expected


def test_case_6_number_and_name_are_marked(monkeypatch):
    """Fall 6 unter Fassung 1 (Golden-Snapshot, stabil): „Meier,“ (0,38) und „40.000“ (0,46) liegen im
    angebotenen Clip und werden markiert; der Harness bestätigt es."""
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    case = harness.load_case("misrecognized_number_or_name")
    _words, _report, ccs = _run("misrecognized_number_or_name")
    accepted = [cc.to_dict() for cc in ccs if cc.decision == "accept"]
    assert accepted
    for data in accepted:
        harness.assert_uncertainty_marked(case, data)
    kinds = {(u["kind"], u["text"]) for u in accepted[0]["assessment_uncertainties"] if u["word_id"] is not None}
    assert ("low_confidence_name", "Meier,") in kinds
    assert ("low_confidence_number", "40.000") in kinds
    all_ids = list(range(len(case["words"])))
    found = {u["word_id"] for u in clip_candidate.low_confidence_uncertainties(case["words"], all_ids)}
    assert found == {u["word"] for u in case["expected"]["uncertain_words"]}


def test_low_confidence_ignores_words_without_prob_and_small_words():
    words = [
        {"text": "rund", "prob": 0.2},
        {"text": "40", "prob": 0.3},
        {"text": "Huber", "prob": 0.1},
        {"text": "Meier", "prob": 0.9},
        {"text": "Wien"},
        {"text": "Zahl", "prob": 0.5},
    ]
    out = clip_candidate.low_confidence_uncertainties(words, list(range(len(words))))
    assert [(u["kind"], u["word_id"]) for u in out] == [("low_confidence_number", 1), ("low_confidence_name", 2)]
    assert out[0]["prob"] == 0.3 and "am Audio prüfen" in out[0]["detail"]


# -- Synthetische Fälle ---------------------------------------------------------------------------


def _demo_candidate() -> tuple[list[dict], list, story_engine.CandidateResult]:
    words = demo_words()
    report = story_engine.run(words, dict(BRIEF), {}, None, _llm())
    return words, clip_candidate.sentences_for(words), report.candidates[0]


def _from(words, sents, result, **kwargs) -> ClipCandidate:
    pol = editorial.load()
    return clip_candidate.from_result(result, words, sents, {"id": "demo"}, clip_candidate.versions_for(pol), pol, BRIEF, **kwargs)


def test_teaser_segment_comes_first_with_its_own_output_time(version):
    words, sents, result = _demo_candidate()
    teaser = sents[result.first_sent + 1]
    comp = compose.with_teaser(compose.Composition.from_json(result.segments), round(teaser.start, 3), round(teaser.end, 3))
    rubric = {**result.rubric, "teaser_satz": teaser.idx}
    cc = _from(words, sents, dataclasses.replace(result, segments=comp.to_json(), rubric=rubric))
    t, body = cc.segments
    assert t.editorial_role == "teaser" and body.editorial_role == "body"
    assert t.output_in == 0.0 and body.output_in == t.output_out
    assert t.source_in == float(words[teaser.word_range[0]]["start"])
    assert cc.opening_source_span["note"] == "teaser"
    assert cc.opening_source_span["sentence_range"] == [teaser.idx, teaser.idx]
    assert ClipCandidate.from_dict(cc.to_dict()) == cc


def test_speaker_is_null_when_the_segment_has_two_speakers(version):
    words, sents, result = _demo_candidate()
    words = copy.deepcopy(words)
    words[_from(words, sents, result).segments[0].word_ids[1]]["speaker"] = "SPEAKER_01"
    assert _from(words, sents, result).segments[0].speaker_id is None
    for w in words:
        w.pop("speaker", None)
    assert _from(words, sents, result).segments[0].speaker_id is None


def test_pause_boundary_and_unconfirmed_story_graph_are_uncertain(version):
    words, sents, result = _demo_candidate()
    words = copy.deepcopy(words)
    plain = _from(words, sents, result)
    assert not {"boundary_from_pause", "boundary_from_length_cap"} & {u["kind"] for u in plain.assessment_uncertainties}
    # Letztes Wort ohne Satzzeichen: das Ende ist nur noch durch die Pause von 0,8 s eine Grenze.
    last_id = plain.segments[-1].word_ids[-1]
    words[last_id]["text"] = str(words[last_id]["text"]).rstrip(".!?")
    later = min(result.last_sent + 1, len(sents) - 1)
    flag = {"sentence_idx": later, "seconds_after": 1.0, "marker": "das heißt aber nicht", "text": sents[later].text,
            "overlap": 0.3, "confirmed": None, "reason": "", "repair": "extend", "suggestion": "Clip verlängern"}  # fmt: skip
    cc = _from(words, sents, dataclasses.replace(result, story_graph_flags=[flag]))
    kinds = [u["kind"] for u in cc.assessment_uncertainties]
    assert "boundary_from_pause" in kinds and "story_graph_unconfirmed" in kinds
    pause = next(u for u in cc.assessment_uncertainties if u["kind"] == "boundary_from_pause")
    assert "Ende s1" in pause["detail"] and pause["word_id"] is None
    dep = cc.meaning_dependencies[0]
    assert dep["kind"] == "later_qualification" and dep["sentence_idx"] == later
    assert dep["source_in"] == float(words[sents[later].word_range[0]]["start"])
    assert dep["detail"] == "Clip verlängern"
    confirmed = _from(words, sents, dataclasses.replace(result, story_graph_flags=[{**flag, "confirmed": True}]))
    assert "story_graph_unconfirmed" not in [u["kind"] for u in confirmed.assessment_uncertainties]


def test_required_context_from_repair(version):
    words, sents, result = _demo_candidate()
    rubric = {**result.rubric, "repair": {"rounds": 1, "expanded_front": 1, "expanded_back": 2, "failed": False}}
    cc = _from(words, sents, dataclasses.replace(result, rubric=rubric))
    front, back = cc.required_context_spans
    assert front["sentence_range"] == [result.first_sent, result.first_sent]
    assert back["sentence_range"] == [result.last_sent - 1, result.last_sent]


def test_gate_failure_is_a_rejection_with_reason(version):
    words, sents, result = _demo_candidate()
    gates = {**result.gates, "no_open_loop": {"passed": False, "detail": "endet auf „aber“"}}
    cc = _from(words, sents, dataclasses.replace(result, gates=gates, gate_passed=False))
    assert cc.decision == "reject"
    assert "no_open_loop" in cc.decision_reason and "aber" in cc.decision_reason
    assert cc.alternatives_considered is None
    harness.assert_rejected({"id": "x", "expected": {"expect_reject": {"value": True, "reason": "Tor"}}}, cc.to_dict())


def test_selection_drops_become_rejections_with_alternatives(version):
    _words, report, ccs = _run("demo", max_candidates=1)
    assert len(report.candidates) == 1 and report.verworfen
    accepted = [cc for cc in ccs if cc.decision == "accept"]
    rejected = [cc for cc in ccs if cc.decision == "reject"]
    assert len(accepted) == 1 and len(rejected) == len(report.verworfen)
    reasons = {d["reason"] for d in report.discarded}
    assert reasons & {"limit", "overlap"}
    for cc in rejected:
        assert cc.decision_reason.startswith("Verworfen")
        assert isinstance(cc.alternatives_considered, list)


def test_sentence_list_must_match_the_run(version):
    words, sents, result = _demo_candidate()
    with pytest.raises(ValueError, match="Satzliste"):
        _from(words, sents[1:], result)


def test_from_dict_rejects_contract_violations(version):
    data = _run("demo")[2][0].to_dict()
    for broken, message in (
        ({k: v for k, v in data.items() if k != "policy_version"}, "Pflichtfeld"),
        ({**data, "decision": "maybe"}, "nicht erlaubt"),
        ({**data, "externally_verified": True}, "Typ"),
        ({**data, "virality": 0.9}, "nicht vorgesehen"),
        ({**data, "audience_context_provenance": "inferred"}, "nicht erlaubt"),
        ({**data, "segments": [{**data["segments"][0], "output_out": -1.0}]}, "vor"),
        ({**data, "segments": []}, "ohne Segmente"),
    ):
        with pytest.raises(SchemaError, match=message):
            ClipCandidate.from_dict(broken)


def test_compact_for_rubric_is_the_additive_subset(version):
    cc = _run("demo")[2][0]
    compact = clip_candidate.compact_for_rubric(cc)
    assert tuple(compact) == clip_candidate.RUBRIC_KEYS
    assert compact["versions"] == {
        "contract": "clip_candidate_v1",
        "model_version": cc.model_version,
        "prompt_version": cc.prompt_version,
        "policy_version": cc.policy_version,
    }
    assert compact["calibration"] == "uncalibrated"
    assert compact["removed_spans"] == []
    assert compact["quality_gate_results"] == cc.quality_gate_results
    json.dumps(compact, ensure_ascii=False)


def test_adapter_does_not_touch_the_candidate(version):
    words, sents, result = _demo_candidate()
    before = copy.deepcopy(result.to_row())
    _from(words, sents, result)
    assert result.to_row() == before


def test_low_confidence_detail_keeps_the_word_as_transcribed():
    out = clip_candidate.low_confidence_uncertainties([{"text": "40.000", "prob": 0.46}], [0])
    assert out[0]["detail"] == "Zahl „40.000“ unsicher erkannt (Sicherheit 0,46 unter 0,50), am Audio prüfen"


def test_length_cap_boundary_is_its_own_kind(version, monkeypatch):
    words, sents, result = _demo_candidate()
    real = dach_nlp.cut_boundary_kind
    last_id = _from(words, sents, result).segments[-1].word_ids[-1]
    monkeypatch.setattr(dach_nlp, "cut_boundary_kind", lambda w, i, **kw: "length_cap" if i == last_id else real(w, i, **kw))
    kinds = [u["kind"] for u in _from(words, sents, result).assessment_uncertainties]
    assert "boundary_from_length_cap" in kinds and "boundary_from_pause" not in kinds


def test_nlp_note_separates_off_from_missing():
    note = clip_candidate._nlp_note
    assert note({"passed": True, "detail": "Verbklammer laut Richtlinie nicht geprüft", "available": False, "method": "off"}, "off").startswith("Verbklammer laut Richtlinie abgeschaltet")
    assert note({"available": True, "method": "heuristic", "detail": "x"}, "heuristic").startswith("spaCy-Modell fehlt, Verbklammer nur heuristisch")
    assert note({"available": False, "detail": "spaCy fehlt"}, "").startswith("spaCy-Modell fehlt, Verbklammer nicht geprüft")
    assert note({"available": True, "method": "spacy", "detail": "ok"}, "spacy") is None


def test_name_detection_skips_function_words_and_sentence_starts():
    def w(text, prob=0.2, speaker="A"):
        return {"text": text, "prob": prob, "speaker": speaker}

    words = [w("Wir"), w("haben"), w("Sie"), w("gefragt."), w("Huber"), w("kam"), w("mit"), w("Frau"), w("Meier"),
             w("und"), w("Pichler."), w("Hälfte"), w("halb"), w("Ok.", speaker="B"), w("Gruber", speaker="A")]  # fmt: skip
    found = {(u["kind"], u["text"]) for u in clip_candidate.low_confidence_uncertainties(words, list(range(len(words))))}
    assert found == {("low_confidence_name", "Meier"), ("low_confidence_name", "Pichler."),
                     ("low_confidence_number", "Hälfte"), ("low_confidence_number", "halb")}  # fmt: skip
    known = clip_candidate.low_confidence_uncertainties(words, list(range(len(words))), names=["Huber", "gruber"])
    assert {u["text"] for u in known if u["kind"] == "low_confidence_name"} == {"Huber", "Meier", "Pichler.", "Gruber"}


def test_prob_none_falls_back_to_asr_confidence():
    out = clip_candidate.low_confidence_uncertainties([{"text": "x"}, {"text": "40.000", "prob": None, "asr_confidence": 0.3}], [1])
    assert out[0]["prob"] == 0.3


def test_candidate_id_depends_on_policy_and_engine(version):
    words, sents, result = _demo_candidate()
    pol = editorial.load()
    base = clip_candidate.versions_for(pol)
    ids = {
        clip_candidate.from_result(result, words, sents, {"id": "demo"}, v, pol, BRIEF).candidate_id
        for v in (base, {**base, "policy_version": "clip_policy_v9"}, {**base, "engine": "story_engine_v99"})
    }
    assert len(ids) == 3


def test_semantic_rules(version):
    data = _run("demo")[2][0].to_dict()
    seg = data["segments"][0]
    cases = (
        ({**data, "audience_context_provenance": None}, "nur gemeinsam"),
        ({**data, "audience_context": None}, "nur gemeinsam"),
        ({**data, "segments": [{**seg, "source_in": None}]}, "output_in ohne source_in"),
        ({**data, "segments": [{**seg, "word_ids": [], "source_in": None, "source_out": None, "output_in": None, "output_out": None}]}, "speaker_id ohne Wörter"),
        ({**data, "removed_spans": [{"source_in": 2.0, "source_out": 2.0, "removal_reason": "Pause", "protected_context_check": None}]}, "nicht nach source_in"),
        ({**data, "segments": [{**seg, "output_out": float("nan")}]}, "keine endliche Zahl"),
        ({**data, "assessment_uncertainties": [{"kind": "heuristic_only", "detail": "x", "word_id": 3, "text": None, "prob": None}]}, "nur bei Wortbefunden"),
        ({**data, "assessment_uncertainties": [{"kind": "low_confidence_number", "detail": "x", "word_id": None, "text": "40", "prob": 0.2}]}, "ohne word_id"),
        ({**data, "opening_source_span": {**data["opening_source_span"], "word_range": [1]}}, "word_range: 1 Einträge"),
    )  # fmt: skip
    for broken, message in cases:
        with pytest.raises(SchemaError, match=message):
            ClipCandidate.from_dict(broken)


def test_semantic_rules_only_apply_to_the_contract_schema(version):
    data = _run("demo")[2][0].to_dict()
    assert clip_candidate.validate({**data, "audience_context": None}, {"type": "object"}) == []
    assert clip_candidate.validate({**data, "audience_context": None}) != []


def test_segments_off_sentence_and_word_boundaries_are_accepted(version):
    """AP7 schneidet Füllwörter am Rand und kürzt Pausen auf die halbe Zielpause: Segmente beginnen dann nach
    dem Satzanfang und enden zwischen zwei Wörtern. source_in und source_out sind die tatsächlichen
    Schnittgrenzen, word_ids die ganz enthaltenen Wörter; die Ausgabe-Timeline bleibt lückenlos."""
    words, sents, result = _demo_candidate()
    a, b = sents[result.first_sent].word_range[0], sents[result.last_sent].word_range[1]
    mid = sents[result.first_sent].word_range[1]  # Pause zwischen den ersten beiden Sätzen
    assert result.last_sent > result.first_sent
    cut_a = round(float(words[a + 1]["start"]) - 0.04, 3)  # erstes Wort weggeschnitten, Schnitt in der Pause davor
    cut_mid = round(float(words[mid]["end"]) + 0.01, 3)  # Pause hinter dem Wort halbiert
    restart = round(float(words[mid + 1]["start"]) - 0.01, 3)
    segments = [
        {"start": cut_a, "end": cut_mid, "role": "body"},
        {"start": restart, "end": round(float(words[b]["end"]), 3), "role": "body"},
    ]
    removed = [{"source_in": cut_mid, "source_out": restart, "removal_reason": "technical_pause", "protected_context_check": None,
                "kind": "local", "word_ids": [], "text": ""}]  # fmt: skip
    cc = _from(words, sents, dataclasses.replace(result, segments=segments, rubric={**result.rubric, "removed_spans": removed}))
    data = cc.to_dict()
    s1, s2 = data["segments"]
    assert s1["source_in"] == cut_a and s1["source_out"] == cut_mid and s2["source_in"] == restart
    assert s1["word_ids"][0] == a + 1 and s1["word_ids"][-1] == mid and s2["word_ids"][0] == mid + 1
    assert s1["output_in"] == 0.0 and s2["output_in"] == s1["output_out"]
    for seg in data["segments"]:
        assert seg["output_out"] - seg["output_in"] == pytest.approx(seg["source_out"] - seg["source_in"], abs=2e-3)
    assert data["removed_spans"] == [{"source_in": cut_mid, "source_out": restart, "removal_reason": "technical_pause", "protected_context_check": None}]
