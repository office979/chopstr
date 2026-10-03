"""Story-Graph: Marker an Wortgrenzen und Korrekturmarker nur unter Regel v2 (AP4); v1 bleibt wie vor AP4."""

from __future__ import annotations

import copy

import pytest

from chopstr_worker.pipeline import dach_nlp, segment, story_graph
from tests.editorial_v1 import harness

CASES = {c["id"]: c for c in harness.load_cases()}


@pytest.fixture(autouse=True)
def no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)


def sents_of(*texts: str) -> list[segment.Sentence]:
    out, t = [], 0.0
    for n, text in enumerate(texts):
        out.append(segment.Sentence(idx=n, text=text, start=t, end=t + 3.0, speaker="SPEAKER_00", word_range=(n, n)))
        t += 3.5
    return out


def _sentence_containing(sents, i):
    return next(s.idx for s in sents if s.word_range[0] <= i <= s.word_range[1])


def _near_duplicate():
    c = CASES["near_duplicate_candidates"]
    sents = segment.sentences_from_words(copy.deepcopy(c["words"]))
    a, b = c["expected"]["near_duplicate_candidates"]["spans"][0]["word_range"]
    target = _sentence_containing(sents, c["expected"]["not_a_qualification_word_range"][0])
    return sents, _sentence_containing(sents, a), _sentence_containing(sents, b), target


def test_v1_still_reads_ausserdem_as_ausser():
    """Bekannter Defekt (RK 2 Befund 6) bleibt unter v1 stehen: Rollback heißt gleiches Verhalten."""
    sents, first, last, target = _near_duplicate()
    hits = story_graph.find_later_qualifications(sents, first, last)
    assert [h["marker"] for h in hits if h["sentence_idx"] == target] == ["außer"]
    assert hits == story_graph.find_later_qualifications(sents, first, last, rule="v1")
    assert all("kind" not in h for h in hits)


def test_v2_matches_markers_at_word_boundaries():
    sents, first, last, target = _near_duplicate()
    hits = story_graph.find_later_qualifications(sents, first, last, rule="v2")
    assert [h for h in hits if h["sentence_idx"] == target] == []


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        ("Außer im Sommer rechnen wir die Preise nicht durch.", "außer"),
        ("Außerdem rechnen wir die Preise im Sommer durch.", None),
        ("Außerhalb der Saison rechnen wir die Preise durch.", None),
        ("Das gilt nur, wenn ihr die Preise vorher rechnet.", "nur wenn"),
    ],
)
def test_find_marker_uses_whole_words(text, marker):
    assert story_graph.find_marker(text, story_graph.CONTRAST_MARKERS) == marker


def test_v2_finds_correction_markers_v1_does_not():
    sents = sents_of(
        "Werbung braucht man eigentlich gar nicht.",
        "Ich korrigiere mich.",
        "Werbung braucht man schon, nur weniger als früher.",
    )
    assert story_graph.find_later_qualifications(sents, 0, 0) == []
    hits = story_graph.find_later_qualifications(sents, 0, 0, rule="v2")
    assert [(h["sentence_idx"], h["marker"], h["kind"]) for h in hits] == [(1, "ich korrigiere mich", "correction")]


def test_v2_keeps_the_later_self_correction_case():
    c = CASES["later_self_correction"]
    lq = c["expected"]["later_qualification"]
    sents = segment.sentences_from_words(copy.deepcopy(c["words"]))
    first = _sentence_containing(sents, lq["claim_word_range"][0])
    last = _sentence_containing(sents, lq["claim_word_range"][1])
    hits = story_graph.find_later_qualifications(sents, first, last, rule="v2")
    ziel = _sentence_containing(sents, lq["qualification_word_range"][0])
    assert any(h["sentence_idx"] == ziel and h["marker"] == lq["marker"] and h["kind"] == "contrast" for h in hits)
    assert any(h["kind"] == "correction" for h in hits)


def test_lexical_overlap_matches_the_v1_formula():
    clip, later = "Werbung braucht man gar nicht.", "Das heißt aber nicht, dass Werbung überflüssig ist."
    lem = story_graph._lemmas(later)
    assert story_graph.lexical_overlap(clip, later) == len(story_graph._lemmas(clip) & lem) / len(lem)
