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


# -- AP2: eine Satzende-Funktion, Regel v1 und v2 ------------------------------------------------


def _is_sentence_end_before_ap2(words: list[dict], i: int, min_pause_s: float = 0.7) -> bool:
    """Wörtliche Kopie von ``dach_nlp.is_sentence_end`` vor AP2 (Stand 35de380), als Maßstab für v1."""
    w = words[i]
    text = str(w.get("text", "")).strip()
    nxt = words[i + 1] if i + 1 < len(words) else None
    if nxt is None:
        return True
    pause = float(nxt.get("start", 0.0)) - float(w.get("end", 0.0))
    long_pause = pause >= min_pause_s
    speaker_change = nxt.get("speaker") is not None and nxt.get("speaker") != w.get("speaker")
    stripped = dach_nlp._strip_trailing(text)
    if stripped.endswith(("!", "?", "…")):
        return True
    if stripped.endswith("."):
        nxt_text = str(nxt.get("text", "")).strip()
        if dach_nlp.is_ordinal(stripped) or nxt_text[:1].isdigit() or dach_nlp.is_abbreviation(stripped):
            return long_pause or speaker_change
        return True
    return long_pause or speaker_change


def _paused(tokens: list[str], pause_after: dict[int, float], speaker: str = "S0") -> list[dict]:
    out, t = [], 0.0
    for k, tok in enumerate(tokens):
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.3, 3), "speaker": speaker})
        t += 0.32 + pause_after.get(k, 0.0)
    return out


def test_rule_v1_is_unchanged_on_every_fixture_word():
    from tests.editorial_v1 import harness
    from tests.transcript_fixtures import demo_words

    lists = [demo_words()] + [c["words"] for c in harness.load_cases()]
    lists.append(_paused(["Und", "dann...", "Wir", "haben", "es", "so.", "Das", "ist", "max.", "3.", "Platz"], {1: 1.0, 5: 0.8}))
    for words in lists:
        for i in range(len(words)):
            assert dach_nlp.is_sentence_end(words, i) is _is_sentence_end_before_ap2(words, i), (i, words[i]["text"])
            assert dach_nlp.is_sentence_end(words, i, rule="v1") is _is_sentence_end_before_ap2(words, i)


def test_abbreviations_v2_drop_words_that_end_sentences():
    assert {"so", "i", "mag", "max", "art", "min"} <= dach_nlp.ABBREVIATIONS
    assert not {"so", "i", "mag", "max", "art", "min"} & dach_nlp.ABBREVIATIONS_V2
    assert {"so", "i", "mag", "max", "art", "min"} == dach_nlp.ABBREVIATIONS - dach_nlp.ABBREVIATIONS_V2
    for text in ("so.", "i.", "mag.", "Max.", "Art.", "min."):
        assert dach_nlp.is_abbreviation(text) is True
        assert dach_nlp.is_abbreviation(text, rule="v2") is False
    for text in ("z.", "B.", "z.B.", "Dr.", "usw.", "u.a."):
        assert dach_nlp.is_abbreviation(text, rule="v2") is True


def test_das_ist_so_ends_a_sentence_under_v2_only():
    w = _words(["Das", "ist", "so.", "Deshalb", "geben", "wir", "nichts."])
    assert dach_nlp.sentence_end_kind(w, 2, "v2") == "punct"
    assert dach_nlp.sentence_end_kind(w, 2, "v1") == "none"


def test_pause_before_lowercase_word_is_no_boundary_under_v2():
    """Befund 1: „In Wahrheit haben wir … drei Jahre“ wurde an der Pause in zwei Sätze zerlegt."""
    w = _paused(["In", "Wahrheit", "haben", "wir", "drei", "Jahre", "gebraucht."], {3: 0.9})
    assert dach_nlp.sentence_end_kind(w, 3, "v1") == "pause_candidate"
    assert dach_nlp.sentence_end_kind(w, 3, "v2") == "none"


def test_pause_with_open_bracket_is_no_boundary_even_before_a_noun():
    w = _paused(["Wir", "haben", "dann", "stattdessen", "Newsletter", "gemacht."], {3: 0.9})
    assert dach_nlp.sentence_end_kind(w, 3, "v2") == "none"
    w = _paused(["Wir", "arbeiten", "mit", "einem", "Kunden", "zusammen."], {3: 1.2})
    assert dach_nlp.sentence_end_kind(w, 3, "v2") == "none"
    w = _paused(["Ich", "glaube", "dass", "wir", "das", "Projekt", "schaffen."], {4: 1.0})
    assert dach_nlp.sentence_end_kind(w, 4, "v2") == "none"


def test_pause_after_closed_sentence_before_capital_is_a_boundary():
    w = _paused(["Wir", "haben", "das", "gemacht", "Heute", "läuft", "es", "gut."], {3: 1.0})
    assert dach_nlp.sentence_end_kind(w, 3, "v2") == "pause_candidate"
    assert dach_nlp.is_sentence_end(w, 3, rule="v2") is True


def test_demo_script_sentence_11_stays_a_boundary_under_v2():
    """Plan AP2: „…gewartet, aber“ hängt an der Pause. Unter v2 bleibt es eine Grenze, weil „Allerdings“
    großgeschrieben ist und keine Klammer offen ist (ein abgebrochener Satz, kein offener)."""
    from tests.transcript_fixtures import demo_words

    w = demo_words()
    i = next(k for k, x in enumerate(w) if x["text"] == "aber" and w[k + 1]["text"] == "Allerdings")
    assert dach_nlp.sentence_end_kind(w, i, "v1") == "pause_candidate"
    assert dach_nlp.sentence_end_kind(w, i, "v2") == "pause_candidate"


def test_speaker_change_is_a_boundary_under_both_rules():
    w = _words(["Ich", "bin", "ehrlich,"], speaker="A") + _words(["Okay."], speaker="B")
    for k, x in enumerate(w):
        x["start"], x["end"] = k * 0.4, k * 0.4 + 0.3
    assert dach_nlp.sentence_end_kind(w, 2, "v1") == "speaker_change"
    assert dach_nlp.sentence_end_kind(w, 2, "v2") == "speaker_change"


def test_ellipsis_is_no_punctuation_under_v2():
    w = _words(["Und", "dann…", "kam", "der", "Fehler."])
    assert dach_nlp.sentence_end_kind(w, 1, "v2") == "none"
    w = _paused(["Und", "dann...", "Wir", "haben", "es", "gelassen."], {1: 1.0})
    assert dach_nlp.sentence_end_kind(w, 1, "v1") == "punct"
    assert dach_nlp.sentence_end_kind(w, 1, "v2") == "pause_candidate"


def test_last_word_is_end_of_text_and_unknown_rule_fails():
    w = _words(["Ende"])
    assert dach_nlp.sentence_end_kind(w, 0, "v2") == "end_of_text"
    import pytest

    with pytest.raises(ValueError, match="unbekannte Satzende-Regel"):
        dach_nlp.sentence_end_kind(w, 0, "v3")


def test_annotate_writes_sentence_idx_by_rule():
    tokens = ["In", "Wahrheit", "haben", "wir", "drei", "Jahre", "gebraucht.", "Das", "ist", "so.", "Fertig."]
    v1 = dach_nlp.annotate(_paused(tokens, {3: 0.9}))
    v2 = dach_nlp.annotate(_paused(tokens, {3: 0.9}), rule="v2")
    assert [w["sentence_idx"] for w in v1] == [0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2]
    assert [w["sentence_idx"] for w in v2] == [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2]


def test_nlp_status_names_the_fallback(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    assert dach_nlp.nlp_status() == "heuristic"
