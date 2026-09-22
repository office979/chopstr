"""Rendering (Phase 3, ffmpeg). Ein Aufruf pro Clip:
Shots trimmen und croppen, concat, skalieren 1080x1920, ASS einbrennen, Loudnorm.

Loudness-Master-Entscheidung: Default -16 LUFS / -1,5 dBTP (Preset ``master``).
Preset ``legacy_social``: -14 LUFS / -1 dBTP für Plattformen, die lauter normalisieren.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .reframe import Shot

OUT_W, OUT_H = 1080, 1920
TITLE_CARD_S = 2.5


@dataclass(frozen=True)
class Loudness:
    i_lufs: float
    tp_dbtp: float
    lra: float = 11.0

    def filter(self) -> str:
        return f"loudnorm=I={self.i_lufs}:TP={self.tp_dbtp}:LRA={self.lra}"


LOUDNESS_PRESETS = {
    "master": Loudness(-16.0, -1.5),
    "legacy_social": Loudness(-14.0, -1.0),
}


def build_filter(shots: list[Shot], ass_path: str | None, title_card: str | None, loudness: str = "master", font_file: str = "fonts/Inter-Bold.ttf") -> str:
    """filter_complex als String (getrennt testbar)."""
    parts, labels = [], []
    for i, s in enumerate(shots):
        parts.append(
            f"[0:v]trim=start={s.start:.3f}:end={s.end:.3f},setpts=PTS-STARTPTS,"
            f"crop={s.crop_w}:{s.crop_h}:{s.crop_x}:0,scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[v{i}];"
            f"[0:a]atrim=start={s.start:.3f}:end={s.end:.3f},asetpts=PTS-STARTPTS[a{i}];"
        )
        labels.append(f"[v{i}][a{i}]")
    n = len(shots)
    filt = "".join(parts) + "".join(labels) + f"concat=n={n}:v=1:a=1[vc][ac];"
    vchain = "[vc]"
    if ass_path:
        ass_escaped = ass_path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        vchain += f"subtitles='{ass_escaped}'"
    if title_card:
        safe = title_card.replace("\\", "").replace("'", "’").replace(":", r"\:")
        draw = (
            f"drawtext=text='{safe}':fontfile={font_file}:fontsize=56:fontcolor=white:"
            f"box=1:boxcolor=black@0.6:boxborderw=24:x=(w-text_w)/2:y=260:enable='lt(t,{TITLE_CARD_S})'"
        )
        vchain += ("," if ass_path else "") + draw
    if vchain == "[vc]":
        vchain += "null"
    loud = LOUDNESS_PRESETS.get(loudness, LOUDNESS_PRESETS["master"])
    return filt + vchain + f"[vout];[ac]{loud.filter()}[aout]"


def render_clip(
    src: str,
    shots: list[Shot],
    ass_path: str | None,
    out_path: str,
    title_card: str | None = None,
    loudness: str = "master",
    crf: int = 19,
) -> str:
    filt = build_filter(shots, ass_path, title_card, loudness)
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error", "-i", src, "-filter_complex", filt,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path,
    ]  # fmt: skip
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"Rendern fehlgeschlagen: {' | '.join(tail)}") from exc
    return out_path


def ensure_dir(p: str) -> str:
    Path(p).mkdir(parents=True, exist_ok=True)
    return p


__all__ = ["LOUDNESS_PRESETS", "OUT_H", "OUT_W", "TITLE_CARD_S", "Loudness", "build_filter", "ensure_dir", "render_clip"]
