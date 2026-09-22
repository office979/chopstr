"""Reframe-Planung ohne Video: Strategien, lückenlose Shots, Mindestlänge, Augen-Drittel, neutral ohne Detektor."""

from __future__ import annotations

import pytest

from chopstr_worker.pipeline import reframe

SRC_W, SRC_H = 1920, 1080
SEGS = [{"start": 10.0, "end": 20.0, "role": "body"}, {"start": 30.0, "end": 36.0, "role": "body"}]


def _words(pattern: list[tuple[float, float, str]]) -> list[dict]:
    return [{"text": "w", "start": s, "end": e, "speaker": spk} for s, e, spk in pattern]


def _alternating(start: float, end: float, step: float, speakers=("SPEAKER_00", "SPEAKER_01")) -> list[dict]:
    out, t, i = [], start, 0
    while t + step <= end + 1e-9:
        out.append({"text": "w", "start": round(t, 3), "end": round(t + step - 0.05, 3), "speaker": speakers[i % 2]})
        t += step
        i += 1
    return out


def _assert_gapless(shots: list[reframe.Shot], segs: list[dict]) -> None:
    by_seg = {(s["start"], s["end"]): [] for s in segs}
    for sh in shots:
        key = next(k for k in by_seg if k[0] <= sh.start and sh.end <= k[1])
        by_seg[key].append(sh)
    for (a, b), lst in by_seg.items():
        assert lst and lst[0].start == a and lst[-1].end == b
        for x, y in zip(lst, lst[1:]):
            assert x.end == y.start


def test_crop_geometry_for_all_aspects():
    assert reframe.crop_geometry(1920, 1080, 1080, 1920) == (606, 1080)
    assert reframe.crop_geometry(1920, 1080, 1080, 1350) == (864, 1080)
    assert reframe.crop_geometry(1920, 1080, 1080, 1080) == (1080, 1080)
    assert reframe.crop_geometry(1920, 1080, 1920, 1080) == (1920, 1080)
    assert reframe.crop_geometry(1280, 720, 1080, 1920) == (404, 720)
    assert reframe.crop_geometry(1080, 1920, 1920, 1080) == (1080, 606)  # Hochkant-Quelle zu 16:9
    for w, h in (reframe.crop_geometry(1919, 1079, 1080, 1920), reframe.crop_geometry(720, 1280, 1080, 1350)):
        assert w % 2 == 0 and h % 2 == 0


def test_neutral_without_positions_is_centered_full_height():
    shots = reframe.plan_shots_for_positions(SEGS, [], SRC_W, SRC_H, 1080, 1920, [], {})
    assert len(shots) == 2 and all(s.layout == "single" for s in shots)
    assert shots[0].crop_x == (SRC_W - 606) // 2 and shots[0].crop_y == 0 and shots[0].crop_h == SRC_H
    _assert_gapless(shots, SEGS)
    assert reframe.strategy_for([]) == "neutral"
    # Quelle hochkant, Ausgabe 16:9: ohne Gesicht vertikal mittig
    s = reframe.plan_shots_for_positions(SEGS, [], 1080, 1920, 1920, 1080, [], {})[0]
    assert s.crop_x == 0 and s.crop_y == (1920 - 606) // 2


def test_talking_head_keeps_eyes_in_upper_third():
    shots = reframe.plan_shots_for_positions(SEGS, _alternating(10, 36, 0.5), SRC_W, SRC_H, 1080, 1920, [1400.0], {}, face_y=[300.0])
    assert len(shots) == 2  # ein Shot pro Segment, kein Schnitt bei einer Position
    assert shots[0].crop_x == 1400 - 606 // 2 and shots[0].crop_h == SRC_H and shots[0].crop_y == 0
    assert reframe.strategy_for([1400.0]) == "talking_head"
    # 1:1-Ausgabe: crop_h < src_h, Gesichtsmitte landet bei 37 % der Ausgabehöhe
    sq = reframe.plan_shots_for_positions(SEGS, [], SRC_W, SRC_H, 1080, 1080, [960.0], {}, face_y=[500.0])[0]
    assert sq.crop_w == sq.crop_h == 1080
    assert sq.crop_y == 0  # 500 - 0.37 * 1080 < 0, geklemmt
    sq2 = reframe.plan_shots_for_positions(SEGS, [], 1080, 2000, 1080, 1080, [540.0], {}, face_y=[900.0])[0]
    assert sq2.crop_h == 1080 and sq2.crop_y == round(900 - reframe.EYE_LINE * 1080)
    assert abs((900 - sq2.crop_y) / 1080 - reframe.EYE_LINE) < 0.001
    # Randklemmung horizontal
    edge = reframe.plan_shots_for_positions(SEGS, [], SRC_W, SRC_H, 1080, 1920, [50.0], {})[0]
    assert edge.crop_x == 0
    edge_r = reframe.plan_shots_for_positions(SEGS, [], SRC_W, SRC_H, 1080, 1920, [1900.0], {})[0]
    assert edge_r.crop_x == SRC_W - 606


def test_two_speakers_cuts_on_active_speaker_gapless_and_min_shot():
    positions = [480.0, 1440.0]
    spk = {"SPEAKER_00": 0, "SPEAKER_01": 1}
    # Sprecherwechsel alle 2 Sekunden im ersten Segment, sehr schnelle Wechsel (0,3 s) im zweiten
    words = _alternating(10, 20, 2.0) + _alternating(30, 36, 0.3)
    shots = reframe.plan_shots_for_positions(SEGS, words, SRC_W, SRC_H, 1080, 1920, positions, spk)
    _assert_gapless(shots, SEGS)
    assert all(s.duration >= reframe.MIN_SHOT_S - 1e-9 for s in shots)
    first = [s for s in shots if s.end <= 20.0]
    assert len(first) == 5 and {s.crop_x for s in first} == {480 - 303, 1440 - 303}
    assert first[0].crop_x != first[1].crop_x  # wechselt tatsächlich
    second = [s for s in shots if s.start >= 30.0]
    assert len(second) >= 1 and all(s.duration >= 1.2 for s in second)
    assert reframe.strategy_for(positions) == "two_speakers"


def test_two_speakers_respects_speaker_positions_mapping():
    words = _words([(10.0, 15.0, "SPEAKER_01"), (15.0, 20.0, "SPEAKER_00")])
    seg = [SEGS[0]]
    a = reframe.plan_shots_for_positions(seg, words, SRC_W, SRC_H, 1080, 1920, [480.0, 1440.0], {"SPEAKER_00": 0, "SPEAKER_01": 1})
    b = reframe.plan_shots_for_positions(seg, words, SRC_W, SRC_H, 1080, 1920, [480.0, 1440.0], {"SPEAKER_00": 1, "SPEAKER_01": 0})
    assert [s.crop_x for s in a] == [1440 - 303, 480 - 303]
    assert [s.crop_x for s in b] == [480 - 303, 1440 - 303]
    assert reframe.propose_speaker_positions(words, 2) == {"SPEAKER_01": 0, "SPEAKER_00": 1}
    assert reframe.propose_speaker_positions(words, 1) == {"SPEAKER_01": 0, "SPEAKER_00": 0}


def test_segment_shorter_than_min_shot_is_a_single_shot():
    seg = [{"start": 5.0, "end": 5.8, "role": "teaser"}]
    shots = reframe.plan_shots_for_positions(seg, _alternating(5.0, 5.8, 0.2), SRC_W, SRC_H, 1080, 1920, [480.0, 1440.0], {"SPEAKER_00": 0, "SPEAKER_01": 1})
    assert len(shots) == 1 and (shots[0].start, shots[0].end) == (5.0, 5.8)


def test_plan_reframe_without_detector_is_neutral_and_honest(monkeypatch, tmp_path):
    monkeypatch.setenv("YUNET_MODEL_PATH", str(tmp_path / "missing.onnx"))
    ok, reason = reframe.detector_available()
    assert ok is False and "YuNet-Modell fehlt" in reason
    res = reframe.plan_reframe(None, SEGS, _alternating(10, 36, 0.5), None, "4:5", src_w=SRC_W, src_h=SRC_H)
    assert res.strategy == "neutral" and res.detector == "none" and res.faces_detected is False
    assert res.positions == [] and res.plan_block() == {"strategy": "neutral", "detector": "none", "faces_detected": False, "positions": [], "min_shot_s": 1.2}
    assert (res.out_w, res.out_h) == (1080, 1350) and res.shots[0].crop_w == 864
    assert any("neutral" in n for n in res.notes)
    assert res.shots_json()[0]["layout"] == "single"
    with pytest.raises(ValueError):
        reframe.plan_reframe(None, SEGS, [], None, "9:16")


def test_detector_reports_missing_opencv_when_model_exists(monkeypatch, tmp_path):
    model = tmp_path / "yunet.onnx"
    model.write_bytes(b"x")
    monkeypatch.setenv("YUNET_MODEL_PATH", str(model))
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    ok, reason = reframe.detector_available()
    assert ok is False and "OpenCV" in reason
