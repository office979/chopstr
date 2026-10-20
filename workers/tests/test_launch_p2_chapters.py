"""Lane P2 (Launch Phase 2): Kapitel an Themenwechseln statt fester 240 s (Schalter
``implementation.chapters.topic_shift``, Regel ``chapters.topic_shift.enabled``, Standard aus)."""

from __future__ import annotations

import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import segment, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.test_story_engine import BRIEF, wired  # noqa: F401
from tests.transcript_fixtures import make_words

PRICING = [
    "Unsere Preise waren lange viel zu niedrig für den Markt.",
    "Beim Preismodell haben wir die Marge komplett übersehen.",
    "Die Kunden haben den Preis kaum verglichen, die Marge war ihnen egal.",
    "Mit dem neuen Preismodell steigt die Marge pro Kunde deutlich.",
    "Ein höherer Preis bringt Kunden, die länger bleiben.",
    "Preis und Marge hängen am Wert, den Kunden sehen.",
]
HIRING = [
    "Beim Recruiting haben wir Bewerber viel zu lange warten lassen.",
    "Gute Bewerber nehmen im Recruiting das erste Angebot.",
    "Unser Team hat Bewerbungsgespräche jetzt auf zwei Termine gekürzt.",
    "Im Recruiting zählt Tempo mehr als das perfekte Team.",
    "Neue Mitarbeiter im Team brauchen einen klaren Einstieg.",
    "Bewerber fragen im Gespräch zuerst nach dem Team.",
]
TRAVEL = [
    "Übrigens war ich letzte Woche im Urlaub am Gardasee.",
    "Das Wetter am Gardasee war herrlich sonnig.",
]
SENTENCE_S = 9.2  # mit 0,8 s Pause genau 10 s je Satz


def _script(*blocks: tuple[list[str], int], speaker: str = "SPEAKER_00") -> list[tuple[str, str, float]]:
    return [(speaker, pool[i % len(pool)], SENTENCE_S) for pool, n in blocks for i in range(n)]


def _sents(*blocks: tuple[list[str], int]) -> list[segment.Sentence]:
    return segment.sentences_from_words(make_words(_script(*blocks)))


def test_topic_shift_is_found():
    """Preise 150 s, dann Recruiting 200 s: die Grenze liegt am Themenwechsel, nicht bei 240 s."""
    sents = _sents((PRICING, 15), (HIRING, 20))
    chapters, meta = segment.chapterize_topic_shift(sents)
    assert [(c[0].idx, c[-1].idx) for c in chapters] == [(0, 14), (15, 34)]
    assert meta[0]["boundary"] == "start" and meta[0]["topic_boundary_score"] is None
    assert meta[1]["boundary"] == "topic_shift" and meta[1]["topic_boundary_score"] >= 0.5
    # Gegenprobe: feste 240 s schneiden mitten in das zweite Thema.
    assert [c[-1].idx for c in segment.chapterize(sents, 240.0)][0] == 24


def test_a_continuous_topic_is_not_cut():
    """Ein Thema über 280 s bleibt ein Kapitel; feste 240 s hätten es zerschnitten."""
    sents = _sents((PRICING, 28))
    chapters, meta = segment.chapterize_topic_shift(sents)
    assert len(chapters) == 1 and meta[0]["first_sent"] == 0 and meta[0]["last_sent"] == 27
    assert len(segment.chapterize(sents, 240.0)) == 2


def test_a_short_digression_creates_no_chapter():
    """Gegenbeispiel: ein Einschub von 20 s (Urlaub) mitten im Preisthema ist keine Grenze; geschnitten wird erst
    beim echten Wechsel zu Recruiting."""
    sents = _sents((PRICING, 13), (TRAVEL, 2), (PRICING, 13), (HIRING, 15))
    chapters, meta = segment.chapterize_topic_shift(sents)
    assert [(c[0].idx, c[-1].idx) for c in chapters] == [(0, 27), (28, 42)]
    assert all(m["last_sent"] - m["first_sent"] >= 11 for m in meta), "kein Kapitel aus dem Einschub"


def test_maximum_length_forces_a_cut_and_says_so():
    sents = _sents((PRICING, 45))
    chapters, meta = segment.chapterize_topic_shift(sents, min_s=120.0, max_s=300.0)
    assert len(chapters) == 2
    assert meta[1]["boundary"] == "max_length"
    first_len = chapters[0][-1].end - chapters[0][0].start
    assert 120.0 <= first_len <= 300.0


def test_overlap_carries_the_last_sentences_into_the_next_chapter():
    sents = _sents((PRICING, 15), (HIRING, 20))
    chapters, meta = segment.chapterize_topic_shift(sents, overlap_s=30.0)
    assert chapters[1][0].idx == 12 and meta[1]["first_sent"] == 12
    assert [s.idx for s in chapters[1] if s.idx >= 15][0] == 15


def test_speaker_turns_add_to_the_boundary_score():
    """Gleiche Wörter, aber am Themenwechsel übernimmt ein anderer Sprecher: die Bewertung dieser Lücke steigt."""
    mono = segment.sentences_from_words(make_words(_script((PRICING, 15), (HIRING, 20))))
    mixed = segment.sentences_from_words(make_words(_script((PRICING, 15)) + _script((HIRING, 20), speaker="SPEAKER_01")))
    at = next(g for g in segment.topic_boundary_scores(mono) if g["after_sent"] == 14)
    at_mixed = next(g for g in segment.topic_boundary_scores(mixed) if g["after_sent"] == 14)
    assert at_mixed["speaker"] > at["speaker"] == 0.0
    assert at_mixed["score"] > at["score"]


def test_degenerate_inputs():
    assert segment.chapterize_topic_shift([]) == ([], [])
    one = _sents((PRICING, 1))
    chapters, meta = segment.chapterize_topic_shift(one)
    assert len(chapters) == 1 and meta[0]["boundary"] == "start"
    assert segment.topic_boundary_scores(one) == []


def test_settings_follow_switch_and_rule(wired):  # noqa: F811
    assert story_engine.topic_shift_settings(editorial.load(1)) is None
    pol = wired()
    assert pol.roh["chapters"]["topic_shift"]["enabled"] is False, "Standard aus"
    assert story_engine.topic_shift_settings(pol) is None
    pol = wired(**{"chapters.topic_shift.enabled": True})
    assert story_engine.topic_shift_settings(pol) == {
        "min_s": 120.0, "max_s": 300.0, "window_s": 60.0, "min_boundary_score": 0.5, "speaker_weight": 0.25,
    }  # fmt: skip
    pol = wired(**{"chapters.topic_shift.enabled": True, "implementation.chapters.topic_shift": False})
    assert story_engine.topic_shift_settings(pol) is None
    with pytest.raises(editorial.PolicyError):
        story_engine.topic_shift_settings(wired(**{"chapters.topic_shift.enabled": True, "chapters.topic_shift.min_s": 400}))


def test_run_uses_topic_chapters_only_with_the_rule(wired):  # noqa: F811
    heur = LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())
    words = make_words(_script((PRICING, 15), (HIRING, 20)))
    wired()
    off = story_engine.run(words, BRIEF, {}, None, heur)
    assert off.chapter_meta == [] and "chapter_meta" not in off.to_json()
    wired(**{"chapters.topic_shift.enabled": True})
    on = story_engine.run(words, BRIEF, {}, None, heur)
    assert on.chapters == 2
    assert [(m["chapter"], m["first_sent"], m["boundary"]) for m in on.chapter_meta] == [(0, 0, "start"), (1, 12, "topic_shift")]
    assert on.to_json()["chapter_meta"][1]["topic_boundary_score"] >= 0.5
    assert all(e["chapter"] in (0, 1) for e in on.funnel["pool"])
