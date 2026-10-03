"""Schnittkanten an Wortgrenzen, boundary_confidence und Übergangsprüfung (AP10b, ``pipeline.transitions``)."""

from __future__ import annotations

import copy

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import transitions
from chopstr_worker.pipeline.transitions import CutRules
from tests.editorial_v1 import harness
from tests.transcript_fixtures import demo_words

RULES = CutRules(lead_in_s=0.06, lead_out_s=0.18, min_gap_s=0.1, low_confidence_threshold=0.5)


def w(text: str, start: float, end: float, prob: float = 0.95, speaker: str = "SPEAKER_00", **extra) -> dict:
    return {"text": text, "start": start, "end": end, "prob": prob, "speaker": speaker, **extra}


# Klare Pausen von 0,5 s zwischen den Wörtern, hohe Sicherheit.
CLEAR = [w("Eins", 1.0, 1.4), w("zwei", 1.9, 2.3), w("drei", 2.8, 3.2), w("vier", 3.7, 4.1), w("fünf", 4.6, 5.0)]


def pad(segments: list[dict], words: list[dict], rules: CutRules = RULES) -> list[dict]:
    return transitions.pad_segments(segments, words, rules)


def inside_a_word(t: float, words: list[dict]) -> bool:
    return any(float(x["start"]) + 1e-6 < t < float(x["end"]) - 1e-6 for x in words)


# -- Policy ----------------------------------------------------------------------------------------


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    yield editorial.load()
    editorial.clear_cache()


def test_rules_come_from_policy_v2_and_reference_the_transcription_threshold(v2):
    from chopstr_worker.pipeline import transcribe

    assert transitions.cut_rules(v2) == RULES
    assert v2.roh["cut"]["low_confidence_threshold"] == editorial.CUT_LOW_CONF_REFERENCE
    assert transitions.cut_rules(v2).low_confidence_threshold == transcribe.LOW_CONF_THRESHOLD
    assert "cut.padding" in editorial.V2_IMPLEMENTED_SWITCHES
    for leaf in ("cut.padding", "cut.lead_in_s", "cut.lead_out_s", "cut.min_gap_s", "cut.low_confidence_threshold"):
        assert leaf in editorial.rule_paths(v2.roh) and v2.roh["origins"][leaf]["origin"] in ("H", "R")


def test_no_rules_under_v1_or_with_switch_or_rule_off(v2):
    assert transitions.cut_rules(editorial.load(1)) is None
    for path in (("implementation", "cut", "padding"), ("cut", "padding")):
        raw = copy.deepcopy(v2.roh)
        node = raw
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = False
        assert transitions.cut_rules(editorial.Policy(version=2, stand=v2.stand, roh=raw)) is None
    # Ohne Regeln bleiben die Zeiten unverändert.
    segs = [{"start": 1.0, "end": 3.2, "role": "body"}]
    out = transitions.pad_segments(segs, CLEAR, editorial.load(1))
    assert [(s["start"], s["end"], s["boundary_confidence"]) for s in out] == [(1.0, 3.2, None)]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda raw: raw.pop("cut"), "der Abschnitt cut fehlt"),
        (lambda raw: raw["cut"].update(low_confidence_threshold="transcribe.ANDERS"), "low_confidence_threshold"),
        (lambda raw: raw["cut"].update(lead_out_s=-0.1), "nicht negativ"),
        (lambda raw: raw["cut"].update(padding="ja"), "cut.padding ist true oder false"),
    ],
)
def test_broken_cut_section_fails_loudly(v2, change, message):
    raw = copy.deepcopy(v2.roh)
    change(raw)
    with pytest.raises(editorial.PolicyError, match=message):
        editorial.cut_settings(editorial.Policy(version=2, stand=v2.stand, roh=raw))


# -- pad_segments ----------------------------------------------------------------------------------


def test_lead_in_and_lead_out_with_room():
    (s,) = pad([{"start": 1.9, "end": 3.2, "role": "body"}], CLEAR)
    assert (s["start"], s["end"]) == (1.84, 3.38)
    assert s["boundary_confidence"] > 0.9 and s["low_confidence"] is False


def test_lead_out_is_limited_by_the_next_word():
    words = [w("Eins", 1.0, 1.4), w("zwei", 1.5, 1.9), w("drei", 1.98, 2.3)]
    (s,) = pad([{"start": 1.0, "end": 1.9, "role": "body"}], words, CutRules(0.06, 0.18, 0.1, 0.0))
    assert s["end"] == 1.98  # nie in „drei“ hinein, obwohl 0,18 s erlaubt wären
    (s,) = pad([{"start": 1.5, "end": 1.9, "role": "body"}], words, CutRules(0.06, 0.18, 0.1, 0.0))
    assert s["start"] == 1.44  # 0,06 s vor „zwei“, die Lücke zu „Eins“ ist 0,1 s


def test_gapless_asr_times_get_no_padding():
    words = [w("Eins", 1.0, 1.4), w("zwei", 1.4, 1.8), w("drei", 1.8, 2.2), w("vier", 2.2, 2.6)]
    (s,) = pad([{"start": 1.4, "end": 2.2, "role": "body"}], words)
    assert (s["start"], s["end"]) == (1.4, 2.2)


def test_edge_never_lands_inside_a_word():
    words = [w("Eins", 1.0, 1.4), w("zwei", 1.5, 1.9), w("drei", 2.0, 2.4), w("vier", 2.5, 2.9)]
    # Start in der zweiten Hälfte von „Eins“ (Mitte außerhalb): „Eins“ fällt heraus.
    # Ende in der ersten Hälfte von „vier“ (Mitte außerhalb): „vier“ fällt heraus.
    (s,) = pad([{"start": 1.3, "end": 2.6, "role": "body"}], words)
    assert not inside_a_word(s["start"], words) and not inside_a_word(s["end"], words)
    assert (s["start"], s["end"]) == (1.44, 2.5)  # Nachlauf bis an „vier“, nicht hinein
    # Start in der ersten Hälfte von „zwei“ (Mitte innen): das ganze Wort kommt mit Vorlauf hinein.
    (s,) = pad([{"start": 1.6, "end": 2.4, "role": "body"}], words)
    assert s["start"] == 1.44 and not inside_a_word(s["start"], words)


@pytest.mark.parametrize("seed", range(5))
def test_edges_never_inside_a_word_on_the_demo_transcript(seed):
    words = demo_words()
    n = len(words)
    for a in range(seed, n - 1, 7):
        for b in range(a, min(n, a + 40), 9):
            for s in pad([{"start": words[a]["start"], "end": words[b]["end"], "role": "body"}], words):
                assert not inside_a_word(s["start"], words) and not inside_a_word(s["end"], words)
                assert s["start"] <= words[a]["start"] and s["end"] >= words[b]["end"]
                assert words[a]["start"] - s["start"] <= RULES.lead_in_s + 1e-9
                assert s["end"] - words[b]["end"] <= RULES.lead_out_s + 1e-9


def test_silence_already_in_the_segment_stays():
    """Eine Kante, die weiter in der Stille liegt (Pause aus der Kürzung oder dem Editor), wird nicht gekürzt."""
    (s,) = pad([{"start": 1.6, "end": 3.5, "role": "body"}], CLEAR)
    assert (s["start"], s["end"]) == (1.6, 3.5)


def test_low_confidence_is_marked_and_stays_in_the_middle_of_the_silence():
    words = [w("Eins", 1.0, 1.4, prob=0.3), w("zwei", 1.5, 1.9, prob=0.3), w("drei", 2.0, 2.4, prob=0.3)]
    (s,) = pad([{"start": 1.5, "end": 1.9, "role": "body"}], words)
    assert s["low_confidence"] is True and s["boundary_confidence"] < 0.5
    assert (s["start"], s["end"]) == (1.45, 1.95)  # halbe Lücke, nie bis an das Nachbarwort
    assert not inside_a_word(s["start"], words) and not inside_a_word(s["end"], words)


def test_continuous_seam_shares_the_gap_and_never_doubles_audio():
    words = [w("Eins", 1.0, 1.4), w("zwei", 1.5, 1.9), w("drei", 2.1, 2.5), w("vier", 2.6, 3.0)]
    # Pause zwischen „zwei“ und „drei“ (0,2 s) entfernt: Naht, an der die Quelle direkt weiterläuft.
    a, b = pad([{"start": 1.0, "end": 1.9, "role": "body"}, {"start": 2.1, "end": 3.0, "role": "body"}], words)
    assert a["end"] <= b["start"] and (a["end"], b["start"]) == (2.0, 2.04)
    # Lücke so klein, dass beide Seiten sich in der Mitte treffen würden: Naht bleibt ungepaddet.
    words[2] = w("drei", 1.95, 2.5)
    a, b = pad([{"start": 1.0, "end": 1.9, "role": "body"}, {"start": 1.95, "end": 3.0, "role": "body"}], words)
    assert (a["end"], b["start"]) == (1.9, 1.95)


def test_segment_without_words_is_left_alone():
    (s,) = pad([{"start": 5.2, "end": 5.5, "role": "body"}], CLEAR)
    assert (s["start"], s["end"], s["boundary_confidence"]) == (5.2, 5.5, None)


# -- boundary_confidence ---------------------------------------------------------------------------


def test_boundary_confidence_formula():
    words = [w("a", 1.0, 1.4, prob=0.9), w("b", 1.5, 1.9, prob=0.8), w("c", 1.9, 2.3, prob=1.0)]
    # Kante nach „a“: p = min(0,9, 0,8), Lücke 0,1 s von 0,25 s.
    assert transitions.boundary_confidence(words, 0, "end") == round(0.6 * 0.8 + 0.4 * 0.4, 3)
    # Kante nach „b“: lückenlos.
    assert transitions.boundary_confidence(words, 1, "end") == round(0.6 * 0.8, 3)
    # Kein Nachbar: Lücke zählt voll.
    assert transitions.boundary_confidence(words, 0, "start") == round(0.6 * 0.9 + 0.4, 3)
    assert transitions.boundary_confidence(words, 2, "end") == 1.0
    # Fehlende prob: 0,5; Fixtures: asr_confidence.
    assert transitions.boundary_confidence([{"text": "x", "start": 0.0, "end": 0.3}], 0, "end") == round(0.6 * 0.5 + 0.4, 3)
    assert transitions.boundary_confidence([{"text": "x", "start": 0.0, "end": 0.3, "asr_confidence": 0.7}], 0) == round(0.6 * 0.7 + 0.4, 3)
    with pytest.raises(ValueError):
        transitions.boundary_confidence(words, 0, "both")


def test_doubtful_word_times_halve_the_confidence():
    base = [w("a", 1.0, 1.4), w("b", 2.0, 2.4)]
    clean = transitions.boundary_confidence(base, 0, "end")
    for doubtful in (
        [w("a", 1.0, 1.0), w("b", 2.0, 2.4)],  # Dauer null
        [w("a", 1.0, 2.1), w("b", 2.0, 2.4)],  # Überlappung
        [w("a", 1.0, 1.4, time_source="interpolated"), w("b", 2.0, 2.4)],  # geschätzte Wortzeit
    ):
        assert transitions.boundary_confidence(doubtful, 0, "end") < clean
        assert transitions.boundary_confidence(doubtful, 0, "end") <= 0.5


def test_case_13_imprecise_timestamps_never_claims_word_accuracy():
    """editorial_v1 Fall 13: jede gepaddete Kante im unsicheren Bereich trägt eine Sicherheit unter 0,5."""
    case = next(c for c in harness.load_cases() if c["id"] == "imprecise_timestamps")
    words = copy.deepcopy(case["words"])
    t0, t1 = case["expected"]["boundary_confidence"]["time_range"]
    hits = 0
    for a in range(len(words)):
        for b in range(a, len(words)):
            seg = harness.segment_from_word_range(case, a, b)
            if seg["source_out"] <= seg["source_in"]:
                continue  # nur Wörter mit Dauer null: kein schneidbares Segment
            (p,) = pad([{"start": seg["source_in"], "end": seg["source_out"], "role": "body"}], words)
            padded = {**seg, "source_in": p["start"], "source_out": p["end"], "boundary_confidence": p["boundary_confidence"]}
            harness.assert_boundary_confidence_honest(case, [padded])
            hits += any(t0 - 0.01 <= padded[k] <= t1 + 0.01 for k in ("source_in", "source_out"))
    assert hits > 20  # der Bereich wird wirklich getroffen, nicht nur umgangen


# -- check_transitions -----------------------------------------------------------------------------


def plan_of(*segments: tuple[float, float] | tuple[float, float, str]) -> dict:
    return {"segments": [{"start": s[0], "end": s[1], "role": s[2] if len(s) > 2 else "body"} for s in segments]}


def test_cut_inside_a_word_is_high():
    found = transitions.check_transitions(plan_of((1.2, 3.38)), CLEAR, RULES)
    cut = [f for f in found if f["type"] == "transition_cut_in_word"]
    assert len(cut) == 1 and cut[0]["severity"] == "high" and cut[0]["edge"] == "in" and cut[0]["word_index"] == 0


def test_cut_on_a_word_boundary_inside_an_overlap_is_medium():
    words = [w("a", 1.0, 2.1), w("b", 2.0, 2.4)]
    found = transitions.check_transitions(plan_of((2.0, 2.5)), words, RULES)
    assert [(f["type"], f["severity"]) for f in found if f["type"] == "transition_cut_in_word"] == [("transition_cut_in_word", "medium")]


def test_padded_plan_has_no_high_finding():
    segs = pad([{"start": 1.0, "end": 2.3, "role": "body"}, {"start": 3.7, "end": 5.0, "role": "body"}], CLEAR)
    found = transitions.check_transitions({"segments": segs}, CLEAR, RULES)
    assert found == []


def test_short_rest_gap_at_the_seam_is_medium():
    found = transitions.check_transitions(plan_of((1.0, 2.3), (3.7, 5.0)), CLEAR, RULES)
    assert [(f["type"], f["severity"], f["rest_s"]) for f in found] == [("transition_gap_short", "medium", 0.0)]
    # Ohne Regeln (Fassung 1) entfällt nur diese Prüfung.
    assert transitions.check_transitions(plan_of((1.0, 2.3), (3.7, 5.0)), CLEAR, editorial.load(1)) == []


def test_speaker_change_at_the_seam_needs_a_reason():
    words = [w("a", 1.0, 1.4), w("b", 1.9, 2.3), w("c", 2.8, 3.2, speaker="SPEAKER_01"), w("d", 3.7, 4.1, speaker="SPEAKER_01")]
    kinds = lambda found: [f["type"] for f in found if f["type"] == "transition_speaker_change"]  # noqa: E731
    # Geschnitten wurde „b“ bis „c“ übersprungen: Wechsel ohne Grund.
    assert kinds(transitions.check_transitions(plan_of((0.94, 1.58), (3.64, 4.28)), words, RULES)) == ["transition_speaker_change"]
    # Nur die Pause entfernt, die Quelle läuft direkt weiter: der Wechsel ist echt.
    assert kinds(transitions.check_transitions(plan_of((1.84, 2.48), (2.74, 3.38)), words, RULES)) == []
    # Teaser vorn: gewollter Sprung.
    assert kinds(transitions.check_transitions(plan_of((2.74, 3.38, "teaser"), (0.94, 2.48)), words, RULES)) == []


def test_half_word_without_caption_is_medium():
    found = transitions.check_transitions(plan_of((1.3, 3.38)), CLEAR, RULES)
    lost = [f for f in found if f["type"] == "transition_caption_lost"]
    assert len(lost) == 1 and lost[0]["severity"] == "medium" and lost[0]["word_index"] == 0
    # Wort mit Mitte im Segment: Caption nach Wortmitte, kein Befund (aber Schnitt im Wort: hoch).
    found = transitions.check_transitions(plan_of((1.1, 3.38)), CLEAR, RULES)
    assert [f["type"] for f in found] == ["transition_cut_in_word"]


def test_findings_are_german_and_typed():
    found = transitions.check_transitions(plan_of((1.3, 2.3), (3.7, 4.8)), CLEAR, RULES)
    assert found and all(f["type"].startswith("transition_") and f["severity"] in ("high", "medium") for f in found)
    assert all("–" not in f["detail"] and "—" not in f["detail"] for f in found)


def test_padding_is_idempotent():
    """Die gepaddeten Segmente stehen nach dem Render am Clip; ein zweiter Lauf darf sie nicht weiter verschieben."""
    words = demo_words()
    raw = [
        {"start": words[3]["start"], "end": words[20]["end"], "role": "body"},
        {"start": words[21]["start"], "end": words[40]["end"], "role": "body"},
        {"start": words[60]["start"], "end": words[75]["end"], "role": "body"},
    ]
    once = [{k: s[k] for k in ("start", "end", "role")} for s in pad(raw, words)]
    twice = [{k: s[k] for k in ("start", "end", "role")} for s in pad(once, words)]
    assert once == twice
    low = [w("Eins", 1.0, 1.4, prob=0.3), w("zwei", 1.5, 1.9, prob=0.3), w("drei", 2.0, 2.4, prob=0.3)]
    seg = [{"start": 1.5, "end": 1.9, "role": "body"}]
    once = [{k: s[k] for k in ("start", "end", "role")} for s in pad(seg, low)]
    assert [{k: s[k] for k in ("start", "end", "role")} for s in pad(once, low)] == once
