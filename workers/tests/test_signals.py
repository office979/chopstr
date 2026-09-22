from __future__ import annotations

import wave

import numpy as np

from chopstr_worker.pipeline import signals


def _write_wav(path, seconds=6, sr=16000):
    t = np.arange(int(seconds * sr)) / sr
    x = 0.05 * np.sin(2 * np.pi * 220 * t)
    x[sr * 3 : sr * 4] *= 8  # lauter Abschnitt in Sekunde 3
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def test_audio_heatmap_marks_loud_second(tmp_path):
    wav = _write_wav(tmp_path / "a.wav")
    heat = signals.audio_heatmap(str(wav))
    assert len(heat) == 6
    assert int(np.argmax(heat)) == 3


def test_text_heatmap_markers_questions_numbers():
    words = [
        {"text": "Der", "start": 10.0, "end": 10.2},
        {"text": "Punkt", "start": 10.3, "end": 10.5},
        {"text": "ist", "start": 10.6, "end": 10.8},
        {"text": "wirklich?", "start": 30.0, "end": 30.4},
        {"text": "40.000", "start": 50.0, "end": 50.4},
    ]
    h = signals.text_heatmap(words, 60)
    assert h[10] >= 1.0  # Diskursmarker „der punkt ist"
    assert h[30] >= 0.5
    assert h[50] >= 0.5
    assert h[5] == 0.0
    assert signals.text_heatmap([], 5).shape == (5,)


def test_seeds_respect_min_gap():
    heat = np.zeros(200, dtype=np.float32)
    heat[[10, 12, 100, 150]] = [5, 4, 3, 2]
    s = signals.seeds(heat, top_k=10, min_gap_s=45)
    assert 10 in s and 12 not in s and 100 in s and 150 in s


def test_combined_and_payload(tmp_path):
    wav = _write_wav(tmp_path / "b.wav")
    words = [{"text": "Zum", "start": 1.0, "end": 1.2}, {"text": "Beispiel", "start": 1.3, "end": 1.6}]
    heat = signals.combined(str(wav), words)
    payload = signals.to_payload(heat)
    assert payload["n_bins"] == 6
    assert len(payload["values"]) == 6
    assert isinstance(payload["seeds"], list)
