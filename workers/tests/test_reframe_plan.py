"""Reframe-Planung ohne Video: Strategien, lückenlose Shots, Mindestlänge, Augen-Drittel, neutral ohne Detektor."""

from __future__ import annotations

import pytest

from chopstr_worker.pipeline import reframe, tracking

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


# -- Shots aus gemessenen Zielen -------------------------------------------------------------------

def _ziel(a, b, cx, anker=0.5, cy=300.0):
    return tracking.Ziel(start_s=a, ende_s=b, cx=cx, cy=cy, anker=anker, grund="sprecher")


def test_shots_aus_zielen_decken_das_segment_lueckenlos_ab():
    zl = [[_ziel(10.0, 14.0, 500.0), _ziel(14.0, 20.0, 1400.0)], [_ziel(30.0, 36.0, 500.0)]]
    shots = reframe.plan_shots_aus_zielen(SEGS, zl, SRC_W, SRC_H, 1080, 1920)
    assert [(s.start, s.end) for s in shots] == [(10.0, 14.0), (14.0, 20.0), (30.0, 36.0)]
    for seg in SEGS:
        teil = [s for s in shots if s.start >= seg["start"] - 1e-9 and s.end <= seg["end"] + 1e-9]
        assert teil[0].start == pytest.approx(seg["start"]) and teil[-1].end == pytest.approx(seg["end"])
        for vor, nach in zip(teil, teil[1:]):
            assert vor.end == pytest.approx(nach.start)


def test_ziele_ausserhalb_des_segments_werden_zurechtgeschoben():
    """Gemessen wird an Abtastpunkten, die selten genau auf der Segmentgrenze liegen."""
    zl = [[_ziel(9.5, 13.0, 500.0), _ziel(13.0, 25.0, 1400.0)], [_ziel(30.0, 36.0, 500.0)]]
    shots = reframe.plan_shots_aus_zielen(SEGS, zl, SRC_W, SRC_H, 1080, 1920)
    erste = [s for s in shots if s.start < 25]
    assert erste[0].start == pytest.approx(10.0)
    assert erste[-1].end == pytest.approx(20.0)


def test_drittelregel_setzt_das_gesicht_aus_der_mitte():
    """Wer links sitzt, gehoert auf das linke Drittel, damit rechts Blickraum bleibt."""
    mitte = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel(10.0, 20.0, 960.0, anker=0.5)]], SRC_W, SRC_H, 1080, 1920)[0]
    links = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel(10.0, 20.0, 700.0, anker=1 / 3)]], SRC_W, SRC_H, 1080, 1920)[0]
    rechts = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel(10.0, 20.0, 1300.0, anker=2 / 3)]], SRC_W, SRC_H, 1080, 1920)[0]
    assert (960 - mitte.crop_x) / mitte.crop_w == pytest.approx(0.5, abs=0.01)
    assert (700 - links.crop_x) / links.crop_w == pytest.approx(1 / 3, abs=0.01)
    assert (1300 - rechts.crop_x) / rechts.crop_w == pytest.approx(2 / 3, abs=0.01)


def test_ohne_ziel_bleibt_der_ausschnitt_mittig():
    shots = reframe.plan_shots_aus_zielen(SEGS[:1], [[]], SRC_W, SRC_H, 1080, 1920)
    assert len(shots) == 1
    assert shots[0].crop_x == (SRC_W - shots[0].crop_w) // 2


def test_ausschnitt_bleibt_immer_im_quellbild():
    """Am Bildrand darf der Anker den Ausschnitt nicht herausschieben."""
    for cx, anker in ((60.0, 2 / 3), (1880.0, 1 / 3), (30.0, 1 / 3), (1900.0, 2 / 3)):
        s = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel(10.0, 20.0, cx, anker=anker)]], SRC_W, SRC_H, 1080, 1920)[0]
        assert s.crop_x >= 0 and s.crop_x + s.crop_w <= SRC_W
        assert s.crop_y >= 0 and s.crop_y + s.crop_h <= SRC_H


def test_gleicher_ausschnitt_wird_nicht_zweimal_geplant():
    """Ein Schnitt zwischen zwei gleich gerahmten Naheinstellungen ergibt denselben Ausschnitt."""
    zl = [[_ziel(10.0, 14.0, 500.0), _ziel(14.0, 17.0, 503.0), _ziel(17.0, 20.0, 1400.0)]]
    shots = reframe.plan_shots_aus_zielen(SEGS[:1], zl, SRC_W, SRC_H, 1080, 1920)
    assert [(s.start, s.end) for s in shots] == [(10.0, 17.0), (17.0, 20.0)]


def test_gleicher_ausschnitt_wird_nicht_ueber_segmentgrenzen_zusammengezogen():
    zl = [[_ziel(10.0, 20.0, 500.0)], [_ziel(30.0, 36.0, 500.0)]]
    shots = reframe.plan_shots_aus_zielen(SEGS, zl, SRC_W, SRC_H, 1080, 1920)
    assert [(s.start, s.end) for s in shots] == [(10.0, 20.0), (30.0, 36.0)]


# -- Zoom: naeher heran heisst enger schneiden -----------------------------------------------------
def _ziel_zoom(a, b, cx, zoom, anker=0.5):
    return tracking.Ziel(start_s=a, ende_s=b, cx=cx, cy=300.0, anker=anker, grund="sprecher", zoom=zoom)


def test_ohne_zoom_bleibt_der_ausschnitt_voll():
    s = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel_zoom(10.0, 20.0, 960.0, 1.0)]], SRC_W, SRC_H, 1080, 1920)[0]
    voll = reframe.crop_geometry(SRC_W, SRC_H, 1080, 1920)
    assert (s.crop_w, s.crop_h) == voll
    assert s.zoom == 1.0


def test_zoom_verkleinert_den_ausschnitt_um_denselben_faktor():
    voll_w, voll_h = reframe.crop_geometry(SRC_W, SRC_H, 1080, 1920)
    s = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel_zoom(10.0, 20.0, 960.0, 1.4)]], SRC_W, SRC_H, 1080, 1920)[0]
    assert s.crop_w == pytest.approx(voll_w / 1.4, abs=2)
    assert s.crop_h == pytest.approx(voll_h / 1.4, abs=2)


def test_zoom_haelt_das_seitenverhaeltnis():
    """Sonst waere das Bild verzerrt, und das faellt sofort auf."""
    voll_w, voll_h = reframe.crop_geometry(SRC_W, SRC_H, 1080, 1920)
    s = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel_zoom(10.0, 20.0, 960.0, 1.6)]], SRC_W, SRC_H, 1080, 1920)[0]
    assert s.crop_w / s.crop_h == pytest.approx(voll_w / voll_h, abs=0.01)


def test_der_zoom_bleibt_im_quellbild():
    for cx in (60.0, 960.0, 1880.0):
        s = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel_zoom(10.0, 20.0, cx, 1.6)]], SRC_W, SRC_H, 1080, 1920)[0]
        assert s.crop_x >= 0 and s.crop_x + s.crop_w <= SRC_W
        assert s.crop_y >= 0 and s.crop_y + s.crop_h <= SRC_H


def test_ein_zoomwechsel_trennt_die_abschnitte():
    """Gleiche Bildstelle, andere Naehe: das muessen zwei Abschnitte bleiben."""
    zl = [[_ziel_zoom(10.0, 15.0, 960.0, 1.0), _ziel_zoom(15.0, 20.0, 960.0, 1.4)]]
    shots = reframe.plan_shots_aus_zielen(SEGS[:1], zl, SRC_W, SRC_H, 1080, 1920)
    assert len(shots) == 2
    assert shots[0].crop_w > shots[1].crop_w


# -- Geteiltes Bild --------------------------------------------------------------------------------
def _ziel_geteilt(cx, auswahl, breite=300.0):
    return tracking.Ziel(
        start_s=10.0, ende_s=20.0, cx=cx, cy=800.0, anker=0.5, grund="von_hand",
        breite=breite, auswahl=list(auswahl), layout="geteilt",
    )  # fmt: skip


def test_geteilt_liefert_zwei_gleich_grosse_ausschnitte():
    zwei = reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, _ziel_geteilt(1306.0, [1306.0, 2582.0]))
    assert len(zwei) == 2
    assert {(t["w"], t["h"]) for t in zwei} == {(zwei[0]["w"], zwei[0]["h"])}, "beide Haelften gleich gross"


def test_eine_haelfte_hat_das_verhaeltnis_der_halben_ausgabe():
    """Sonst waere das Bild in der Haelfte verzerrt."""
    zwei = reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, _ziel_geteilt(1306.0, [1306.0, 2582.0]))
    soll = 1080 / (1920 / 2)
    assert zwei[0]["w"] / zwei[0]["h"] == pytest.approx(soll, abs=0.02)


def test_die_haelften_richten_sich_nach_der_gesichtsgroesse():
    """Wer vom Quellbild ausgeht, schneidet bei 4K zwei Drittel der Breite heraus, und dann sitzen
    zwei kleine Koepfe in viel Tisch."""
    klein = reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, _ziel_geteilt(1306.0, [1306.0, 2582.0], breite=200.0))
    gross = reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, _ziel_geteilt(1306.0, [1306.0, 2582.0], breite=500.0))
    assert klein[0]["h"] < gross[0]["h"]


def test_die_gewaehlte_person_ist_immer_dabei():
    """Sonst zeigte das geteilte Bild ausgerechnet nicht den, den jemand von Hand gewaehlt hat."""
    z = _ziel_geteilt(2582.0, [700.0, 1306.0, 2582.0, 3400.0])
    zwei = reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, z)
    mitten = [t["x"] + t["w"] / 2 for t in zwei]
    assert any(abs(m - 2582.0) < t["w"] / 2 for m, t in zip(mitten, zwei))


def test_die_ausschnitte_bleiben_im_quellbild():
    for cx, auswahl in ((100.0, [100.0, 3700.0]), (3700.0, [100.0, 3700.0])):
        zwei = reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, _ziel_geteilt(cx, auswahl))
        for t in zwei:
            assert t["x"] >= 0 and t["x"] + t["w"] <= 3840
            assert t["y"] >= 0 and t["y"] + t["h"] <= 2160


def test_ohne_zweite_person_gibt_es_kein_geteiltes_bild():
    assert reframe.geteilte_ausschnitte(3840, 2160, 1080, 1920, _ziel_geteilt(1306.0, [1306.0])) == []
    shots = reframe.plan_shots_aus_zielen(SEGS[:1], [[_ziel_geteilt(1306.0, [1306.0])]], 3840, 2160, 1080, 1920)
    assert shots[0].layout == "single"


def test_geteilt_landet_als_layout_im_shot():
    shots = reframe.plan_shots_aus_zielen(
        SEGS[:1], [[_ziel_geteilt(1306.0, [1306.0, 2582.0])]], 3840, 2160, 1080, 1920
    )  # fmt: skip
    assert shots[0].layout == "geteilt" and len(shots[0].geteilt) == 2
