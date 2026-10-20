"""Lane P4, Aufgabe 4: Split-Screen bei Überlappung nur mit gesicherter Bindung Sprecher zu Gesicht."""

from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import reframe, tracking
from chopstr_worker.pipeline.tracking import Abtastung, Einstellung, SplitScreenRules, Ziel
from tests.test_launch_p4_prosody import policy_with, w

RULES = SplitScreenRules(min_binding_confidence=0.8)
LEFT, RIGHT = (250, 300, 100, 100), (850, 300, 100, 100)  # Boxen x, y, b, h; Mitten bei x=300 und x=900


def samples(mouth: callable, t0: float = 0.0, t1: float = 10.0, step: float = 0.2) -> list[Abtastung]:
    out, t = [], t0
    while t < t1 - 1e-9:
        left, right = mouth(t)
        out.append(Abtastung(t=round(t, 2), boxen=[LEFT, RIGHT], bildwechsel=0.01, mundbewegung=[left, right]))
        t += step
    return out


def talking(t: float) -> tuple[float, float]:
    """SPEAKER_00 (links) spricht 0 bis 4 s, SPEAKER_01 (rechts) 4 bis 8 s, beide ab 8 s."""
    if t < 4.0:
        return 5.0, 0.5
    if t < 8.0:
        return 0.5, 5.0
    return 5.0, 5.0


def words(overlap: bool = True) -> list[dict]:
    out = [w(f"a{k}", 0.1 + 0.5 * k, 0.5 + 0.5 * k, "SPEAKER_00") for k in range(8)]
    out += [w(f"b{k}", 4.1 + 0.5 * k, 4.5 + 0.5 * k, "SPEAKER_01") for k in range(8)]
    out += [
        {**w(f"o{k}", 8.1 + 0.4 * k, 8.45 + 0.4 * k, "SPEAKER_00" if k % 2 else "SPEAKER_01"), "overlap": overlap, "speakers": ["SPEAKER_00", "SPEAKER_01"]}
        for k in range(4)
    ]  # fmt: skip
    return out


def einstellung(mouth=talking) -> Einstellung:
    abt = samples(mouth)
    return Einstellung(start_s=abt[0].t, ende_s=abt[-1].t, abtastungen=abt)


def test_binding_comes_from_mouth_movement_while_one_speaker_talks_alone():
    e = einstellung()
    b = tracking.speaker_face_binding(e, tracking.positionen(e), words())
    # Ein Abtastpunkt an der Wortgrenze bei 4,0 s stimmt falsch; die Bindung trägt trotzdem.
    assert b["SPEAKER_00"]["position"] == 0 and b["SPEAKER_00"]["x"] == 300.0 and b["SPEAKER_00"]["confidence"] >= 0.9
    assert b["SPEAKER_01"]["position"] == 1 and b["SPEAKER_01"]["x"] == 900.0 and b["SPEAKER_01"]["confidence"] >= 0.9


def test_no_binding_when_mouths_do_not_tell_who_speaks():
    e = einstellung(lambda t: (2.0, 2.0))
    assert tracking.speaker_face_binding(e, tracking.positionen(e), words()) == {}


def test_two_speakers_on_the_same_face_are_both_unbound():
    e = einstellung(lambda t: (5.0, 0.5))  # immer bewegt sich nur der linke Mund
    b = tracking.speaker_face_binding(e, tracking.positionen(e), words())
    assert b["SPEAKER_00"]["confidence"] == 0.0 and b["SPEAKER_01"]["confidence"] == 0.0


def test_overlap_spans_read_the_p1_contract():
    spans = tracking.overlap_spans(words())
    assert spans == [(8.1, 9.65, ["SPEAKER_00", "SPEAKER_01"])]
    assert tracking.overlap_spans(words(overlap=False)) == []


def _ziel() -> list[Ziel]:
    return [Ziel(0.0, 10.0, 300.0, 350.0, 0.5, "sprecher", 100.0, [300.0, 900.0])]


def test_split_only_with_secured_binding_of_both_speakers():
    e = einstellung()
    bound = tracking.speaker_face_binding(e, tracking.positionen(e), words())
    out = tracking.split_bei_overlap(_ziel(), tracking.overlap_spans(words()), bound, RULES)
    geteilt = [z for z in out if z.layout == "geteilt"]
    assert len(geteilt) == 1 and (geteilt[0].start_s, geteilt[0].ende_s) == (8.1, 9.65)
    assert geteilt[0].auswahl == [300.0, 900.0] and geteilt[0].grund == "overlap_gebunden"
    assert [(z.start_s, z.ende_s) for z in out] == [(0.0, 8.1), (8.1, 9.65), (9.65, 10.0)]
    # Unsichere Bindung, zu kurze Überlappung oder keine Überlappung: konservativ, wie bisher.
    weak = {k: {**v, "confidence": 0.5} for k, v in bound.items()}
    assert tracking.split_bei_overlap(_ziel(), tracking.overlap_spans(words()), weak, RULES) == _ziel()
    short = [(8.1, 8.6, ["SPEAKER_00", "SPEAKER_01"])]
    assert tracking.split_bei_overlap(_ziel(), short, bound, RULES) == _ziel()
    assert tracking.split_bei_overlap(_ziel(), [], bound, RULES) == _ziel()


def test_split_screen_rules_are_off_by_default():
    editorial.clear_cache()
    assert tracking.split_screen_rules(editorial.load(1)) is None
    assert tracking.split_screen_rules(editorial.load(2)) is None
    assert tracking.split_screen_rules(policy_with({"cut.split_screen.enabled": True})) == RULES
    assert tracking.split_screen_rules(policy_with({"cut.split_screen.enabled": True, "implementation.cut.split_screen": False})) is None
    with pytest.raises(editorial.PolicyError, match="min_binding_confidence"):
        tracking.split_screen_rules(policy_with({"cut.split_screen.enabled": True, "cut.split_screen.min_binding_confidence": 1.5}))


def test_verfolgen_splits_only_with_rules_and_manual_marks_still_win(monkeypatch):
    monkeypatch.setattr(reframe, "abtasten", lambda path, t0, t1: samples(talking, t0, t1))
    segs = [{"start": 0.0, "end": 10.0, "role": "body"}]
    plain, *_ = reframe.verfolgen("x.mp4", segs, 1280)
    assert not any(z.layout == "geteilt" for zl in plain for z in zl)
    bindungen: list[dict] = []
    split, *_ = reframe.verfolgen("x.mp4", segs, 1280, words=words(), split_rules=RULES, bindungen=bindungen)
    assert any(z.layout == "geteilt" and z.grund == "overlap_gebunden" for zl in split for z in zl)
    assert bindungen and bindungen[0]["binding"]["SPEAKER_01"]["position"] == 1
    marked, *_ = reframe.verfolgen(
        "x.mp4", segs, 1280, zeitmarken=[{"ab_s": 8.0, "x": 300, "layout": "einzel"}], words=words(), split_rules=RULES
    )
    assert not any(z.layout == "geteilt" for zl in marked for z in zl if z.start_s >= 8.0)
    shots = reframe.plan_shots_aus_zielen(segs, split, 1280, 720, 1080, 1920)
    assert any(s.layout == "geteilt" and len(s.geteilt) == 2 for s in shots)


def test_plan_reframe_without_detector_stays_conservative_and_says_so():
    res = reframe.plan_reframe(None, [{"start": 0.0, "end": 10.0, "role": "body"}], words(), None, "9:16", src_w=1280, src_h=720, split_rules=RULES)
    assert all(s.layout != "geteilt" for s in res.shots)
    assert res.plan_block()["speaker_face_binding"] == []
    assert any("ohne gesicherte Zuordnung" in n for n in res.notes)
    off = reframe.plan_reframe(None, [{"start": 0.0, "end": 10.0, "role": "body"}], words(), None, "9:16", src_w=1280, src_h=720)
    assert "speaker_face_binding" not in off.plan_block()
