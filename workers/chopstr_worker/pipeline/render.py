"""Rendering (Phase 3, ffmpeg) aus einem ``render_plan_v1``.

Ein Encode-Durchgang pro Clip: pro Shot ein per ``-ss``/``-t`` gesuchter Input (schnell auch bei langen
Quellen), crop und scale auf die Ausgabegröße, concat; Audio pro Segment mit 20 ms Micro-Fades an den
Klebestellen; Untertitel per ``subtitles`` (libass, Fontdir); Titelkarte und Hook-Overlay per ``drawtext``;
Loudness zweistufig (Pass 1 misst ``loudnorm=print_format=json``, Pass 2 normalisiert linear mit den
Messwerten; bei LRA über ``COMPRESS_ABOVE_LRA`` kommt ``acompressor`` davor). Ausgabe H.264 High,
yuv420p, ``+faststart``, AAC 192k, Bildrate aus dem Plan.

Ehrlichkeit gegenüber der Umgebung: fehlt der ffmpeg-Build ``subtitles`` (libass) oder ``drawtext``
(libfreetype), wird der betroffene Schritt übersprungen und als Hinweis in ``RenderResult.notes``
gemeldet; der Render selbst läuft durch. Dasselbe gilt für eine fehlende Font-Datei.

Marke (Phase 4): ``font_path`` ersetzt Inter in ``drawtext`` (der ``Fontname`` in der ASS kommt aus
``write_captions(font_family=...)``, libass findet die Datei über ``fontsdir``). ``logo_path`` (PNG) wird bei
``plan.brand.watermark.enabled`` als Wasserzeichen unten rechts innerhalb der Safe Zone per ``overlay`` gelegt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import captions_de

log = logging.getLogger("chopstr.render")

TITLE_CARD_S = 2.5
COMPRESS_ABOVE_LRA = 7.0
LOUDNORM_LRA = 11.0
AUDIO_RATE = 48000
FONT_CANDIDATES = ("Inter-Bold.ttf", "Inter-Bold.otf")
SYSTEM_FONT_DIRS = ("/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter")
COMPRESSOR = "acompressor=threshold=0.125:ratio=2:attack=20:release=250:makeup=1"
BLACK_MIN_S = 0.5
DURATION_TOLERANCE_S = 0.3


@dataclass(frozen=True)
class Loudness:
    i_lufs: float
    tp_dbtp: float
    lra: float = LOUDNORM_LRA

    def filter(self) -> str:
        return f"loudnorm=I={self.i_lufs}:TP={self.tp_dbtp}:LRA={self.lra}"


LOUDNESS_PRESETS = {
    "master": Loudness(-16.0, -1.5),
    "legacy_social": Loudness(-14.0, -1.0),
}


@dataclass
class RenderResult:
    out_path: str
    expected_duration_s: float
    notes: list[str] = field(default_factory=list)
    measured: dict[str, float] = field(default_factory=dict)
    compressor: bool = False
    captions_burned: bool = False
    title_card_drawn: bool = False
    hook_overlay_drawn: bool = False
    watermark_drawn: bool = False
    filter_graph: str = ""


class RenderError(RuntimeError):
    pass


# -- Umgebung ------------------------------------------------------------------------------------
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@lru_cache(maxsize=1)
def ffmpeg_filters() -> frozenset[str]:
    """Namen aller Filter des installierten ffmpeg (leer, wenn ffmpeg fehlt)."""
    if shutil.which("ffmpeg") is None:
        return frozenset()
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False)
    except OSError:
        return frozenset()
    names = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and re.fullmatch(r"[.TSC]{2,3}", parts[0]) and "->" in parts[2]:
            names.add(parts[1])
    return frozenset(names)


def capabilities() -> dict[str, bool]:
    f = ffmpeg_filters()
    return {
        "subtitles": "subtitles" in f, "drawtext": "drawtext" in f, "loudnorm": "loudnorm" in f, "ebur128": "ebur128" in f,
        "overlay": "overlay" in f,
    }  # fmt: skip


def default_fonts_dir() -> Path:
    from .. import config

    env = (config.settings().render_fonts_dir or "").strip()
    return Path(env) if env else Path(__file__).resolve().parents[2] / "fonts"


def font_file(fonts_dir: str | os.PathLike | None = None) -> Path | None:
    """Erste vorhandene Inter-Bold-Datei aus dem Fontordner oder den Systempfaden des Docker-Images."""
    dirs = [Path(fonts_dir)] if fonts_dir else [default_fonts_dir()]
    dirs += [Path(d) for d in SYSTEM_FONT_DIRS]
    for d in dirs:
        for name in FONT_CANDIDATES:
            p = d / name
            if p.is_file():
                return p
    return None


# -- Filtergraph --------------------------------------------------------------------------------
def _q(value: str) -> str:
    """Wert für den Filtergraph in einfache Anführungszeichen setzen (Doppelpunkt und Backslash escapen)."""
    v = str(value).replace("\\", "\\\\").replace(":", "\\:")
    return "'" + v + "'"


def _text(value: str) -> str:
    return _q(value.replace("'", "’").replace("\n", " "))


def _path(value: str | os.PathLike) -> str:
    p = str(Path(value).resolve()).replace("\\", "/")
    if "'" in p:
        raise RenderError("Pfade mit Apostroph werden nicht unterstützt")
    return _q(p)


def _drawtext_lines(lines: list[str], font: Path, font_px: int, y0: int, seconds: float) -> list[str]:
    line_h = int(round(font_px * 1.3))
    out = []
    for i, line in enumerate(lines):
        out.append(
            f"drawtext=fontfile={_path(font)}:text={_text(line)}:expansion=none:fontsize={font_px}:fontcolor=white:"
            f"box=1:boxcolor=black@0.6:boxborderw={max(8, font_px // 4)}:x=(w-text_w)/2:y={y0 + i * line_h}:"
            f"enable='lt(t,{seconds:.2f})'"
        )
    return out


def overlay_filters(plan: dict, font: Path | None, caps: dict[str, bool]) -> tuple[list[str], list[str], bool, bool]:
    """drawtext-Filter für Titelkarte und Hook-Overlay. Gibt (Filter, Hinweise, titel_gezeichnet, hook_gezeichnet)."""
    filters: list[str] = []
    notes: list[str] = []
    title = plan.get("title_card") or None
    hook = plan.get("hook_overlay") or None
    if not title and not hook:
        return [], [], False, False
    if not caps.get("drawtext"):
        notes.append("Titelkarte und Hook-Overlay nicht gezeichnet: ffmpeg ohne drawtext-Filter (libfreetype)")
        return [], notes, False, False
    if font is None:
        notes.append("Titelkarte und Hook-Overlay nicht gezeichnet: Font Inter-Bold fehlt (fonts/README.md)")
        return [], notes, False, False
    out_w, out_h = int(plan["output"]["width"]), int(plan["output"]["height"])
    safe = plan["captions"]["safe_zone"]
    margin_x = max(int(safe["left"]), int(safe["right"]), 40)
    y = int(safe["top"])
    title_drawn = hook_drawn = False
    if title:
        font_px = max(18, int(round(out_h * 0.031)))
        lines = captions_de.wrap_lines(str(title["text"]).split(), captions_de.max_chars(font_px, out_w - 2 * margin_x), 3)
        filters += _drawtext_lines(lines, font, font_px, y, float(title["seconds"]))
        y += int(round(font_px * 1.3)) * len(lines) + font_px
        title_drawn = True
    if hook:
        font_px = max(18, int(round(out_h * 0.036)))
        lines = captions_de.wrap_lines(str(hook["text"]).split(), captions_de.max_chars(font_px, out_w - 2 * margin_x), 3)
        filters += _drawtext_lines(lines, font, font_px, y, float(hook["seconds"]))
        hook_drawn = True
    return filters, notes, title_drawn, hook_drawn


def _inputs(plan: dict) -> tuple[list[dict], list[dict]]:
    shots = list(plan.get("shots") or [])
    segments = list(plan["segments"])
    if not shots:
        raise RenderError("Plan ohne Shots")
    return shots, segments


def input_args(src_path: str | os.PathLike, plan: dict) -> list[str]:
    """``-ss``/``-t``/``-i`` je Shot (Video) und je Segment (Audio), in dieser Reihenfolge."""
    shots, segments = _inputs(plan)
    args: list[str] = []
    for item in [*shots, *segments]:
        start, end = float(item["start"]), float(item["end"])
        args += ["-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.001):.3f}", "-i", str(src_path)]
    return args


def audio_chain(plan: dict, first_input: int, loud_filter: str, compressor: bool) -> str:
    """Audio: Segmente mit Micro-Fades, concat, optional Kompressor, Loudnorm, 48 kHz. Endet in ``[aout]``."""
    _, segments = _inputs(plan)
    fade = float(plan["audio"].get("micro_fade_ms", 20)) / 1000.0
    parts, labels = [], []
    for j, seg in enumerate(segments):
        dur = float(seg["end"]) - float(seg["start"])
        idx = first_input + j
        fade_out_at = max(dur - fade, 0.0)
        parts.append(
            f"[{idx}:a]asetpts=PTS-STARTPTS,afade=t=in:st=0:d={fade:.3f},afade=t=out:st={fade_out_at:.3f}:d={fade:.3f}[a{j}];"
        )
        labels.append(f"[a{j}]")
    chain = "".join(parts) + "".join(labels) + f"concat=n={len(segments)}:v=0:a=1[ac];"
    tail = (COMPRESSOR + "," if compressor else "") + loud_filter + f",aresample={AUDIO_RATE}"
    return chain + f"[ac]{tail}[aout]"


def watermark_filter(plan: dict, logo_index: int) -> str:
    """Logo als Wasserzeichen unten rechts innerhalb der Safe Zone: ``[vt]`` plus Logo-Input zu ``[vout]``."""
    out_w = int(plan["output"]["width"])
    wm = dict(plan.get("brand", {}).get("watermark") or {})
    safe = plan["captions"]["safe_zone"]
    width = max(64, int(round(out_w * float(wm.get("width_ratio", 0.18)))))
    opacity = min(1.0, max(0.0, float(wm.get("opacity", 0.85))))
    right, bottom = int(safe["right"]), int(safe["bottom"])
    return (
        f"[{logo_index}:v]scale={width}:-1:flags=lanczos,format=rgba,colorchannelmixer=aa={opacity:.2f}[wm];"
        f"[vt][wm]overlay=x=W-w-{right}:y=H-h-{bottom}[vout]"
    )


def video_chain(
    plan: dict,
    ass_path: str | None,
    font: Path | None,
    caps: dict[str, bool],
    fonts_dir: Path | None,
    logo_index: int | None = None,
) -> tuple[str, list[str], bool, bool, bool, bool]:
    """Video: Shots croppen und skalieren, concat, Untertitel, Overlays, Wasserzeichen. Endet in ``[vout]``."""
    shots, _ = _inputs(plan)
    out_w, out_h = int(plan["output"]["width"]), int(plan["output"]["height"])
    parts, labels = [], []
    for i, s in enumerate(shots):
        parts.append(
            f"[{i}:v]setpts=PTS-STARTPTS,crop={int(s['crop_w'])}:{int(s['crop_h'])}:{int(s['crop_x'])}:{int(s['crop_y'])},"
            f"scale={out_w}:{out_h}:flags=lanczos,setsar=1[v{i}];"
        )
        labels.append(f"[v{i}]")
    chain = "".join(parts) + "".join(labels) + f"concat=n={len(shots)}:v=1:a=0[vc];"
    filters: list[str] = []
    notes: list[str] = []
    burned = False
    if ass_path:
        if caps.get("subtitles"):
            sub = f"subtitles={_path(ass_path)}"
            if fonts_dir and Path(fonts_dir).is_dir():
                sub += f":fontsdir={_path(fonts_dir)}"
            filters.append(sub)
            burned = True
        else:
            notes.append("Untertitel nicht eingebrannt: ffmpeg ohne subtitles-Filter (libass); SRT und VTT liegen bei")
    ov, ov_notes, title_drawn, hook_drawn = overlay_filters(plan, font, caps)
    filters += ov
    notes += ov_notes
    watermark = False
    if logo_index is not None and not caps.get("overlay"):
        notes.append("Wasserzeichen nicht gezeichnet: ffmpeg ohne overlay-Filter")
        logo_index = None
    if logo_index is not None:
        chain += "[vc]" + (",".join(filters) if filters else "null") + "[vt];" + watermark_filter(plan, logo_index)
        watermark = True
    else:
        chain += "[vc]" + (",".join(filters) if filters else "null") + "[vout]"
    return chain, notes, burned, title_drawn, hook_drawn, watermark


def loudness_for(plan: dict) -> Loudness:
    a = plan["audio"]
    return Loudness(float(a["lufs"]), float(a["true_peak"]), LOUDNORM_LRA)


def needs_compressor(measured_lra: float | None) -> bool:
    return measured_lra is not None and measured_lra > COMPRESS_ABOVE_LRA


# -- ffmpeg-Aufrufe -----------------------------------------------------------------------------
def _run(cmd: list[str], what: str, level: str = "error") -> subprocess.CompletedProcess:
    full = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", level, "-nostats", *cmd]
    try:
        return subprocess.run(full, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RenderError("ffmpeg ist nicht installiert") from exc
    except subprocess.CalledProcessError as exc:
        tail = [ln for ln in (exc.stderr or "").strip().splitlines() if ln.strip()][-3:]
        raise RenderError(f"{what} fehlgeschlagen: {' | '.join(tail) or exc}") from exc


def measure_loudnorm(src_path: str | os.PathLike, plan: dict, compressor: bool = False) -> dict[str, float]:
    """Pass 1: ``loudnorm=print_format=json`` über die Audio-Kette des Plans. Gibt die Messwerte zurück."""
    shots, _ = _inputs(plan)
    loud = loudness_for(plan)
    chain = audio_chain(plan, len(shots), loud.filter() + ":print_format=json", compressor)
    r = _run([*input_args(src_path, plan), "-filter_complex", chain, "-map", "[aout]", "-f", "null", "-"], "Loudness-Messung", level="info")
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, flags=re.DOTALL)
    if not m:
        raise RenderError("Loudness-Messung lieferte kein JSON")
    data = json.loads(m[-1])
    out: dict[str, float] = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            out[k] = float(data.get(k))
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def loudnorm_pass2(loud: Loudness, measured: dict[str, float]) -> str:
    return (
        f"{loud.filter()}:measured_I={measured['input_i']:.2f}:measured_TP={measured['input_tp']:.2f}:"
        f"measured_LRA={measured['input_lra']:.2f}:measured_thresh={measured['input_thresh']:.2f}:"
        f"offset={measured['target_offset']:.2f}:linear=true:print_format=summary"
    )


def render_from_plan(
    plan: dict,
    src_path: str | os.PathLike,
    ass_path: str | os.PathLike | None,
    out_path: str | os.PathLike,
    fonts_dir: str | os.PathLike | None = None,
    x264_preset: str = "medium",
    crf: int = 19,
    font_path: str | os.PathLike | None = None,
    logo_path: str | os.PathLike | None = None,
) -> RenderResult:
    """Rendert den Plan in ``out_path`` (MP4). Untertitel und Overlays sind best effort (siehe Modul-Docstring).

    ``font_path``: Marken-Font für ``drawtext`` (sonst Inter aus ``fonts_dir``). ``logo_path``: PNG für das
    Wasserzeichen, nur wirksam bei ``plan.brand.watermark.enabled``."""
    if not Path(src_path).is_file():
        raise RenderError("Quelldatei für den Render fehlt")
    caps = capabilities()
    if not caps.get("loudnorm"):
        raise RenderError("ffmpeg ohne loudnorm-Filter, Master-Lautheit nicht möglich")
    fdir = Path(fonts_dir) if fonts_dir else default_fonts_dir()
    font = Path(font_path) if font_path and Path(font_path).is_file() else font_file(fdir)
    logo: Path | None = None
    if logo_path and dict(plan.get("brand", {}).get("watermark") or {}).get("enabled"):
        logo = Path(logo_path) if Path(logo_path).is_file() else None
    loud = loudness_for(plan)
    expected = round(sum(float(s["end"]) - float(s["start"]) for s in plan["segments"]), 3)

    measured = measure_loudnorm(src_path, plan, compressor=False)
    compressor = needs_compressor(measured.get("input_lra"))
    if compressor:
        measured = measure_loudnorm(src_path, plan, compressor=True)

    shots, segments = _inputs(plan)
    logo_index = len(shots) + len(segments) if logo is not None else None
    vchain, notes, burned, title_drawn, hook_drawn, watermark = video_chain(
        plan, str(ass_path) if ass_path else None, font, caps, fdir, logo_index
    )
    achain = audio_chain(plan, len(shots), loudnorm_pass2(loud, measured), compressor)
    graph = vchain + ";" + achain
    fps = float(plan["output"].get("fps") or 25.0)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    logo_args = ["-i", str(logo)] if watermark and logo is not None else []
    cmd = [
        *input_args(src_path, plan), *logo_args,
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-profile:v", "high", "-preset", x264_preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-r", f"{fps:g}", "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-movflags", "+faststart", str(out_path),
    ]  # fmt: skip
    _run(cmd, "Rendern")
    return RenderResult(
        out_path=str(out_path),
        expected_duration_s=expected,
        notes=notes,
        measured=measured,
        compressor=compressor,
        captions_burned=burned,
        title_card_drawn=title_drawn,
        hook_overlay_drawn=hook_drawn,
        watermark_drawn=watermark,
        filter_graph=graph,
    )


def measure_loudness(path: str | os.PathLike) -> dict[str, float]:
    """Integrierte Lautheit (LUFS), True Peak (dBTP) und LRA (LU) des Ergebnisses über ``ebur128``."""
    r = _run(["-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"], "Lautheitsmessung", level="info")
    text = r.stderr
    tail = text[text.rfind("Summary:") :] if "Summary:" in text else text

    def grab(pattern: str) -> float | None:
        m = re.search(pattern, tail)
        return float(m.group(1)) if m else None

    return {
        "integrated_lufs": grab(r"I:\s+(-?[\d.]+)\s+LUFS") or 0.0,
        "true_peak_dbtp": grab(r"Peak:\s+(-?[\d.]+)\s+dBFS") or 0.0,
        "lra_lu": grab(r"LRA:\s+(-?[\d.]+)\s+LU") or 0.0,
    }


def make_poster(video_path: str | os.PathLike, jpg_path: str | os.PathLike, at_s: float = 1.0) -> str:
    """JPG bei ``at_s`` Sekunden (fällt auf 0 s zurück, wenn das Video kürzer ist)."""
    from .. import ingest

    dur = ingest.probe(video_path).duration_s
    t = at_s if dur > at_s + 0.05 else 0.0
    _run(["-ss", f"{t:.3f}", "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(jpg_path)], "Poster")
    return str(jpg_path)


def black_intervals(path: str | os.PathLike, min_s: float = BLACK_MIN_S) -> list[tuple[float, float]]:
    r = _run(["-i", str(path), "-vf", f"blackdetect=d={min_s}:pix_th=0.10", "-an", "-f", "null", "-"], "Schwarzbild-Prüfung", level="info")
    out = []
    for m in re.finditer(r"black_start:(-?[\d.]+)\s+black_end:(-?[\d.]+)", r.stderr):
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def regression_checks(out_path: str | os.PathLike, expected_duration: float, expected_w: int, expected_h: int) -> list[str]:
    """Dauer (±0,3 s), Auflösung, keine Schwarzbilder über 0,5 s, Audiospur vorhanden. Liefert Warnungen."""
    from .. import ingest

    warnings: list[str] = []
    p = Path(out_path)
    if not p.is_file() or p.stat().st_size == 0:
        return ["Ausgabedatei fehlt oder ist leer"]
    pr = ingest.probe(p)
    if abs(pr.duration_s - expected_duration) > DURATION_TOLERANCE_S:
        warnings.append(f"Dauer weicht ab: {pr.duration_s:.2f} s statt {expected_duration:.2f} s")
    if (pr.width, pr.height) != (expected_w, expected_h):
        warnings.append(f"Auflösung {pr.width}x{pr.height} statt {expected_w}x{expected_h}")
    if not pr.has_audio:
        warnings.append("Keine Audiospur im Ergebnis")
    if not pr.has_video:
        warnings.append("Keine Videospur im Ergebnis")
    else:
        for a, b in black_intervals(p):
            warnings.append(f"Schwarzbild von {a:.2f} s bis {b:.2f} s")
    return warnings


def write_captions(
    out_words: list[dict],
    preset: captions_de.CaptionPreset,
    play_res: tuple[int, int],
    directory: str | os.PathLike,
    basename: str,
    font_family: str | None = None,
) -> dict[str, str]:
    """Schreibt ASS (eingebrannt), SRT und VTT (Sidecars) auf die Ausgabe-Timeline. Gibt die Pfade zurück.
    ``font_family`` setzt den ``Fontname`` der ASS (Marken-Font); ohne ihn gilt der Preset-Font."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    paths = {
        "ass": d / f"{basename}.ass",
        "srt": d / f"{basename}.srt",
        "vtt": d / f"{basename}.vtt",
    }
    paths["ass"].write_text(captions_de.to_ass(out_words, 0.0, preset, play_res, font_family=font_family), encoding="utf-8")
    paths["srt"].write_text(captions_de.to_srt(out_words, 0.0, preset.max_chars), encoding="utf-8")
    paths["vtt"].write_text(captions_de.to_vtt(out_words, 0.0, preset.max_chars), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


def ensure_dir(p: str) -> str:
    Path(p).mkdir(parents=True, exist_ok=True)
    return p


__all__ = [
    "AUDIO_RATE",
    "COMPRESSOR",
    "COMPRESS_ABOVE_LRA",
    "DURATION_TOLERANCE_S",
    "LOUDNESS_PRESETS",
    "TITLE_CARD_S",
    "Loudness",
    "RenderError",
    "RenderResult",
    "audio_chain",
    "black_intervals",
    "capabilities",
    "default_fonts_dir",
    "ensure_dir",
    "ffmpeg_available",
    "ffmpeg_filters",
    "font_file",
    "input_args",
    "loudnorm_pass2",
    "make_poster",
    "measure_loudness",
    "measure_loudnorm",
    "needs_compressor",
    "overlay_filters",
    "regression_checks",
    "render_from_plan",
    "video_chain",
    "watermark_filter",
    "write_captions",
]
