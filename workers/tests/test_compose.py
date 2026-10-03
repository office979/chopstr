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


# -- AP7: Splice-Zählung, Debattenregel, Ausgabetimeline, Mittelpunkt-Zuordnung ------------------------


def _turns(*turns):
    """Wörter aus (Sprecher, Text)-Paaren, 0,4 s je Wort, 0,1 s Lücke."""
    out, t = [], 0.0
    for spk, text in turns:
        for tok in text.split():
            out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.4, 3), "speaker": spk})
            t += 0.5
    return out


def test_is_debate_needs_two_speakers_with_changes():
    debate = _turns(("A", "Ich finde das falsch."), ("B", "Ich sehe das ganz anders."), ("A", "Warum denn?"))
    assert compose.is_debate(debate, 0, len(debate) - 1) is True
    interview = _turns(("A", "Wie lief das?"), ("B", "Gut, wir haben verkauft."))
    assert compose.is_debate(interview, 0, len(interview) - 1) is False  # Frage und Antwort: ein Wechsel
    monolog = _turns(("A", "Wir haben das gemacht,"), ("B", "Genau."), ("A", "und es lief gut."))
    assert compose.is_debate(monolog, 0, len(monolog) - 1) is False  # Einwurf zählt nicht als Beitrag
    assert compose.is_debate(debate, 4, len(debate) - 1) is False  # nur B und A: ein Wechsel


def test_debate_rule_forbids_teaser_only_when_asked():
    words = _turns(("A", "Ich finde das falsch."), ("B", "Ich sehe das ganz anders."), ("A", "Warum denn?"))
    body = compose.Composition([compose.Segment(0.0, words[-1]["end"])])
    teased = compose.with_teaser(body, words[4]["start"], words[8]["end"])
    assert teased.validate(words) == []  # Verhalten vor AP7 (Fassung 1)
    issues = teased.validate(words, debate_no_reorder=True)
    assert issues == ["Debatte: kein Teaser, die Reihenfolge des Gesprächs bleibt (E6)"]
    assert body.validate(words, debate_no_reorder=True) == []


def test_splice_counting_separates_semantic_from_local_joins():
    words = _turns(("A", "Erster Satz hier. Zweiter Satz. Dritter Satz äh hier. Vierter Satz. Fünfter Satz hier."))
    t = [(w["start"], w["end"]) for w in words]
    # Satz 1 | Satz 2 weg | Satz 3 ohne „äh“ | Satz 4 weg | Satz 5
    comp = compose.Composition([
        compose.Segment(t[0][0], t[2][1]), compose.Segment(t[5][0], t[6][1]), compose.Segment(t[8][0], t[8][1]),
        compose.Segment(t[11][0], t[13][1]),
    ])  # fmt: skip
    assert compose.splice_kinds(comp, words) == ["semantic", "local", "semantic"]
    assert comp.validate(words, max_splices=2) == []
    assert comp.validate(words, max_splices=1) == [
        "Zu viele Splices (2 statt höchstens 1 Verbindungen nicht benachbarter Sätze, E6)"
    ]
    assert comp.validate(words) == []  # ohne Grenze wie vor AP7


def test_removed_backchannel_is_a_local_join():
    words = _turns(("A", "Ich bin da ganz ehrlich,"), ("B", "Okay."), ("A", "ich hänge an den Leuten."))
    comp = compose.Composition([compose.Segment(0.0, words[4]["end"]), compose.Segment(words[6]["start"], words[-1]["end"])])
    assert compose.splice_kinds(comp, words) == ["local"]


def test_output_timeline_is_deterministic():
    comp = compose.Composition([
        compose.Segment(10.1, 12.35, "teaser"), compose.Segment(5.0, 7.333), compose.Segment(8.1, 12.6),
    ])  # fmt: skip
    tl = compose.output_timeline(comp)
    assert tl == [
        {"segment_index": 0, "role": "teaser", "source_in": 10.1, "source_out": 12.35, "output_in": 0.0, "output_out": 2.25},
        {"segment_index": 1, "role": "body", "source_in": 5.0, "source_out": 7.333, "output_in": 2.25, "output_out": 4.583},
        {"segment_index": 2, "role": "body", "source_in": 8.1, "source_out": 12.6, "output_in": 4.583, "output_out": 9.083},
    ]
    assert compose.output_timeline(compose.Composition.from_json(comp.to_json())) == tl
    assert tl[-1]["output_out"] == round(comp.duration, 3)


def test_remap_words_by_midpoint_keeps_words_that_graze_a_boundary():
    words = _words(["a", "b", "c", "d"])  # a 0..0.4, b 0.5..0.9, c 1.0..1.4, d 1.5..1.9
    comp = compose.Composition([compose.Segment(0.0, 0.8), compose.Segment(1.1, 1.9)])
    assert [w["text"] for w in compose.remap_words(words, comp)] == ["a", "d"]  # Standard unverändert
    out = compose.remap_words(words, comp, by_midpoint=True)
    assert [w["text"] for w in out] == ["a", "b", "c", "d"]
    b, c = out[1], out[2]
    assert (b["start"], b["end"]) == (0.5, 0.8)  # auf das Segmentende gekürzt
    assert (c["start"], c["end"]) == (0.8, 1.1)  # Segment 2 beginnt bei 0,8 s Ausgabezeit
    assert all(x["end"] >= x["start"] for x in out)
