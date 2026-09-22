from __future__ import annotations

from chopstr_worker.pipeline import compose


def _words(tokens, gap=0.1, speaker="S0"):
    out, t = [], 0.0
    for tok in tokens:
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.4, 3), "speaker": speaker})
        t += 0.4 + gap
    return out


def test_from_keep_ranges_merges_small_gaps():
    words = _words(["a", "b", "c", "d", "e"])
    comp = compose.from_keep_ranges(words, [(0, 1), (3, 4)])
    assert len(comp.segments) == 2
    assert comp.segments[0].start == 0.0
    assert comp.duration > 0
    comp2 = compose.from_keep_ranges(words, [(0, 1), (2, 4)])
    assert len(comp2.segments) == 1  # Lücke < 0.15 s wird verschmolzen


def test_teaser_rules():
    words = _words(["a", "b", "c", "d", "e", "f"])
    body = compose.Composition([compose.Segment(0.0, 3.0)])
    ok = compose.with_teaser(body, 1.0, 2.0)
    assert ok.validate(words) == []
    too_long = compose.with_teaser(body, 0.0, 7.0)
    assert any("zu lang" in i for i in too_long.validate(words))
    outside = compose.with_teaser(body, 5.0, 5.5)
    assert any("nicht noch einmal" in i for i in outside.validate(words))
    words[1]["speaker"] = "S1"
    multi = compose.with_teaser(body, 0.0, 1.5)
    assert any("mehrere Sprecher" in i for i in multi.validate(words))


def test_reordered_body_is_flagged():
    comp = compose.Composition([compose.Segment(5.0, 6.0), compose.Segment(0.0, 1.0)])
    assert any("umsortiert" in i for i in comp.validate([]))


def test_remap_words_to_output_timeline():
    words = _words(["a", "b", "c", "d"])  # a: 0..0.4, b: 0.5..0.9, c: 1.0..1.4, d: 1.5..1.9
    comp = compose.Composition([compose.Segment(1.0, 2.0, "teaser"), compose.Segment(0.0, 2.0)])
    out = compose.remap_words(words, comp)
    assert [w["text"] for w in out] == ["c", "d", "a", "b", "c", "d"]
    assert out[0]["start"] == 0.0 and out[0]["segment_role"] == "teaser"
    assert out[2]["start"] == 1.0  # Body beginnt nach 1 s Teaser
    assert compose.Composition.from_json(comp.to_json()).to_json() == comp.to_json()
