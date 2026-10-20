"""Lane P1: Sprecherüberlappung (pyannote regulär plus exklusiv), Mehrspur über Spurenergie, Ingest mehrerer Spuren.

pyannote ist lokal nicht installiert; der pyannote-Pfad läuft mit einer Fake-Pipeline, die beide Ausgaben von
community-1 nachbildet (``speaker_diarization`` und ``exclusive_speaker_diarization``).
"""

from __future__ import annotations

import subprocess
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from chopstr_worker import config, ingest
from chopstr_worker.activities import ingest as act_ingest
from chopstr_worker.activities import nlp as act_nlp
from chopstr_worker.activities import transcribe as act_asr
from chopstr_worker.pipeline import transcribe as asr
from tests.conftest import FakeCursor, make_test_video, requires_ffmpeg

SR = 16000


def w(text, start, end):
    return {"text": text, "start": start, "end": end, "prob": 0.9}


# -- Überlappung je Wort -----------------------------------------------------------------------------


def test_overlap_marks_words_with_two_active_speakers():
    words = [w("Ja", 0.0, 0.4), w("aber", 1.0, 1.3), w("genau", 2.0, 2.4)]
    turns = [(0.0, 1.2, "A"), (1.2, 3.0, "B")]
    overlap = [(0.0, 1.5, "A"), (0.9, 3.0, "B")]
    asr.assign_speakers(words, turns, overlap, min_ratio=0.3)
    assert [x["speaker"] for x in words] == ["A", "A", "B"]  # Mehrheit aus der exklusiven Struktur bleibt
    assert [x["overlap"] for x in words] == [False, True, False]
    assert words[1]["speakers"] == ["A", "B"] and "speakers" not in words[0]
    assert asr.overlap_ratio(words) == pytest.approx(1 / 3, abs=1e-4)


def test_short_touch_of_a_second_speaker_is_no_overlap():
    words = [w("Kunden", 1.0, 2.0)]
    asr.assign_speakers(words, [(0.0, 3.0, "A")], [(0.0, 3.0, "A"), (1.9, 3.0, "B")], min_ratio=0.3)
    assert words[0]["overlap"] is False  # B deckt nur 10 % des Wortes ab


def test_without_overlap_turns_nothing_changes():
    words = [w("Ja", 0.0, 0.4)]
    asr.assign_speakers(words, [(0.0, 1.0, "A")])
    assert words[0] == {"text": "Ja", "start": 0.0, "end": 0.4, "prob": 0.9, "speaker": "A"}
    assert asr.overlap_ratio(words) is None


class _Seg:
    def __init__(self, a, b):
        self.start, self.end = a, b


class _Ann:
    def __init__(self, rows):
        self.rows = rows

    def itertracks(self, yield_label=True):
        for a, b, spk in self.rows:
            yield _Seg(a, b), "_", spk


def test_pyannote_path_keeps_the_overlap_capable_annotation(tmp_path, monkeypatch):
    out = SimpleNamespace(
        speaker_diarization=_Ann([(0.0, 2.0, "SPEAKER_00"), (1.5, 3.0, "SPEAKER_01")]),
        exclusive_speaker_diarization=_Ann([(0.0, 1.5, "SPEAKER_00"), (1.5, 3.0, "SPEAKER_01")]),
    )
    monkeypatch.setattr(asr, "diarization_availability", lambda s=None: (True, None))
    monkeypatch.setattr(asr, "load_diarizer", lambda s=None: lambda path, **kw: out)
    res = asr.diarize(str(tmp_path / "x.wav"), s=config.reload())
    assert res["turns"] == [[0.0, 1.5, "SPEAKER_00"], [1.5, 3.0, "SPEAKER_01"]]
    assert res["overlap_turns"] == [[0.0, 2.0, "SPEAKER_00"], [1.5, 3.0, "SPEAKER_01"]]


# -- Spurenergie ---------------------------------------------------------------------------------------


def _tone(seconds: float, amp: float, f: float = 200.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def _tracks():
    """A spricht 0 bis 1 s (B hört A 30 dB leiser mit), B spricht 1 bis 2 s, beide 2 bis 2,5 s, dann Stille."""
    loud, bleed, quiet = 0.3, 0.3 * 10 ** (-30 / 20), 0.0
    a = np.concatenate([_tone(1.0, loud), _tone(1.0, quiet), _tone(0.5, loud), _tone(0.5, quiet)])
    b = np.concatenate([_tone(1.0, bleed), _tone(1.0, loud, 300), _tone(0.5, loud * 0.8, 300), _tone(0.5, quiet)])
    return a, b


def test_energy_diarization_loudest_track_and_overlap():
    res = asr.energy_diarization(list(_tracks()), SR, window_s=0.1, overlap_db=10.0, silence_dbfs=-45.0)
    assert res["model_id"] == asr.DIARIZER_MULTITRACK and res["windows"] == 30
    assert res["turns"] == [[0.0, 1.0, "SPEAKER_00"], [1.0, 2.0, "SPEAKER_01"], [2.0, 2.5, "SPEAKER_00"]]
    assert res["overlap_windows"] == 5  # nur 2,0 bis 2,5 s; Übersprechen bei 30 dB zählt nicht
    assert res["overlap_turns"] == [[0.0, 1.0, "SPEAKER_00"], [1.0, 2.5, "SPEAKER_01"], [2.0, 2.5, "SPEAKER_00"]]
    assert not any(t[0] < 1.0 and t[2] == "SPEAKER_01" for t in res["overlap_turns"])
    words = [w("hallo", 0.2, 0.6), w("beide", 2.1, 2.4)]
    asr.assign_speakers(words, res["turns"], res["overlap_turns"], 0.3)
    assert words[0]["overlap"] is False and words[1]["overlap"] is True and words[1]["speakers"] == ["SPEAKER_00", "SPEAKER_01"]


def test_energy_diarization_is_deterministic_and_quiet_is_no_speaker():
    a, b = _tracks()
    one = asr.energy_diarization([a, b], SR)
    assert one == asr.energy_diarization([a, b], SR)
    silent = asr.energy_diarization([np.zeros(SR, dtype=np.float32), np.zeros(SR, dtype=np.float32)], SR)
    assert silent["turns"] == [] and silent["speakers"] == []
    assert asr.energy_diarization([], SR)["turns"] == []


def _write(path, x):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def test_multitrack_activity_and_fusion_without_pyannote(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("SPEAKERS_MULTITRACK", "1")
    fake_context.settings = config.reload()
    a, b = _tracks()
    fake_context.store.put_file("derived", "audio/mix.wav", _write(tmp_path / "mix.wav", (a + b) / 2))
    fake_context.store.put_file("derived", "audio/t0.wav", _write(tmp_path / "t0.wav", a))
    fake_context.store.put_file("derived", "audio/t1.wav", _write(tmp_path / "t1.wav", b))
    ws = fake_db.add_workspace()
    sid = fake_db.add_source(ws, "uploads/m.mp4", audio_key="audio/mix.wav", duration_s=3.0, audio_tracks=["audio/t0.wav", "audio/t1.wav"])
    execute = fake_db.execute

    def with_tracks(sql, params=None):
        if " ".join(sql.split()).lower().startswith("select audio_tracks from sources where id"):
            return FakeCursor([(fake_db.sources[params[0]].get("audio_tracks"),)])
        return execute(sql, params)

    monkeypatch.setattr(fake_db, "execute", with_tracks)
    key = act_asr.run_diarize(fake_context, sid)
    doc = fake_context.store.get_json("derived", key)
    assert doc["model_id"] == asr.DIARIZER_MULTITRACK and doc["tracks"] == 2 and doc["skipped"] is False
    ev = fake_db.events_for("diarize")[-1]
    assert ev["payload"]["diarization"] == "multitrack_energy" and ev["payload"]["speakers"] == 2

    words = [w("Ich", 0.2, 0.5), w("sage.", 1.2, 1.6), w("Beide.", 2.1, 2.4)]
    akey = act_asr.asr_key_for("audio/mix.wav", "de", [], "", fake_context.settings)
    fake_context.store.put_json("derived", akey, {"words": words, "model_id": "m", "variant": "de"})
    act_nlp.run(fake_context, sid)
    tv = fake_db.transcript_versions[-1]
    assert tv["diarizer_id"] == asr.DIARIZER_MULTITRACK and tv["stats"]["diarization"] == "multitrack_energy"
    assert [x["speaker"] for x in tv["words"]] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert tv["words"][2]["overlap"] is True and tv["stats"]["overlap_ratio"] == pytest.approx(0.3333, abs=1e-4)


def test_without_switch_no_track_query(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.delenv("SPEAKERS_MULTITRACK", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    fake_context.settings = config.reload()
    assert act_asr.audio_tracks(fake_context, "irrelevant") == []
    assert not [q for q, _p in fake_db.statements if "audio_tracks" in q]


# -- Ingest mehrerer Spuren ---------------------------------------------------------------------------


def _two_track_video(path, seconds=2.0, offset=None):
    cmd = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=660:sample_rate=48000:duration={seconds}",
           "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
           "-c:a", "aac", "-shortest", str(path)]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@requires_ffmpeg
def test_probe_lists_audio_streams_and_extracts_each(tmp_path):
    info = ingest.probe(_two_track_video(tmp_path / "two.mp4"))
    assert [s["index"] for s in info.audio_streams] == [0, 1]
    assert ingest.common_time_base(info.audio_streams)
    out = ingest.extract_track(tmp_path / "two.mp4", tmp_path / "t1.wav", 1)
    with wave.open(out, "rb") as wf:
        assert (wf.getframerate(), wf.getnchannels()) == (16000, 1)
    single = ingest.probe(make_test_video(tmp_path / "one.mp4", seconds=1.0))
    assert len(single.audio_streams) == 1


def test_common_time_base_tolerance():
    assert ingest.common_time_base([{"start_time": 0.0}, {"start_time": 0.05}])
    assert not ingest.common_time_base([{"start_time": 0.0}, {"start_time": 0.5}])
    assert ingest.common_time_base([{"start_time": None}, {"start_time": 0.0}])


@requires_ffmpeg
def test_ingest_activity_stores_tracks_only_with_switch(fake_db, fake_context, tmp_path, monkeypatch):
    fake_context.store.put_file("sources", "uploads/two.mp4", _two_track_video(tmp_path / "two.mp4"))
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/two.mp4")
    monkeypatch.delenv("SPEAKERS_MULTITRACK", raising=False)
    fake_context.settings = config.reload()
    act_ingest.run(fake_context, sid)
    assert "audio_tracks" not in fake_db.sources[sid]  # Standard: wie vor Lane P1

    monkeypatch.setenv("SPEAKERS_MULTITRACK", "1")
    fake_context.settings = config.reload()
    act_ingest.run(fake_context, sid)
    tracks = fake_db.sources[sid]["audio_tracks"]
    assert tracks == [act_ingest.track_key_for("uploads/two.mp4", 0), act_ingest.track_key_for("uploads/two.mp4", 1)]
    assert all(fake_context.store.exists("derived", k) for k in tracks)
    assert fake_db.events_for("probe_and_extract")[-1]["payload"]["audio_tracks"] == 2
