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

Folien-Crop (Phase 5c): Shots mit ``layout = "pip"`` werden aus einem Input zweimal geschnitten (``split``):
die Folie (``reframe.slide_region``) skaliert auf die volle Breite und die Höhe ``pip.y`` (Seitenverhältnis bleibt,
Rest schwarz per ``pad``), der Sprecher-Crop des Shots auf ``pip.w x pip.h``; beide per ``vstack`` untereinander.
Alle übrigen Schritte (concat, Untertitel, Overlays, Audio) bleiben unverändert.
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

from . import captions_de, render_plan
from . import effekte as effekte_mod
from . import musik as musik_mod

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
        "overlay": "overlay" in f, "vstack": "vstack" in f and "split" in f and "pad" in f,
        "zoompan": "zoompan" in f,
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


def _drawtext_lines(lines: list[str], font: Path, font_px: int, y0: int, seconds: float, style: str = "dark") -> list[str]:
    """Textzeilen als drawtext-Filter.

    ``style = "light"`` ist der Instagram-Look: schwarze Schrift auf deckendem Weiß. ``"dark"`` ist
    der frühere Look, weiße Schrift auf halbdurchsichtigem Schwarz; er bleibt für die Titelkarte,
    die über dem eigenen Standbild liegt."""
    line_h = int(round(font_px * 1.3))
    fontcolor, boxcolor = ("black", "white@0.95") if style == "light" else ("white", "black@0.6")
    out = []
    for i, line in enumerate(lines):
        out.append(
            f"drawtext=fontfile={_path(font)}:text={_text(line)}:expansion=none:fontsize={font_px}:fontcolor={fontcolor}:"
            f"box=1:boxcolor={boxcolor}:boxborderw={max(8, font_px // 4)}:x=(w-text_w)/2:y={y0 + i * line_h}:"
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
        filters += _drawtext_lines(lines, font, font_px, y, float(hook["seconds"]), style="light")
        hook_drawn = True
    return filters, notes, title_drawn, hook_drawn


def _inputs(plan: dict) -> tuple[list[dict], list[dict]]:
    shots = list(plan.get("shots") or [])
    segments = list(plan["segments"])
    if not shots:
        raise RenderError("Plan ohne Shots")
    return shots, segments


def input_args(src_path: str | os.PathLike, plan: dict, musik_path: str | os.PathLike | None = None) -> list[str]:
    """``-ss``/``-t``/``-i`` je Shot (Video) und je Segment (Audio), in dieser Reihenfolge.

    Die Musik haengt hinten dran, VOR dem Logo. Das ist kein Geschmack, sondern noetig: die
    Lautheitsmessung (Pass 1) laeuft ohne Logo, der Render mit. Kaeme die Musik danach, haette sie
    in beiden Laeufen eine andere Nummer - und Pass 2 wuerde einen Eingang mischen, der dort ein
    Bild ist."""
    shots, segments = _inputs(plan)
    args: list[str] = []
    for item in [*shots, *segments]:
        start, end = float(item["start"]), float(item["end"])
        args += ["-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.001):.3f}", "-i", str(src_path)]
    if musik_path is not None:
        args += ["-i", str(musik_path)]
    return args


def musik_index(plan: dict) -> int:
    """Die Eingangsnummer der Musik: direkt hinter Shots und Segmenten."""
    shots, segments = _inputs(plan)
    return len(shots) + len(segments)


def audio_chain(
    plan: dict,
    first_input: int,
    loud_filter: str,
    compressor: bool,
    musik: musik_mod.Musik | None = None,
) -> str:
    """Audio: Segmente mit Micro-Fades, concat, optional Musik, Kompressor, Loudnorm, 48 kHz.

    Endet in ``[aout]``.

    DIE MUSIK KOMMT VOR LOUDNORM. Andersherum waere die gemessene Endlautheit die von Sprache
    ALLEIN, und der fertige Clip laege um die Musik darueber - also ueber dem, was die Plattformen
    erwarten und leiser regeln. Deshalb steht die Mischung zwischen concat und dem Tail."""
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
    quelle = "[ac]"
    if musik is not None:
        dauer = sum(float(s["end"]) - float(s["start"]) for s in segments)
        kette, quelle = musik_mod.ffmpeg_kette(musik, musik_index(plan), dauer)
        chain += kette
    tail = (COMPRESSOR + "," if compressor else "") + loud_filter + f",aresample={AUDIO_RATE}"
    return chain + f"{quelle}{tail}[aout]"


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


def pip_shot_filter(plan: dict, index: int, shot: dict) -> str:
    """Filterkette eines ``pip``-Shots: Folie oben (``reframe.slide_region`` auf Breite x ``pip.y``, Rest schwarz),
    Sprecher-Crop unten (``pip.w x pip.h``), ``vstack``. Endet in ``[v<index>]``."""
    rf = plan.get("reframe") or {}
    region, pip = rf.get("slide_region"), rf.get("pip")
    if not region or not pip:
        raise RenderError("Shot mit Layout pip, aber der Plan hat keine slide_region oder pip")
    out_w = int(plan["output"]["width"])
    slide_h = int(pip["y"])
    if int(pip["x"]) != 0 or int(pip["w"]) != out_w or slide_h <= 0:
        raise RenderError("Layout pip erwartet die Sprecherfläche über die volle Breite unter der Folie")
    return (
        f"[{index}:v]setpts=PTS-STARTPTS,split=2[s{index}][p{index}];"
        f"[s{index}]crop={int(region['w'])}:{int(region['h'])}:{int(region['x'])}:{int(region['y'])},"
        f"scale={out_w}:{slide_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={out_w}:{slide_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[sl{index}];"
        f"[p{index}]crop={int(shot['crop_w'])}:{int(shot['crop_h'])}:{int(shot['crop_x'])}:{int(shot['crop_y'])},"
        f"scale={int(pip['w'])}:{int(pip['h'])}:flags=lanczos,setsar=1[pp{index}];"
        f"[sl{index}][pp{index}]vstack=inputs=2[v{index}];"
    )


def geteilt_shot_filter(plan: dict, index: int, shot: dict) -> str:
    """Zwei Personen uebereinander, beide aus DEMSELBEN Quellbild geschnitten.

    Das ist der Unterschied zum Reaktionsformat, wo ein zweites Video dazukommt: hier gibt es nur
    eine Kamera, und das Bild wird zweimal verschieden ausgeschnitten. Genau das loest die Stelle,
    an der die Automatik nicht entscheiden kann, wer spricht - dann zeigt man eben beide.

    Jede Haelfte bekommt die halbe Ausgabehoehe. Damit ein Gesicht darin nicht auf einen Streifen
    zusammengedrueckt wird, ist der Ausschnitt je Haelfte doppelt so breit wie hoch gemessen am
    Ausgabeformat; das Quellbild liefert diese Breite bei 16:9 muehelos.
    """
    out_w, out_h = int(plan["output"]["width"]), int(plan["output"]["height"])
    haelfte = max(2, int(out_h / 2) // 2 * 2)  # gerade Zahl, sonst mag es der Encoder nicht
    zwei = shot.get("geteilt") or []
    if len(zwei) != 2:
        raise RenderError("Shot mit Layout geteilt, aber der Plan nennt nicht zwei Ausschnitte")
    teile = []
    for n, t in enumerate(zwei):
        teile.append(
            f"[g{index}_{n}]crop={int(t['w'])}:{int(t['h'])}:{int(t['x'])}:{int(t['y'])},"
            f"scale={out_w}:{haelfte}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={out_w}:{haelfte},setsar=1[gt{index}_{n}];"
        )
    return (
        f"[{index}:v]setpts=PTS-STARTPTS,split=2[g{index}_0][g{index}_1];"
        + "".join(teile)
        + f"[gt{index}_0][gt{index}_1]vstack=inputs=2,scale={out_w}:{out_h}:flags=lanczos,setsar=1[v{index}];"
    )


def zoom_filter(out_w: int, out_h: int, fps: float, duration: float, zoom_to: float) -> str:
    """Langsamer Push-in über eine Einstellung: linear von 1,0 auf ``zoom_to``, mittig.

    Vor dem Zoom wird auf die doppelte Ausgabegröße hochskaliert. ``zoompan`` quantisiert den
    Zoomfaktor je Frame; ohne diesen Zwischenschritt springt das Bild sichtbar in Stufen.
    ``d=1`` heißt: ein Ausgabeframe je Eingabeframe, die Länge bleibt also unverändert."""
    frames = max(1, int(round(max(duration, 0.04) * fps)))
    expr = f"min(1+{zoom_to - 1:.4f}*on/{frames},{zoom_to:.4f})"
    return (
        f"scale={out_w * 2}:{out_h * 2}:flags=lanczos,"
        f"zoompan=z='{expr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={out_w}x{out_h}:fps={fps:g},"
        f"setsar=1"
    )


def video_chain(
    plan: dict,
    ass_path: str | None,
    font: Path | None,
    caps: dict[str, bool],
    fonts_dir: Path | None,
    logo_index: int | None = None,
) -> tuple[str, list[str], bool, bool, bool, bool]:
    """Video: Shots croppen und skalieren (``pip``: Folie plus Sprecher), concat, Untertitel, Overlays,
    Wasserzeichen. Endet in ``[vout]``."""
    shots, _ = _inputs(plan)
    out_w, out_h = int(plan["output"]["width"]), int(plan["output"]["height"])
    fps = float(plan["output"].get("fps") or 25.0)
    motion = plan.get("motion") or {}
    zoom_to = float(motion.get("zoom_to") or 1.0)
    zoom_min_s = float(motion.get("min_shot_s") or 0.0)
    can_zoom = zoom_to > 1.0 and caps.get("zoompan", True)
    parts, labels = [], []
    for i, s in enumerate(shots):
        if s.get("layout") == "pip":
            if not caps.get("vstack", True):
                raise RenderError("ffmpeg ohne split/pad/vstack-Filter, Layout pip nicht möglich")
            parts.append(pip_shot_filter(plan, i, s))
        elif s.get("layout") == "geteilt":
            if not caps.get("vstack", True):
                raise RenderError("ffmpeg ohne split/vstack-Filter, geteiltes Bild nicht möglich")
            parts.append(geteilt_shot_filter(plan, i, s))
        else:
            crop = f"crop={int(s['crop_w'])}:{int(s['crop_h'])}:{int(s['crop_x'])}:{int(s['crop_y'])}"
            duration = float(s.get("end", 0.0)) - float(s.get("start", 0.0))
            if can_zoom and duration >= zoom_min_s:
                parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{crop},{zoom_filter(out_w, out_h, fps, duration, zoom_to)}[v{i}];")
            else:
                parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{crop},scale={out_w}:{out_h}:flags=lanczos,setsar=1[v{i}];")
        labels.append(f"[v{i}]")
    chain = "".join(parts) + "".join(labels) + f"concat=n={len(shots)}:v=1:a=0[vc];"
    filters: list[str] = []
    notes: list[str] = []
    burned = False

    # Effekte liegen auf der Zeitachse des FERTIGEN Clips, also hinter dem Zusammenfuegen. Der
    # Push-in weiter oben gehoert zur einzelnen Einstellung; hier geht es um eine Betonung an einer
    # bestimmten Sekunde, und die kann ueber eine Schnittgrenze hinweg laufen.
    #
    # Vor dem Zoom wird auf die doppelte Groesse skaliert: zoompan quantisiert den Faktor je Bild,
    # ohne den Zwischenschritt springt die Bewegung sichtbar in Stufen.
    quelle = "[vc]"
    effekte = effekte_mod.lesen(plan.get("effekte"), render_plan.plan_duration(plan))
    if effekte and not caps.get("zoompan", True):
        notes.append("ffmpeg ohne zoompan-Filter, Effekte wurden weggelassen")
    elif effekte:
        # Erst hochskalieren (zoompan quantisiert je Bild, sonst springt die Bewegung in Stufen),
        # dann schwarze Reserve ringsherum: ohne sie koennte „heraus" nicht kleiner werden, denn
        # zoompan kann nur hineingehen. Der Ruhezustand ist deshalb z = RESERVE.
        ausdruck = effekte_mod.ffmpeg_ausdruck(effekte, fps)
        gross_w, gross_h = out_w * 2, out_h * 2
        rand_w = int(round(gross_w * effekte_mod.RESERVE))
        rand_h = int(round(gross_h * effekte_mod.RESERVE))
        chain += (
            f"[vc]scale={gross_w}:{gross_h}:flags=lanczos,"
            f"pad={rand_w}:{rand_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"zoompan=z='{ausdruck}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={out_w}x{out_h}:fps={fps:g},"
            f"setsar=1[ve];"
        )
        quelle = "[ve]"
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
        chain += quelle + (",".join(filters) if filters else "null") + "[vt];" + watermark_filter(plan, logo_index)
        watermark = True
    else:
        chain += quelle + (",".join(filters) if filters else "null") + "[vout]"
    return chain, notes, burned, title_drawn, hook_drawn, watermark


def loudness_for(plan: dict) -> Loudness:
    a = plan["audio"]
    return Loudness(float(a["lufs"]), float(a["true_peak"]), LOUDNORM_LRA)


def needs_compressor(measured_lra: float | None) -> bool:
    return measured_lra is not None and measured_lra > COMPRESS_ABOVE_LRA


# -- ffmpeg-Aufrufe -----------------------------------------------------------------------------
# Meldungen, die ffmpeg bei ERFOLGREICHEM Lauf ausgibt und die trotzdem bedeuten, dass das Ergebnis
# nicht in Ordnung ist. ffmpeg beendet sich in diesen Faellen mit 0, schreibt die Warnung nach
# stderr und niemand liest sie.
STILLE_WARNUNGEN = (
    "Invalid NAL unit",
    "error while decoding",
    "corrupt",
    "Non-monotonous DTS",
    "Past duration",
    "buffer underflow",
    "decode_slice_header error",
    "missing picture",
    "Conversion failed",
)


def _run(cmd: list[str], what: str, level: str = "error") -> subprocess.CompletedProcess:
    full = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", level, "-nostats", *cmd]
    try:
        r = subprocess.run(full, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RenderError("ffmpeg ist nicht installiert") from exc
    except subprocess.CalledProcessError as exc:
        tail = [ln for ln in (exc.stderr or "").strip().splitlines() if ln.strip()][-3:]
        raise RenderError(f"{what} fehlgeschlagen: {' | '.join(tail) or exc}") from exc
    # Erfolgreich beendet heisst nicht fehlerfrei. Beim Nachgehen eines kaputten Bildstroms kam
    # heraus, dass genau hier die Spur endete: ffmpeg lief durch, meldete den Schaden nach stderr,
    # und capture_output hat ihn verschluckt. Zwei von vierzehn Clips waren betroffen.
    meldungen = (r.stderr or "").strip()
    if meldungen:
        auffaellig = [w for w in STILLE_WARNUNGEN if w in meldungen]
        zeilen = [ln.strip() for ln in meldungen.splitlines() if ln.strip()][:3]
        if auffaellig:
            log.warning("ffmpeg %s meldet trotz Erfolg: %s | %s", what, ", ".join(auffaellig), " | ".join(zeilen))
        else:
            log.info("ffmpeg %s: %s", what, " | ".join(zeilen))
    return r


def measure_loudnorm(
    src_path: str | os.PathLike,
    plan: dict,
    compressor: bool = False,
    musik: musik_mod.Musik | None = None,
    musik_path: str | os.PathLike | None = None,
) -> dict[str, float]:
    """Pass 1: ``loudnorm=print_format=json`` über die Audio-Kette des Plans. Gibt die Messwerte zurück.

    Die Musik muss hier MIT gemessen werden. Ohne sie misst Pass 1 die Sprache allein, Pass 2
    normalisiert darauf, und die Musik kommt obendrauf - der Clip waere zu laut."""
    shots, _ = _inputs(plan)
    loud = loudness_for(plan)
    chain = audio_chain(plan, len(shots), loud.filter() + ":print_format=json", compressor, musik)
    r = _run(
        [*input_args(src_path, plan, musik_path), "-filter_complex", chain, "-map", "[aout]", "-f", "null", "-"],
        "Loudness-Messung",
        level="info",
    )
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
    musik_path: str | os.PathLike | None = None,
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

    # Musik nur, wenn im Plan steht WAS und der Aufrufer sagt WO die Datei liegt. Fehlt eines von
    # beidem, wird still ohne Musik gerendert - ein Clip ohne Musik ist besser als kein Clip.
    musik = musik_mod.lesen(plan.get("musik")) if musik_path else None
    if musik is None:
        musik_path = None

    measured = measure_loudnorm(src_path, plan, compressor=False, musik=musik, musik_path=musik_path)
    compressor = needs_compressor(measured.get("input_lra"))
    if compressor:
        measured = measure_loudnorm(src_path, plan, compressor=True, musik=musik, musik_path=musik_path)

    shots, segments = _inputs(plan)
    # Das Logo kommt HINTER die Musik, siehe input_args.
    logo_versatz = 1 if musik_path else 0
    logo_index = len(shots) + len(segments) + logo_versatz if logo is not None else None
    vchain, notes, burned, title_drawn, hook_drawn, watermark = video_chain(
        plan, str(ass_path) if ass_path else None, font, caps, fdir, logo_index
    )
    achain = audio_chain(plan, len(shots), loudnorm_pass2(loud, measured), compressor, musik)
    graph = vchain + ";" + achain
    fps = float(plan["output"].get("fps") or 25.0)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    logo_args = ["-i", str(logo)] if watermark and logo is not None else []
    cmd = [
        *input_args(src_path, plan, musik_path), *logo_args,
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


# Filmstreifen fuer die Zeitleiste: ein einziges Bild mit vielen kleinen Einzelbildern nebeneinander.
# Bewusst eine Datei und nicht hundert: ein Streifen ist ein Bildabruf, hundert Einzelbilder waeren
# hundert, und die Zeitleiste soll sofort dastehen und nicht nachladen, waehrend man schiebt.
# Zahl und Hoehe sind an der fertigen Oberflaeche abgelesen, nicht geraten: die Zeitleiste steht in
# der linken Spalte und ist dort rund 400 Bildpunkte breit. Mit 40 Einzelbildern blieben davon 10
# Punkte je Bild uebrig, und der Streifen wurde zu einem grauen Band, auf dem nichts mehr zu
# erkennen war. Mit 20 sind es 20 Punkte je Bild bei 72 Punkten Hoehe - schmal, aber man sieht, wer
# im Bild ist und wo ein Kameraschnitt liegt. Genau dafuer ist der Streifen da; das Bild selbst
# zeigt die Vorschau darueber.
STREIFEN_BILDER = 20  # so viele Einzelbilder ueber den ganzen Clip
STREIFEN_HOEHE = 108  # Hoehe je Einzelbild in Bildpunkten; die Breite ergibt sich aus dem Format


def make_filmstreifen(
    video_path: str | os.PathLike,
    jpg_path: str | os.PathLike,
    bilder: int = STREIFEN_BILDER,
    hoehe: int = STREIFEN_HOEHE,
) -> dict | None:
    """Einzelbilder ueber die ganze Laenge in EIN JPG nebeneinander legen.

    Zurueck kommt, was die Oberflaeche zum Rechnen braucht: wie viele Bilder, wie breit eines ist
    und wie hoch. Ohne diese Angaben muesste sie das Bild erst laden und vermessen.

    Bei einem Fehler kommt None. Ein fehlender Streifen kostet Bedienkomfort, aber der Clip ist
    fertig; ihn deswegen scheitern zu lassen waere falsch herum.
    """
    from .. import ingest

    try:
        pr = ingest.probe(video_path)
        dauer = float(pr.duration_s or 0.0)
        if dauer <= 0:
            return None
        n = max(1, min(int(bilder), 120))
        # fps so waehlen, dass ueber die ganze Laenge genau n Bilder herauskommen.
        fps = n / dauer
        breite = max(2, int(round(hoehe * (pr.width or 16) / (pr.height or 9))) // 2 * 2)
        _run(
            [
                "-i", str(video_path),
                "-vf", f"fps={fps:.6f},scale={breite}:{hoehe},tile={n}x1",
                "-frames:v", "1", "-q:v", "4",
                str(jpg_path),
            ],
            "Filmstreifen",
        )  # fmt: skip
        if not os.path.isfile(jpg_path) or os.path.getsize(jpg_path) == 0:
            return None
        return {"bilder": n, "breite": breite, "hoehe": hoehe, "dauer_s": round(dauer, 3)}
    except Exception:
        return None


def black_intervals(path: str | os.PathLike, min_s: float = BLACK_MIN_S) -> list[tuple[float, float]]:
    r = _run(["-i", str(path), "-vf", f"blackdetect=d={min_s}:pix_th=0.10", "-an", "-f", "null", "-"], "Schwarzbild-Prüfung", level="info")
    out = []
    for m in re.finditer(r"black_start:(-?[\d.]+)\s+black_end:(-?[\d.]+)", r.stderr):
        out.append((float(m.group(1)), float(m.group(2))))
    return out


# Meldungen, an denen ein kaputter H.264-Strom zu erkennen ist. Sie tauchen auch beim blossen
# Umkopieren auf, also ohne zu dekodieren, und sind damit billig zu pruefen.
BITSTROM_FEHLER = (
    "Invalid NAL unit",
    "Error splitting the input",
    "missing picture in access unit",
    "corrupt",
    "error while decoding",
    "Invalid data found",
    "decode_slice_header error",
    "no frame!",
)


def bitstrom_pruefen(out_path: str | os.PathLike) -> list[str]:
    """Laesst sich die Datei ueberhaupt von vorne bis hinten lesen?

    Gemessen an echten Ergebnissen: zwei von sechs gerenderten Clips hatten einen kaputten
    H.264-Strom („Invalid NAL unit size"), bei dem nur rund 60 Prozent der Bilder dekodierten. Der
    Player bleibt dann mittendrin stehen. Die bisherigen Pruefungen haben das nicht gesehen, weil
    Dauer, Aufloesung, Ton und Schwarzbild alle in Ordnung waren - die Laenge steht im Container,
    nicht im Bildstrom.

    Geprueft wird mit vollem Dekodieren. Der naheliegende, billigere Weg ueber ``-c copy`` findet
    zwar den echten Fall (kaputte Laengenangaben der NAL-Einheiten), aber nicht einen beschaedigten
    Bildinhalt: dort stimmen die Laengen, nur die Daten nicht. Dekodieren laeuft bei einem
    Kurzformat-Clip mit rund dem Neunzigfachen der Echtzeit, kostet also unter einer Sekunde.
    """
    p = Path(out_path)
    if not p.is_file():
        return ["Ausgabedatei fehlt"]
    try:
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(p), "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
    except FileNotFoundError:
        return []
    meldungen = r.stderr or ""
    treffer = sorted({m for m in BITSTROM_FEHLER if m in meldungen})
    if not treffer:
        return []
    erste = next((ln.strip() for ln in meldungen.splitlines() if ln.strip()), "")
    return [f"Bildstrom beschaedigt ({', '.join(treffer)}): {erste[:120]}"]


def regression_checks(
    out_path: str | os.PathLike,
    expected_duration: float,
    expected_w: int,
    expected_h: int,
    bitstrom: bool = True,
) -> list[str]:
    """Dauer (±0,3 s), Auflösung, keine Schwarzbilder über 0,5 s, Audiospur vorhanden, Bildstrom lesbar.

    ``bitstrom=False``, wenn der Aufrufer den Bildstrom schon selbst geprüft hat: das Dekodieren
    ist der teuerste Teil und muss nicht zweimal laufen."""
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
        if bitstrom:
            warnings.extend(bitstrom_pruefen(p))
    return warnings


def write_captions(
    out_words: list[dict],
    preset: captions_de.CaptionPreset,
    play_res: tuple[int, int],
    directory: str | os.PathLike,
    basename: str,
    font_family: str | None = None,
    text_field: str = "text",
) -> dict[str, str]:
    """Schreibt ASS (eingebrannt), SRT und VTT (Sidecars) auf die Ausgabe-Timeline. Gibt die Pfade zurück.
    ``font_family`` setzt den ``Fontname`` der ASS (Marken-Font); ohne ihn gilt der Preset-Font.
    ``text_field`` wählt ``text`` (Original) oder ``text_norm`` (normalisiert, Fallback auf ``text``)."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    paths = {
        "ass": d / f"{basename}.ass",
        "srt": d / f"{basename}.srt",
        "vtt": d / f"{basename}.vtt",
    }
    paths["ass"].write_text(
        captions_de.to_ass(out_words, 0.0, preset, play_res, font_family=font_family, text_field=text_field), encoding="utf-8"
    )
    # Dasselbe Preset wie die eingebrannten Untertitel, damit die Beiblaetter an denselben Stellen
    # umbrechen. Vorher bekamen sie nur die Zeichenbreite; bei den hochkanten Stilen stand im Bild
    # ein Wort je Einblendung und in der SRT ein ganzer Satz.
    paths["srt"].write_text(captions_de.to_srt(out_words, 0.0, preset, text_field=text_field), encoding="utf-8")
    paths["vtt"].write_text(captions_de.to_vtt(out_words, 0.0, preset, text_field=text_field), encoding="utf-8")
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
    "bitstrom_pruefen",
    "black_intervals",
    "capabilities",
    "default_fonts_dir",
    "ensure_dir",
    "ffmpeg_available",
    "ffmpeg_filters",
    "font_file",
    "input_args",
    "loudnorm_pass2",
    "make_filmstreifen",
    "make_poster",
    "measure_loudness",
    "measure_loudnorm",
    "needs_compressor",
    "overlay_filters",
    "geteilt_shot_filter",
    "pip_shot_filter",
    "regression_checks",
    "render_from_plan",
    "video_chain",
    "watermark_filter",
    "write_captions",
]
