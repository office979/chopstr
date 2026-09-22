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
