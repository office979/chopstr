from __future__ import annotations

import pytest

from chopstr_worker import config
from chopstr_worker.pipeline import transcribe


def _w(text, start, end, prob=0.9):
    return {"text": text, "start": start, "end": end, "prob": prob, "speaker": None}


def test_plan_windows():
    assert transcribe.plan_windows(100, 600, 20) == [(0.0, 100.0)]
    wins = transcribe.plan_windows(1500, 600, 20)
    assert wins[0] == (0.0, 600.0)
    assert wins[1] == (580.0, 1180.0)
    assert wins[-1][1] == 1500.0
    for (_, e1), (s2, _) in zip(wins, wins[1:]):
        assert e1 - s2 == pytest.approx(20.0)
    with pytest.raises(ValueError):
        transcribe.plan_windows(100, 10, 20)


def test_merge_windows_removes_duplicates_at_seam():
    # Fenster A: 0..30, Fenster B: 20..50, Überlappung 20..30, längste Pause bei 24.5..25.8
    a = [_w("eins", 1, 2), _w("zwei", 21, 22), _w("drei", 23, 24.5), _w("vier", 25.8, 26.5), _w("fünf", 27, 28)]
    b = [_w("drei", 23.1, 24.4), _w("vier", 25.9, 26.4), _w("fünf", 27.1, 28.1), _w("sechs", 40, 41)]
    merged = transcribe.merge_windows([(0, 30, a), (20, 50, b)])
    assert [w["text"] for w in merged] == ["eins", "zwei", "drei", "vier", "fünf", "sechs"]
    # Wörter vor dem Schnitt (Mitte der längsten Pause) stammen aus A, danach aus B
    assert merged[2]["start"] == 23
    assert merged[3]["start"] == 25.9


def test_merge_windows_no_overlap_and_single():
    a = [_w("a", 0, 1)]
    b = [_w("b", 5, 6)]
    assert [w["text"] for w in transcribe.merge_windows([(0, 3, a), (3, 8, b)])] == ["a", "b"]
    assert transcribe.merge_windows([(0, 3, a)]) == a
    assert transcribe.merge_windows([]) == []


def test_merge_is_deterministic_regardless_of_order():
    a = [_w("x", 1, 2), _w("y", 21, 22)]
    b = [_w("y", 21.05, 22.05), _w("z", 35, 36)]
    m1 = transcribe.merge_windows([(0, 30, a), (20, 50, b)])
    m2 = transcribe.merge_windows([(20, 50, b), (0, 30, a)])
    assert m1 == m2
    assert [w["text"] for w in m1] == ["x", "y", "z"]


def test_assign_speakers_majority_over_word_duration():
    turns = [(0.0, 1.0, "SPEAKER_00"), (1.0, 3.0, "SPEAKER_01")]
    words = [_w("a", 0.0, 0.5), _w("b", 0.8, 1.6), _w("c", 0.95, 1.1), _w("d", 5.0, 5.2)]
    transcribe.assign_speakers(words, turns)
    assert words[0]["speaker"] == "SPEAKER_00"
    assert words[1]["speaker"] == "SPEAKER_01"  # 0.6 s bei 01 gegen 0.2 s bei 00 (Mittelpunkt läge bei 1.2)
    assert words[2]["speaker"] == "SPEAKER_01"
    assert words[3]["speaker"] == "SPEAKER_01"  # ohne Überlappung: nächster Turn


def test_assign_speakers_midpoint_would_be_wrong():
    # Wort 0.4..1.4: Mittelpunkt 0.9 liegt in SPEAKER_00, aber die Mehrheit (0.6 s) liegt bei SPEAKER_01
    turns = [(0.0, 0.8, "SPEAKER_00"), (0.8, 3.0, "SPEAKER_01")]
    words = [_w("x", 0.4, 1.4)]
    transcribe.assign_speakers(words, turns)
    assert words[0]["speaker"] == "SPEAKER_01"


def test_assign_speakers_without_turns_keeps_none():
    words = [_w("x", 0, 1)]
    transcribe.assign_speakers(words, [])
    assert words[0]["speaker"] is None


def test_apply_brand_vocab_and_normalize_numbers():
    words = [_w("chopster,", 0, 1), _w("Chop-Str", 1, 2), _w("2.4", 2, 3), _w("Prozent", 3, 4)]
    transcribe.apply_brand_vocab(words, ["chopstr"])
    assert words[0]["text"] == "chopstr,"
    assert words[1]["text"] == "chopstr"
    transcribe.normalize_numbers(words)
    assert words[2]["text"] == "2,4"
    assert words[2]["start"] == 2


def test_confidence_stats():
    words = [_w("a", 0, 1, 0.9), _w("b", 1, 2, 0.3), _w("c", 2, 3, 0.4)]
    words[0]["speaker"] = "S1"
    st = transcribe.confidence_stats(words)
    assert st["word_count"] == 3
    assert st["low_conf_count"] == 2
    assert st["low_conf_ratio"] == pytest.approx(2 / 3, abs=1e-3)
    assert st["speakers"] == ["S1"]
    assert transcribe.confidence_stats([])["word_count"] == 0


def test_transcribe_without_model_raises_clear_error(tmp_path):
    with pytest.raises(transcribe.TranscribeError, match="ASR_MODEL_DE"):
        transcribe.transcribe(str(tmp_path / "x.wav"), variant="de", s=config.settings())
    with pytest.raises(transcribe.TranscribeError, match="ASR_MODEL_CH"):
        transcribe.transcribe(str(tmp_path / "x.wav"), variant="de-CH", s=config.settings())
    with pytest.raises(transcribe.TranscribeError, match="Variante"):
        transcribe.transcribe(str(tmp_path / "x.wav"), variant="fr", s=config.settings())


def test_gladia_fallback_requires_base_url(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIA_BASE_URL", raising=False)
    config.reload()
    with pytest.raises(transcribe.TranscribeError, match="GLADIA_BASE_URL"):
        transcribe.transcribe(str(tmp_path / "x.wav"), fallback="gladia-eu", s=config.settings())


def test_gladia_fallback_blocked_by_residency(tmp_path, monkeypatch):
    from chopstr_worker.residency import ResidencyError

    monkeypatch.setenv("GLADIA_BASE_URL", "https://api.gladia.io")
    monkeypatch.setenv("GLADIA_API_KEY", "x")
    monkeypatch.setenv("EGRESS_ALLOWLIST", "")
    config.reload()
    # gladia_base_url ist automatisch auf der Allowlist, sobald gesetzt; ein anderer Host nicht
    s = config.settings()
    assert "api.gladia.io" in __import__("chopstr_worker.residency", fromlist=["allowed_hosts"]).allowed_hosts(s)
    s2 = config.Settings(gladia_base_url="https://api.gladia.io", egress_allowlist=[])
    s2 = config.Settings(**{**s2.__dict__, "gladia_base_url": ""})
    with pytest.raises(transcribe.TranscribeError):
        transcribe.transcribe(str(tmp_path / "x.wav"), fallback="gladia-eu", s=s2)
    # Host, der nicht aus der Konfiguration stammt
    from chopstr_worker import residency

    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://api.openai.com/v1", s)
