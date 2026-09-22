from __future__ import annotations

from chopstr_worker.pipeline import dach_nlp


def _words(tokens: list[str], gap: float = 0.1, speaker: str | None = "S0") -> list[dict]:
    out, t = [], 0.0
    for tok in tokens:
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.3, 3), "prob": 0.9, "speaker": speaker})
        t += 0.3 + gap
    return out


def test_abbreviations_are_not_sentence_ends():
    assert dach_nlp.is_abbreviation("z.")
    assert dach_nlp.is_abbreviation("B.")
    assert dach_nlp.is_abbreviation("z.B.")
    assert dach_nlp.is_abbreviation("Dr.")
    assert dach_nlp.is_abbreviation("usw.")
    assert dach_nlp.is_abbreviation("Mio.")
    assert not dach_nlp.is_abbreviation("Haus.")
    assert not dach_nlp.is_abbreviation("Haus")


def test_ordinal_numbers():
    assert dach_nlp.is_ordinal("3.")
    assert dach_nlp.is_ordinal("12.")
    assert not dach_nlp.is_ordinal("2024")
    assert not dach_nlp.is_ordinal("3.5")


def test_sentence_boundaries_respect_abbreviations_ordinals_decimals():
    words = _words(["Wir", "nutzen", "z.", "B.", "Dr.", "Maier.", "Er", "wurde", "3.", "Platz.", "Das", "sind", "2.", "4", "Prozent."])
    ends = dach_nlp.sentence_boundaries(words)
    texts = [words[i]["text"] for i in ends]
    assert texts == ["Maier.", "Platz.", "Prozent."]


def test_long_pause_and_speaker_change_are_boundaries():
    words = _words(["Ich", "glaube", "das"], gap=0.1)
    words[1]["end"] = 1.0
    words[2]["start"] = 2.0  # lange Pause
    assert dach_nlp.is_sentence_end(words, 1)
    words = _words(["ja", "genau"], speaker="S0")
    words[1]["speaker"] = "S1"
    assert dach_nlp.is_sentence_end(words, 0)


def test_question_and_exclamation_with_quotes():
    words = _words(["Wirklich?“", "Ja!", "Gut"])
    assert dach_nlp.is_sentence_end(words, 0)
    assert dach_nlp.is_sentence_end(words, 1)


def test_classify_fillers_keeps_modal_particles():
    words = _words(["Das", "ist", "äh", "halt", "quasi", "nicht", "gut"])
    dach_nlp.classify_fillers(words)
    by = {w["text"]: w for w in words}
    assert by["äh"]["filler"] == "hard"
    assert by["halt"]["filler"] == "modal_keep"
    assert by["quasi"]["filler"] == "soft"
    assert by["nicht"]["negation"] is True
    assert by["gut"]["filler"] is None
    assert by["gut"]["negation"] is False


def test_backchannel_from_other_speaker():
    words = _words(["Wir", "haben", "genau", "damals", "gewonnen"], speaker="S0")
    words[2]["speaker"] = "S1"
    dach_nlp.classify_fillers(words)
    assert words[2]["filler"] == "backchannel"


def test_auto_remove_ranges():
    words = _words(["Wir", "äh", "haben", "ähm", "gewonnen"])
    dach_nlp.classify_fillers(words)
    assert dach_nlp.auto_remove_ranges(words) == [(0, 0), (2, 2), (4, 4)]
    words = _words(["quasi", "gut"])
    dach_nlp.classify_fillers(words)
    assert dach_nlp.auto_remove_ranges(words) == [(0, 1)]
    assert dach_nlp.auto_remove_ranges(words, aggressive=True) == [(1, 1)]


def test_de_number():
    assert dach_nlp.de_number("2.4 Prozent") == "2,4 %"
    assert dach_nlp.de_number("40.000 Euro") == "40.000 Euro"
    assert dach_nlp.de_number("3. Platz") == "3. Platz"
    assert dach_nlp.de_number("12%") == "12 %"


def test_ends_with_open_loop():
    assert dach_nlp.ends_with_open_loop("Das war gut, aber")
    assert dach_nlp.ends_with_open_loop("Und zwar")
    assert dach_nlp.ends_with_open_loop("Das heißt.")
    assert not dach_nlp.ends_with_open_loop("Das war die Entscheidung.")
    assert not dach_nlp.ends_with_open_loop("")


def test_annotate_adds_sentence_idx_filler_negation():
    words = _words(["Ich", "war", "nicht", "da.", "Aber", "äh", "jetzt", "schon."])
    dach_nlp.annotate(words)
    assert [w["sentence_idx"] for w in words] == [0, 0, 0, 0, 1, 1, 1, 1]
    assert words[2]["negation"] is True
    assert words[5]["filler"] == "hard"
    assert words[7]["filler"] == "modal_keep"


def test_forbidden_cut_ranges_without_spacy_returns_empty():
    try:
        import spacy  # noqa: F401

        has_spacy = True
    except ImportError:
        has_spacy = False
    ranges = dach_nlp.forbidden_cut_ranges("Ich habe das gestern gemacht", _words(["Ich", "habe", "das", "gestern", "gemacht"]))
    if not has_spacy:
        assert ranges == []
        assert dach_nlp.verb_bracket_available is False
    else:
        assert isinstance(ranges, list)
    assert dach_nlp.cut_is_legal(0.5, [(1.0, 2.0)])
    assert not dach_nlp.cut_is_legal(1.5, [(1.0, 2.0)])
