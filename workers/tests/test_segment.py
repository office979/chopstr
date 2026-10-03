from __future__ import annotations

from chopstr_worker.pipeline import segment


def _words(tokens, gap=0.1, speaker="S0"):
    out, t = [], 0.0
    for tok in tokens:
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.4, 3), "prob": 0.9, "speaker": speaker})
        t += 0.4 + gap
    return out


def test_sentences_from_words_uses_dach_boundaries():
    words = _words(["Das", "ist", "z.", "B.", "gut.", "Wir", "sind", "3.", "geworden.", "Fertig?"])
    sents = segment.sentences_from_words(words)
    assert [s.text for s in sents] == ["Das ist z. B. gut.", "Wir sind 3. geworden.", "Fertig?"]
    assert sents[0].word_range == (0, 4)
    assert sents[1].idx == 1
    assert sents[2].start == words[9]["start"]
    assert sents[0].to_dict()["word_range"] == [0, 4]


def test_sentences_split_on_speaker_change():
    words = _words(["Ich", "sage", "das"], speaker="S0") + _words(["Genau"], speaker="S1")
    words[3]["start"], words[3]["end"] = 1.6, 2.0
    sents = segment.sentences_from_words(words)
    assert len(sents) == 2
    assert sents[1].speaker == "S1"


def test_candidate_windows_and_chapters():
    sents = [segment.Sentence(i, f"Satz {i}.", i * 5.0, i * 5.0 + 4.5, "S0", (i, i)) for i in range(20)]
    cands = segment.candidate_windows(sents, min_len=12, max_len=30, stride=1)
    assert cands
    assert all(12 <= c.duration <= 30 for c in cands)
    assert all(c.first_sent <= c.last_sent for c in cands)
    chapters = segment.chapterize(sents, chunk_seconds=30)
    assert sum(len(c) for c in chapters) == 20
    assert len(chapters) > 1
    assert segment.numbered(sents[:2]) == "[0] (S0) Satz 0.\n[1] (S0) Satz 1."


# -- AP2: Sätze aus der vorhandenen sentence_idx ------------------------------------------------


def test_sentences_from_annotated_mirror_the_annotation():
    from chopstr_worker.pipeline import dach_nlp

    words = _words(["Das", "ist", "so.", "Wir", "machen", "weiter.", "Fertig?"])
    dach_nlp.annotate(words, rule="v2")
    sents = segment.sentences_from_annotated(words)
    assert [s.text for s in sents] == ["Das ist so.", "Wir machen weiter.", "Fertig?"]
    assert [s.word_range for s in sents] == [(0, 2), (3, 5), (6, 6)]
    assert [s.idx for s in sents] == [0, 1, 2]
    assert sents[1].start == words[3]["start"] and sents[1].end == words[5]["end"]


def test_sentences_from_annotated_keeps_an_existing_v1_annotation():
    """Eine bestehende Transkriptversion behält ihre Sätze, auch wenn die Regel sich ändert."""
    from chopstr_worker.pipeline import dach_nlp

    words = _words(["Das", "ist", "so.", "Wir", "machen", "weiter."])
    dach_nlp.annotate(words)  # v1: „so." ist eine Abkürzung
    assert [s.text for s in segment.sentences_from_annotated(words)] == ["Das ist so. Wir machen weiter."]
    assert [s.text for s in segment.sentences_from_words(words, rule="v2")] == ["Das ist so.", "Wir machen weiter."]


def test_sentences_from_annotated_without_index_returns_nothing():
    words = _words(["Das", "ist", "gut."])
    assert segment.sentences_from_annotated(words) == []
    words[1]["sentence_idx"] = 0
    assert segment.sentences_from_annotated(words) == []
    assert segment.sentences_from_annotated([]) == []


# -- AP5: Kapitelüberlappung ----------------------------------------------------------------------


def _five_second_sentences(n: int) -> list[segment.Sentence]:
    return [segment.Sentence(i, f"Satz {i}.", i * 5.0, i * 5.0 + 4.5, "S0", (i, i)) for i in range(n)]


def test_chapterize_without_overlap_is_unchanged():
    sents = _five_second_sentences(20)
    assert segment.chapterize(sents, 30) == segment.chapterize(sents, 30, overlap_s=0.0)
    assert sum(len(c) for c in segment.chapterize(sents, 30)) == 20


def test_chapterize_overlap_repeats_the_tail_of_the_previous_chapter():
    sents = _five_second_sentences(20)
    plain = segment.chapterize(sents, 30)
    over = segment.chapterize(sents, 30, overlap_s=10.0)
    # Jedes Kapitel ab dem zweiten beginnt mit den Sätzen, die in den letzten 10 s des vorigen beginnen.
    for prev, cur in zip(over, over[1:]):
        tail = [s for s in prev if s.start >= prev[-1].end - 10.0]
        assert cur[: len(tail)] == tail and len(tail) < len(prev)
    # Jeder Satz kommt vor, keiner fällt weg, und das letzte Kapitel enthält neue Sätze.
    assert {s.idx for c in over for s in c} == set(range(20))
    assert over[-1][-1].idx == 19 and len(over) >= len(plain)


def test_chapterize_overlap_never_repeats_a_whole_chapter():
    """Längere Überlappung als ein Kapitel: das folgende Kapitel wiederholt nie das ganze vorige."""
    sents = _five_second_sentences(8)
    over = segment.chapterize(sents, 10, overlap_s=100.0)
    for prev, cur in zip(over, over[1:]):
        assert [s.idx for s in cur[: len(prev)]] != [s.idx for s in prev]
    assert {s.idx for c in over for s in c} == set(range(8))
