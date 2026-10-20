"""Verdrahtung der Verbklammer-Erweiterung (Lane P1) im Tor ``story_engine._verb_bracket_gate``.

Unter Fassung 2 laufen zu-Infinitiv, Korrelat und Partikel ohne Satzzeichen an beiden Kanten mit, dazu
offene Korrelate über die ganze Clip-Spanne; unter Fassung 1 bleibt das Tor aus AP3 unverändert.
"""

from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import dach_nlp, segment, story_engine
from tests.test_story_engine import make_words


@pytest.fixture
def policy_v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    yield editorial.load()
    editorial.clear_cache()


def _span(w: list[dict], a: int, b: int) -> segment.Sentence:
    return segment.Sentence(idx=0, text="", start=w[a]["start"], end=w[b]["end"], speaker="SPEAKER_00", word_range=(a, b))


def test_rule01_open_correlate_inside_the_span_fails_under_v2(policy_v2):
    w = make_words([("SPEAKER_00", "Wir haben zwar den Preis gesenkt.", 3.0), ("SPEAKER_00", "Aber die Marge ist geblieben.", 3.0)])
    end = next(i for i, x in enumerate(w) if x["text"] == "gesenkt.")
    g = story_engine._verb_bracket_gate(w, [_span(w, 0, end)], 0, 0)
    assert g["passed"] is False and "Korrelat" in g["detail"] and "zwar" in g["detail"]


def test_rule01_closed_correlate_inside_the_span_passes_under_v2(policy_v2):
    w = make_words([("SPEAKER_00", "Wir haben zwar den Preis gesenkt, aber die Marge ist geblieben.", 5.0)])
    sents = segment.sentences_from_words(w, rule="v2")
    g = story_engine._verb_bracket_gate(w, sents, 0, len(sents) - 1)
    assert g["passed"] is True


def test_rule01_cut_between_zu_and_infinitive_fails_under_v2(policy_v2):
    w = make_words([("SPEAKER_00", "Wir haben beschlossen das Projekt zu", 3.0), ("SPEAKER_00", "stoppen und neu zu planen.", 3.0)])
    start = next(i for i, x in enumerate(w) if x["text"] == "stoppen")
    g = story_engine._verb_bracket_gate(w, [_span(w, start, len(w) - 1)], 0, 0)
    assert g["passed"] is False and "Anfang" in g["detail"]


def test_rule01_v1_gate_ignores_the_extensions(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    try:
        w = make_words([("SPEAKER_00", "Wir haben zwar den Preis gesenkt.", 3.0), ("SPEAKER_00", "Aber die Marge ist geblieben.", 3.0)])
        end = next(i for i, x in enumerate(w) if x["text"] == "gesenkt.")
        g = story_engine._verb_bracket_gate(w, [_span(w, 0, end)], 0, 0)
        assert g["passed"] is True and g["available"] is False
    finally:
        editorial.clear_cache()
