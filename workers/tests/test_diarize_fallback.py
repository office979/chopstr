"""Diarisierung ohne HF_TOKEN oder ohne pyannote: Fallback auf einen Sprecher statt Fehler."""

from __future__ import annotations

import importlib.util
import wave

import numpy as np

from chopstr_worker import config
from chopstr_worker.activities import nlp as act_nlp
from chopstr_worker.activities import transcribe as act_asr
from chopstr_worker.activities.transcribe import asr_key_for, diar_key_for
from chopstr_worker.pipeline import transcribe as asr


def _wav(path, seconds: float = 2.0, sr: int = 16000):
    t = np.arange(int(seconds * sr)) / sr
    x = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(x.tobytes())
    return path


def test_pipeline_fallback_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    s = config.reload()
    assert asr.diarization_availability(s) == (False, asr.HINT_DIARIZATION_SKIPPED)
    assert asr.diarizer_id(s) == asr.DIARIZER_NONE
    out = asr.diarize(str(_wav(tmp_path / "a.wav", 2.0)), min_speakers=2, max_speakers=2, s=s)
    assert out["skipped"] is True and out["hint"] == asr.HINT_DIARIZATION_SKIPPED
    assert out["turns"] == [[0.0, 2.0, "SPEAKER_00"]] and out["speakers"] == ["SPEAKER_00"]
    assert out["model_id"] == asr.DIARIZER_NONE and out["compute_seconds"] == 0.0


def test_pipeline_fallback_without_pyannote(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    s = config.reload()
    available, hint = asr.diarization_availability(s)
    if importlib.util.find_spec("pyannote") is None:
        assert (available, hint) == (False, asr.HINT_PYANNOTE_MISSING)
        assert asr.diarizer_id(s) == asr.DIARIZER_NONE
    else:  # pragma: no cover - nur mit installiertem pyannote
        assert available and hint is None
        assert asr.diarizer_id(s) == (s.diarizer_model or asr._DEFAULT_DIARIZER)


def test_model_hint_only_for_generic_whisper():
    assert asr.model_hint("cstr/whisper-large-v3-turbo-german-int8_float32") is None
    assert asr.model_hint("deepdml/faster-whisper-large-v3-turbo-ct2") == asr.HINT_GENERIC_WHISPER


def test_activity_fallback_events_and_fusion(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("ASR_MODEL_DE", "dummy/model")
    fake_context.settings = config.reload()
    ws = fake_db.add_workspace()
    audio_key = "audio/test.wav"
    fake_context.store.put_file("derived", audio_key, _wav(tmp_path / "a.wav", 3.0))
    sid = fake_db.add_source(ws, "uploads/x.mp4", audio_key=audio_key, expected_speakers=2, duration_s=3.0)

    key = act_asr.run_diarize(fake_context, sid)
    assert key == diar_key_for(audio_key, 2, asr.DIARIZER_NONE)
    ev = fake_db.events_for("diarize")[-1]
    assert ev["status"] == "finished"
    assert ev["message"].startswith(asr.HINT_DIARIZATION_SKIPPED)
    assert "Quelle erwartet 2 Sprecher, alle Wörter werden SPEAKER_00 zugeordnet" in ev["message"]
    assert ev["payload"]["diarization"] == "skipped" and ev["payload"]["hints"][0] == asr.HINT_DIARIZATION_SKIPPED
    assert not [c for c in fake_db.job_costs if c.get("job_type") == "diarize"]  # keine Rechenzeit gebucht
    assert fake_db.sources[sid]["status"] != "failed"

    words = [
        {"text": "Wir", "start": 0.0, "end": 0.3, "prob": 0.9},
        {"text": "haben.", "start": 0.4, "end": 0.8, "prob": 0.9},
        {"text": "Genau.", "start": 2.5, "end": 2.9, "prob": 0.9},
    ]
    akey = asr_key_for(audio_key, "de", [], "dummy/model", fake_context.settings)
    fake_context.store.put_json("derived", akey, {"words": words, "model_id": "dummy/model", "variant": "de"})
    act_nlp.run(fake_context, sid)
    tv = fake_db.transcript_versions[-1]
    assert tv["stats"]["diarization"] == "skipped"
    assert tv["stats"]["speakers"] == ["SPEAKER_00"]
    assert all(w["speaker"] == "SPEAKER_00" for w in tv["words"])
    assert tv["diarizer_id"] == asr.DIARIZER_NONE


def test_activity_single_speaker_has_only_one_hint(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    fake_context.settings = config.reload()
    ws = fake_db.add_workspace()
    fake_context.store.put_file("derived", "audio/one.wav", _wav(tmp_path / "b.wav", 1.0))
    sid = fake_db.add_source(ws, "uploads/y.mp4", audio_key="audio/one.wav", expected_speakers=1)
    act_asr.run_diarize(fake_context, sid)
    ev = fake_db.events_for("diarize")[-1]
    assert ev["message"] == asr.HINT_DIARIZATION_SKIPPED and ev["payload"]["hints"] == [asr.HINT_DIARIZATION_SKIPPED]
