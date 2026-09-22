from __future__ import annotations

import pytest

from chopstr_worker import ingest
from tests.conftest import make_test_video, requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return make_test_video(tmp_path_factory.mktemp("vid") / "test.mp4", seconds=3.0)


def test_probe_returns_real_values(video):
    info = ingest.probe(video)
    assert 2.5 <= info.duration_s <= 3.6
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(25.0)
    assert info.codec == "h264"
    assert info.has_audio and info.has_video
    assert info.size_bytes > 0
    assert info.to_dict()["fps"] == info.fps


def test_sha256_streaming(video, tmp_path):
    import hashlib

    assert ingest.sha256_file(video) == hashlib.sha256(video.read_bytes()).hexdigest()


def test_extract_audio_16k_mono(video, tmp_path):
    import wave

    wav = ingest.extract_audio(video, tmp_path / "a.wav")
    with wave.open(wav, "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
    assert 2.5 <= ingest.wav_duration_s(wav) <= 3.6


def test_make_proxy_720p_keeps_aspect(video, tmp_path):
    out = ingest.make_proxy(video, tmp_path / "p.mp4")
    info = ingest.probe(out)
    assert info.height <= 720
    assert info.width == 640 and info.height == 360  # kleiner als 720p: nicht hochskalieren
    assert info.codec == "h264" and info.audio_codec == "aac"


def test_probe_missing_file_raises(tmp_path):
    with pytest.raises(ingest.IngestError, match="nicht gefunden"):
        ingest.probe(tmp_path / "nope.mp4")


def test_extract_audio_without_audio_track_raises(tmp_path):
    import subprocess

    silent = tmp_path / "noaudio.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)],
        check=True, capture_output=True,
    )  # fmt: skip
    assert ingest.probe(silent).has_audio is False
    with pytest.raises(ingest.IngestError):
        ingest.extract_audio(silent, tmp_path / "x.wav")
