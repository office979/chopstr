"""Lane P3, Aufgabe 1: Claim-Index über das ganze Video (``story_graph``), Klassen mit Sprecherbezug und
Schnittreaktion, Gate ``later_correction`` ohne 60-s-Grenze, ``rubric.context_hits`` im Lauf.

Fassung 2 aus einer Kopie der Richtlinie mit eingeschaltetem Claim-Index (Regel ``context.claim_index.enabled``
steht in der Datei auf false), spaCy fest aus.
"""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

from chopstr_worker import editorial
from chopstr_worker.pipeline import dach_nlp, editorial_gates, segment, story_engine, story_graph
from tests.test_story_engine import BRIEF, brain, llm  # noqa: F401  (Fixtures)
from tests.transcript_fixtures import demo_words, make_words

FILLER = ("SPEAKER_00", "Danach erzählt sie lange von Reisen, Kochen und Gartenarbeit.", 60.0)


@pytest.fixture
def policy(monkeypatch, tmp_path):
    """Fassung 2 mit Overrides (Punktpfad zu Wert), spaCy aus."""
    source = editorial.policy_dir()

    def make(**overrides):
        for path in source.glob("clip_policy_v*.yaml"):
            shutil.copy(path, tmp_path)
        target = tmp_path / "clip_policy_v2.yaml"
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        for dotted, value in overrides.items():
            node = data
            *parents, leaf = dotted.split(".")
            for part in parents:
                node = node[part]
            node[leaf] = value
        target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
        monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
        monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
        editorial.clear_cache()
        return editorial.load()

    yield make
    editorial.clear_cache()


ON = {"context.claim_index.enabled": True}


def sents_of(script):
    words = make_words(script)
    return words, segment.sentences_from_words(words, rule="v2")


def hit_for(hits, idx):
    return next(h for h in hits if h["sentence_idx"] == idx)


CLIP = [
    ("SPEAKER_00", "Kaltakquise funktioniert für jedes Unternehmen im Mittelstand.", 5.0),
    ("SPEAKER_00", "Wir haben damit 40 Neukunden gewonnen.", 4.0),
]


def test_claim_index_is_off_by_default_and_needs_rule_and_switch(policy):
    assert story_graph.claim_index_settings(policy()) is None, "Regel context.claim_index.enabled steht auf false"
    assert story_graph.claim_index_settings(policy(**ON)) == {"max_hits": 5, "min_overlap": 0.2}
    assert story_graph.claim_index_settings(policy(**ON, **{"implementation.context.claim_index": False})) is None
    assert story_graph.claim_index_settings(editorial.load(1)) is None


def test_claim_index_lists_sentences_with_claim_features():
    _w, sents = sents_of([
        ("A", "Laut Herr Brenner sind es 40 Prozent.", 3.0), ("A", "Das ist schön.", 2.0),
        ("A", "Das gilt nur, wenn man früh anfängt.", 3.0), ("A", "Damals war das nicht so.", 3.0),
    ])  # fmt: skip
    index = {e["sentence_idx"]: e for e in story_graph.build_claim_index(sents)}
    assert set(index) == {0, 2, 3}
    assert {"number", "attribution"} <= set(index[0]["kinds"]) and index[0]["names"] == ["brenner"]
    assert {"condition", "restriction"} <= set(index[2]["kinds"])
    assert {"negation", "time"} <= set(index[3]["kinds"])


def test_relativization_ten_minutes_later_is_found(policy):
    """Die Relativierung steht gut zehn Minuten nach dem Clip, weit außerhalb des 60-s-Fensters."""
    pol = policy(**ON)
    _w, sents = sents_of([*CLIP, *[FILLER] * 10, ("SPEAKER_00", "Kaltakquise funktioniert allerdings nur, wenn das Angebot im Mittelstand klar ist.", 5.0)])
    late = len(sents) - 1
    assert sents[late].start - sents[1].end > 600
    hits = story_graph.context_hits(sents, 0, 1, policy=pol)
    h = hit_for(hits, late)
    assert h["context_class"] == "self_correction" and h["class_reason"] == "qualification" and h["reaction"] == "review"
    assert h["marker"] == "allerdings" and h["seconds_from_clip"] > 600
    # Der Story-Graph sieht den Satz unter Regel v2 jetzt auch ohne 60-s-Grenze und kennt seine Klasse.
    later = story_graph.find_later_qualifications(sents, 0, 1, rule="v2", policy=pol)
    assert [x["context_class"] for x in later if x["sentence_idx"] == late] == ["self_correction"]
    assert story_graph.find_later_qualifications(sents, 0, 1, rule="v2", policy=policy()) == [], "ohne Claim-Index 60 s"


def test_unrelated_sentence_with_same_number_is_unrelated(policy):
    pol = policy(**ON)
    _w, sents = sents_of([
        ("SPEAKER_00", "Die Antwortquote unserer Kampagne lag bei 40 Prozent.", 4.0), ("SPEAKER_00", "Das hat uns gefreut.", 2.0),
        FILLER, ("SPEAKER_00", "Mein Handy stand beim Wandern im Gebirge bei 40 Prozent.", 4.0),
    ])  # fmt: skip
    h = hit_for(story_graph.context_hits(sents, 0, 1, policy=pol), len(sents) - 1)
    assert h["context_class"] == "unrelated" and h["class_reason"] == "same_number_only" and h["reaction"] == "none"


def test_repetition_of_the_same_statement_is_no_correction(policy):
    """Gegenbeispiel: dieselbe Aussage noch einmal, gleiche Zahl, gleiche Polarität: Ergänzung, keine Korrektur."""
    pol = policy(**ON)
    _w, sents = sents_of([*CLIP, *[FILLER] * 3, ("SPEAKER_00", "Wie gesagt, wir haben damit 40 Neukunden gewonnen.", 4.0)])
    h = hit_for(story_graph.context_hits(sents, 0, 1, policy=pol), len(sents) - 1)
    assert h["context_class"] == "addition" and h["class_reason"] == "repetition" and h["reaction"] == "hint"
    words = make_words([*CLIP, *[FILLER] * 3, ("SPEAKER_00", "Wie gesagt, wir haben damit 40 Neukunden gewonnen.", 4.0)])
    assert editorial_gates.later_correction(words, sents, 0, 1, pol)["passed"] is True


def test_self_correction_with_other_number_hits_later_correction_beyond_60_s(policy):
    script = [*CLIP, *[FILLER] * 3, ("SPEAKER_00", "Es waren damit eigentlich 30 Neukunden, die wir gewonnen haben.", 4.0)]
    words, sents = sents_of(script)
    late = len(sents) - 1
    pol = policy(**ON)
    h = hit_for(story_graph.context_hits(sents, 0, 1, policy=pol), late)
    assert h["context_class"] == "self_correction" and h["class_reason"] == "number" and h["reaction"] == "later_correction"
    assert h["heal_to_sentence_idx"] is None, "drei Minuten liegen außerhalb der Heilreichweite"
    gate = editorial_gates.later_correction(words, sents, 0, 1, pol)
    assert gate["passed"] is False and gate["healable"] is None and gate["heal_to_sentence_idx"] == late
    assert "abweichende Zahl" in gate["detail"]
    # Ohne Claim-Index bleibt das Gate beim 60-s-Fenster und sieht die Korrektur nicht.
    assert editorial_gates.later_correction(words, sents, 0, 1, policy())["passed"] is True


def test_self_correction_in_reach_heals_to_the_correcting_sentence(policy):
    script = [*CLIP, ("SPEAKER_00", "Ich korrigiere mich.", 1.5), ("SPEAKER_00", "Es waren damit 30 Neukunden.", 2.0)]
    words, sents = sents_of(script)
    pol = policy(**ON)
    h = hit_for(story_graph.context_hits(sents, 0, 1, policy=pol), 3)
    assert h["context_class"] == "self_correction" and h["class_reason"] == "marker" and h["heal_to_sentence_idx"] == 3
    gate = editorial_gates.later_correction(words, sents, 0, 1, pol)
    assert gate["passed"] is False and gate["healable"] == "back"


def test_contradiction_by_other_speaker_is_a_flag_with_evidence(policy):
    pol = policy(**ON)
    _w, sents = sents_of([*CLIP, FILLER, ("SPEAKER_01", "Das stimmt nicht, Kaltakquise funktioniert im Mittelstand kaum.", 4.0)])
    report = story_graph.context_report(sents, 0, 1, pol)
    late = len(sents) - 1
    h = hit_for(report["hits"], late)
    assert h["context_class"] == "contradiction_by_other" and h["reaction"] == "flag"
    (flag,) = report["flags"]
    assert flag["flag"] == "debate_contradiction" and flag["sentence_idx"] == late and flag["source_span"]["start_s"] == h["start_s"]
    assert report["note"] == story_graph.CLAIM_INDEX_NOTE and "kein Beleg" in report["note"]


def test_agreement_by_other_speaker_is_unrelated(policy):
    pol = policy(**ON)
    _w, sents = sents_of([*CLIP, ("SPEAKER_01", "Kaltakquise funktioniert bei uns im Mittelstand auch gut.", 4.0)])
    assert hit_for(story_graph.context_hits(sents, 0, 1, policy=pol), 2)["context_class"] == "unrelated"


def test_top_m_limits_hits(policy):
    pol = policy(**ON, **{"context.claim_index.max_hits": 2})
    script = [*CLIP, *[("SPEAKER_00", "Kaltakquise funktioniert nur im Mittelstand.", 3.0)] * 5]
    _w, sents = sents_of(script)
    assert len(story_graph.context_report(sents, 0, 1, pol)["hits"]) == 2


def test_run_writes_context_hits_and_classes(brain, llm, policy):  # noqa: F811
    policy(**ON, **{"implementation.search.payoff_first": False})
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    for c in [*report.candidates, *report.verworfen]:
        ctx = c.rubric["context_hits"]
        assert ctx["method"] == "lemma_jaccard" and ctx["max_hits"] == 5 and isinstance(ctx["hits"], list)
        for fl in c.story_graph_flags:
            hit = next((h for h in ctx["hits"] if h["sentence_idx"] == fl["sentence_idx"]), None)
            assert hit is None or fl["context_class"] == hit["context_class"]
    json.dumps(report.to_json(), ensure_ascii=False)


def test_run_without_claim_index_has_no_context_hits(brain, llm, policy):  # noqa: F811
    policy(**{"implementation.search.payoff_first": False})
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert all("context_hits" not in c.rubric for c in report.candidates)
