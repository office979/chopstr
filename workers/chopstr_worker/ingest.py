"""Ingest: ffprobe, sha256, 16-kHz-Mono-WAV, 720p-Proxy. Alles über ffmpeg/ffprobe per subprocess.

Das Original wird nie verändert. Alle Funktionen sind reine Datei-Operationen; die
Idempotenz über ``storage.exists`` liegt in ``activities.ingest``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

AUDIO_SAMPLE_RATE = 16000
PROXY_HEIGHT = 720
PROXY_CRF = 23
PROXY_AUDIO_BITRATE = "128k"

# Versionen fließen in die Output-Keys: Änderung an Parametern = neue Ableitungen
AUDIO_PARAMS = {"ar": AUDIO_SAMPLE_RATE, "ac": 1, "codec": "pcm_s16le"}
PROXY_PARAMS = {"height": PROXY_HEIGHT, "crf": PROXY_CRF, "vcodec": "libx264", "acodec": "aac", "ab": PROXY_AUDIO_BITRATE}
INGEST_VERSION = "ingest_v1"


class IngestError(RuntimeError):
    pass


@dataclass
class ProbeResult:
    duration_s: float
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    audio_codec: str | None
    has_audio: bool
    has_video: bool
    size_bytes: int
    format_name: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise IngestError(f"{cmd[0]} ist nicht installiert") from exc
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "").strip().splitlines()[-3:]
        raise IngestError(f"{what} fehlgeschlagen: {' | '.join(tail) or exc}") from exc


def _parse_rate(raw: str | None) -> float | None:
    if not raw or raw in {"0/0", "N/A"}:
        return None
    try:
        return round(float(Fraction(raw)), 3)
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str | os.PathLike) -> ProbeResult:
    """ffprobe als JSON: Dauer, Auflösung, fps, Codecs."""
    p = Path(path)
    if not p.is_file():
        raise IngestError(f"Datei nicht gefunden: {p.name}")
    r = _run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
        "ffprobe",
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise IngestError("ffprobe lieferte kein JSON") from exc
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) != 1), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = fmt.get("duration")
    if duration is None and video is not None:
        duration = video.get("duration")
    if duration is None and audio is not None:
        duration = audio.get("duration")
    try:
        duration_s = float(duration) if duration is not None else 0.0
    except ValueError:
        duration_s = 0.0

    fps = None
    if video is not None:
        fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    return ProbeResult(
        duration_s=round(duration_s, 3),
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=fps,
        codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        has_video=video is not None,
        size_bytes=int(fmt.get("size") or p.stat().st_size),
        format_name=fmt.get("format_name"),
    )


def sha256_file(path: str | os.PathLike, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Streaming-Hash, damit auch 5-GB-Dateien ohne RAM-Spitze laufen."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_audio(src: str | os.PathLike, out_wav: str | os.PathLike) -> str:
    """16 kHz Mono PCM-WAV für ASR und Diarisierung."""
    out = Path(out_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
            "-ar", str(AUDIO_SAMPLE_RATE), "-c:a", "pcm_s16le", str(out),
        ],  # fmt: skip
        "Audio-Extraktion",
    )
    if not out.is_file() or out.stat().st_size < 100:
        raise IngestError("Audio-Extraktion lieferte keine Daten (hat die Quelle eine Tonspur?)")
    return str(out)


def make_proxy(src: str | os.PathLike, out_mp4: str | os.PathLike, height: int = PROXY_HEIGHT) -> str:
    """720p-Proxy: libx264 crf 23, +faststart, AAC 128k. Breite gerade, Seitenverhältnis bleibt."""
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale=-2:'min({height},ih)'"
    _run(
        [
            "ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(src),
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(PROXY_CRF), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", PROXY_AUDIO_BITRATE, "-movflags", "+faststart", str(out),
        ],  # fmt: skip
        "Proxy-Erstellung",
    )
    if not out.is_file():
        raise IngestError("Proxy wurde nicht geschrieben")
    return str(out)


def wav_duration_s(path: str | os.PathLike) -> float:
    """Dauer einer PCM-WAV über den Header (ohne ffprobe)."""
    import wave

    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or AUDIO_SAMPLE_RATE)


__all__ = [
    "AUDIO_PARAMS",
    "INGEST_VERSION",
    "PROXY_PARAMS",
    "IngestError",
    "ProbeResult",
    "extract_audio",
    "ffmpeg_available",
    "make_proxy",
    "probe",
    "sha256_file",
    "wav_duration_s",
]
