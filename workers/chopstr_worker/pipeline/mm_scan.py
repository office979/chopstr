"""Stufe 0 der mehrstufigen Engine: multimodaler Szenen-Scan (T2).

Das Video wird heruntergerechnet (Standard 1 fps, 360p, Mono-Audio), in Fenster geteilt (Standard 10 min mit
Überlappung) und je Fenster an den MM-Provider (``providers_mm``) geschickt. Die Antwort sind zeitgestempelte
Ereignisse ``{t_start, t_end, type, intensity 0..1, speaker?, note, source}`` mit ``type`` aus
``providers_mm.EVENT_TYPES``. Prompt: ``packages/prompts/mm_scan_v1.md`` (gepinnt in der Policy).

Ohne Provider (``none``), ohne Video, ohne ffmpeg, bei einem Fehler je Fenster oder bei erschöpftem Budget
gilt der lokale Fallback aus vorhandenen Signalen: Pegelsprünge im Audioanteil der Heatmap, Sprecherwechsel
aus der Diarisierung, Lachen aus ASR-Markern wie „(lacht)“. Diese Ereignisse tragen ``source: local``.

Einspeisung:

- ``apply_to_heat``: ``laughter_values`` je Bin aus Lachen und Applaus (gelesen von ``payoff_search`` und
  ``trim_plan``), ``event_values`` je Bin aus allen Ereignissen, zusätzliche Seeds an starken Ereignissen.
- ``interleave``: Pseudo-Sätze wie ``[LACHT]`` mit Zeitstempel zwischen den nummerierten Sätzen eines
  Transkriptblocks, ohne eigene Nummer. Damit kann ein Modell ein Ereignis als Auflösung erkennen, aber nie
  eine Spanne an einem Pseudo-Satz beginnen oder enden lassen: Spannen zeigen immer auf echte Sätze bzw.
  Wörter. ``strip_pseudo`` entfernt Pseudo-Marken aus jedem Text, der in Captions oder Copy gehen könnte.

Schalter: ``implementation.mm_scan`` der Policy v2 (``enabled``, ``provider``, ``fps``, ``height``,
``window_s``, ``overlap_s``, ``min_intensity``); Standard an mit Provider ``none``, also lokaler Fallback.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .. import editorial, prompts
from ..costlog import BudgetExceeded
from ..providers_mm import EVENT_SCHEMA, EVENT_TYPES, MMProvider

log = logging.getLogger("chopstr.mm_scan")

SCAN_VERSION = "mm_scan_v1"
SWITCH = "mm_scan"
DEFAULTS: dict[str, Any] = {
    "enabled": True, "provider": "none", "fps": 1, "height": 360, "window_s": 600.0, "overlap_s": 20.0, "min_intensity": 0.3,
}  # fmt: skip
PSEUDO_LABELS = {
    "laughter": "[LACHT]",
    "reaction": "[REAKTION]",
    "emotion_peak": "[EMOTION]",
    "visual_action": "[AKTION]",
    "speaker_change": "[SPRECHERWECHSEL]",
    "shout": "[SCHREI]",
    "applause": "[APPLAUS]",
    "topic_shift": "[THEMENWECHSEL]",
}
_PSEUDO = re.compile(
    r"\[(?:" + "|".join(re.escape(v[1:-1]) for v in PSEUDO_LABELS.values()) + r")\b[^\]]*\]"
    r"(?:[ \t]*\(\d{1,2}:\d{2}(?::\d{2})?(?:,\s*\w+)?\))?[ \t]*"
)
# Lachen, wie es ASR-Systeme ins Transkript schreiben
_ASR_LAUGH = re.compile(r"^[\[(*]?(lacht|lachen|gelächter|haha+|hihi+)[\])*]?[.,!?]*$", re.IGNORECASE)
LAUGHTER_TYPES = ("laughter", "applause")
# Pegelsprung im z-normierten Audioanteil: ab hier ein Ereignis, ab SHOUT_Z ein Schrei
JUMP_Z = 2.0
SHOUT_Z = 2.6
SPEAKER_CHANGE_INTENSITY = 0.3


def settings_from_policy(policy: editorial.Policy | None) -> dict[str, Any]:
    """Einstellungen aus ``implementation.mm_scan``. Fassung 1 oder ohne Abschnitt: aus (``enabled`` False), damit
    der Rollback auf Fassung 1 byte-gleiche Heatmaps liefert; die übrigen Werte sind dann die Standards."""
    raw: Any = None
    if policy is not None and policy.version >= 2:
        raw = (policy.roh.get("implementation") or {}).get(SWITCH)
    cfg = dict(DEFAULTS)
    if raw is None:
        cfg["enabled"] = False
    if isinstance(raw, dict):
        cfg.update({k: raw[k] for k in DEFAULTS if k in raw})
    elif isinstance(raw, bool):
        cfg["enabled"] = raw
    cfg["enabled"] = cfg["enabled"] is True
    for k in ("fps", "height"):
        cfg[k] = int(cfg[k])
    for k in ("window_s", "overlap_s", "min_intensity"):
        cfg[k] = float(cfg[k])
    if cfg["window_s"] <= cfg["overlap_s"] or cfg["window_s"] <= 0:
        raise editorial.PolicyError("implementation.mm_scan: window_s muss größer als overlap_s und als 0 sein.")
    return cfg


def windows(duration_s: float, window_s: float, overlap_s: float) -> list[tuple[float, float]]:
    """Fenster ``(t0, t1)`` über die ganze Dauer, aufeinanderfolgende überlappen um ``overlap_s``."""
    if duration_s <= 0:
        return []
    out: list[tuple[float, float]] = []
    t0 = 0.0
    step = window_s - overlap_s
    while t0 < duration_s:
        t1 = min(duration_s, t0 + window_s)
        out.append((round(t0, 3), round(t1, 3)))
        if t1 >= duration_s:
            break
        t0 += step
    return out


def downscale_window(video: str | Path, out_dir: str | Path, t0: float, t1: float, fps: int, height: int) -> Path:
    """Fenster als kleines MP4 (fps, Höhe, Mono 16 kHz). Liegt die Datei schon da, wird sie wiederverwendet."""
    out = Path(out_dir) / f"mm_{int(t0 * 1000)}_{int(t1 * 1000)}_{fps}fps_{height}p.mp4"
    if out.is_file() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg fehlt, Fenster kann nicht heruntergerechnet werden")
    cmd = [
        ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(video),
        "-vf", f"fps={fps},scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
        "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "32k", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    return out


def normalize(raw: Any, t0: float, t1: float, source: str) -> list[dict[str, Any]]:
    """Antwort eines Fensters in absolute Ereignisse: Typ bekannt, Zeiten im Fenster, Intensität 0..1.

    Das Modell liefert Zeiten relativ zum Fensteranfang; Ereignisse außerhalb des Fensters fallen weg."""
    items = raw.get("events") if isinstance(raw, Mapping) else raw
    out: list[dict[str, Any]] = []
    for e in items or []:
        if not isinstance(e, Mapping) or e.get("type") not in EVENT_TYPES:
            continue
        try:
            a, b = float(e["t_start"]), float(e.get("t_end", e["t_start"]))
            inten = float(e.get("intensity", 0.5))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (a, b, inten)):
            continue
        a, b = t0 + max(0.0, a), t0 + max(0.0, b)
        if a >= t1 or a < t0:
            continue
        ev: dict[str, Any] = {
            "t_start": round(a, 2), "t_end": round(max(a, min(b, t1)), 2), "type": str(e["type"]),
            "intensity": round(min(1.0, max(0.0, inten)), 3), "note": str(e.get("note") or "")[:120], "source": source,
        }  # fmt: skip
        if e.get("speaker"):
            ev["speaker"] = str(e["speaker"])[:40]
        out.append(ev)
    return out


def merge(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sortiert und fasst Dubletten aus überlappenden Fenstern zusammen (gleicher Typ, überlappende Zeit)."""
    out: list[dict[str, Any]] = []
    for e in sorted((dict(x) for x in events), key=lambda x: (x["t_start"], x["type"])):
        twin = next((o for o in reversed(out) if o["type"] == e["type"] and e["t_start"] <= o["t_end"] + 0.5), None)
        if twin is not None:
            twin["t_end"] = max(twin["t_end"], e["t_end"])
            if e["intensity"] > twin["intensity"]:
                twin["intensity"], twin["note"] = e["intensity"], e.get("note") or twin.get("note", "")
            continue
        out.append(e)
    return out


def local_events(words: Sequence[Mapping[str, Any]], heat: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fallback ohne MM-Provider: Pegelsprünge, Sprecherwechsel, Lachen aus ASR-Markern (``source: local``)."""
    out: list[dict[str, Any]] = []
    audio = list((heat or {}).get("audio_values") or [])
    bin_s = float((heat or {}).get("bin_s") or 1.0) or 1.0
    prev = 0.0
    for i, v in enumerate(audio):
        v = float(v)
        if v >= JUMP_Z and prev < JUMP_Z - 1.0:
            kind = "shout" if v >= SHOUT_Z else "emotion_peak"
            out.append({
                "t_start": round(i * bin_s, 2), "t_end": round((i + 1) * bin_s, 2), "type": kind,
                "intensity": round(min(1.0, v / 3.0), 3), "note": "Pegelsprung", "source": "local",
            })  # fmt: skip
        prev = v
    last_speaker = None
    for w in words:
        spk = w.get("speaker")
        text = str(w.get("text") or "").strip()
        if _ASR_LAUGH.match(text):
            out.append({
                "t_start": round(float(w["start"]), 2), "t_end": round(float(w.get("end", w["start"])), 2),
                "type": "laughter", "intensity": 0.6, "note": "ASR-Marker", "source": "local",
            })  # fmt: skip
        if spk is not None and last_speaker is not None and spk != last_speaker:
            out.append({
                "t_start": round(float(w["start"]), 2), "t_end": round(float(w["start"]), 2), "type": "speaker_change",
                "intensity": SPEAKER_CHANGE_INTENSITY, "speaker": str(spk), "note": "", "source": "local",
            })  # fmt: skip
        if spk is not None:
            last_speaker = spk
    return merge(out)


def scan(
    words: Sequence[Mapping[str, Any]],
    heat: Mapping[str, Any] | None,
    provider: MMProvider | None,
    cfg: Mapping[str, Any] | None = None,
    video: str | Path | None = None,
    duration_s: float | None = None,
    work_dir: str | Path | None = None,
    cache: Any = None,
    cache_scope: str = "",
    ledger: Any = None,
    policy: editorial.Policy | None = None,
) -> dict[str, Any]:
    """Ereignisse der ganzen Quelle. Rückgabe ``{version, source, provider, model, events, windows, skipped}``.

    ``source`` ist der MM-Provider, ``local`` (nur Fallback) oder ``mixed`` (einzelne Fenster mit Fallback).
    Je Fenster steht im Ergebnis-Cache (``cache``) die normalisierte Antwort; ein zweiter Lauf schickt nichts."""
    cfg = dict(cfg or settings_from_policy(policy))
    fallback = local_events(words, heat)
    result: dict[str, Any] = {
        "version": SCAN_VERSION, "source": "local", "provider": getattr(provider, "name", "none"),
        "model": provider.model() if provider is not None and provider.available else None,
        "events": fallback, "windows": [], "skipped": [],
    }  # fmt: skip
    if not cfg.get("enabled"):
        result.update(events=[], source="off")
        return result
    if provider is None or not provider.available or video is None:
        if provider is not None and provider.available and video is None:
            result["skipped"].append({"reason": "no_video"})
        return result
    if duration_s is None:
        duration_s = max([float(w.get("end", 0.0)) for w in words] + [0.0])
    try:
        p = prompts.load_pinned("mm_scan", policy)
    except editorial.PolicyError:
        # Fassung 1 pinnt den Scan nicht; er gehört zu Fassung 2, also gilt deren Pin.
        p = prompts.load_pinned("mm_scan", editorial.load(2))
    events: list[dict[str, Any]] = []
    used_fallback = False
    tmp = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="chopstr-mm-"))
    for t0, t1 in windows(float(duration_s), float(cfg["window_s"]), float(cfg["overlap_s"])):
        win = {"t0": t0, "t1": t1, "status": "ok"}
        key = None
        if cache is not None:
            key = cache.key(cache_scope or str(video), "mm_scan", [provider.name, provider.model(), p.prompt_version, t0, t1, cfg], SCAN_VERSION)
            hit = cache.get(key)
            if isinstance(hit, list):
                events.extend(hit)
                win["status"] = "cached"
                result["windows"].append(win)
                if ledger is not None:
                    ledger({"stage": "mm_scan", "provider": provider.name, "model": provider.model(), "cached_result": True})
                continue
        try:
            if ledger is not None:
                ledger.check("mm_scan")
            clip = downscale_window(video, tmp, t0, t1, int(cfg["fps"]), int(cfg["height"]))
            prompt = p.render(window_start=_clock(t0), window_end=_clock(t1), window_s=int(t1 - t0), types=", ".join(EVENT_TYPES))
            raw = provider.scan_window(clip, t0, t1, prompt, EVENT_SCHEMA)
            got = normalize(raw, t0, t1, provider.name)
        except BudgetExceeded as exc:
            win.update(status="budget_exhausted", detail=exc.detail)
            result["skipped"].append({"t0": t0, "t1": t1, "reason": "budget_exhausted"})
            got, used_fallback = [e for e in fallback if t0 <= e["t_start"] < t1], True
        except Exception as exc:  # noqa: BLE001 - ein Fenster darf den Scan nicht stoppen, es gilt der Fallback
            log.warning("mm_scan Fenster %s-%s fehlgeschlagen: %s", t0, t1, exc.__class__.__name__)
            win.update(status="failed", detail=exc.__class__.__name__)
            got, used_fallback = [e for e in fallback if t0 <= e["t_start"] < t1], True
        else:
            if key is not None:
                cache.put(key, got)
        events.extend(got)
        result["windows"].append(win)
    result["events"] = merge(events)
    result["source"] = "mixed" if used_fallback else provider.name
    return result


def _clock(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 3600:d}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def bin_values(events: Sequence[Mapping[str, Any]], n_bins: int, bin_s: float = 1.0, types: Sequence[str] | None = None) -> list[float]:
    """Höchste Intensität je Bin über die Ereignisse der Typen ``types`` (alle ohne Angabe)."""
    vals = [0.0] * max(0, int(n_bins))
    for e in events:
        if types is not None and e["type"] not in types:
            continue
        a = max(0, int(float(e["t_start"]) / bin_s))
        b = min(len(vals) - 1, int(float(e["t_end"]) / bin_s))
        for i in range(a, b + 1):
            if 0 <= i < len(vals):
                vals[i] = max(vals[i], float(e["intensity"]))
    return [round(v, 3) for v in vals]


def apply_to_heat(heat: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]], min_intensity: float = 0.3) -> dict:
    """Heatmap mit Ereignissen: ``laughter_values`` (Lachen, Applaus), ``event_values`` (alle), Seeds ergänzt.

    Die gespeicherte Heatmap bleibt unverändert, zurück kommt eine Kopie. Neue Seeds nur an Ereignissen ab
    ``min_intensity`` und nicht an bloßen Sprecherwechseln; Mindestabstand wie die Heatmap (45 s)."""
    out = dict(heat or {})
    bin_s = float(out.get("bin_s") or 1.0) or 1.0
    end = max([float(e["t_end"]) for e in events] + [0.0])
    n = int(out.get("n_bins") or 0) or int(end / bin_s) + 1
    out.setdefault("bin_s", bin_s)
    out["n_bins"] = n
    out["laughter_values"] = bin_values(events, n, bin_s, LAUGHTER_TYPES)
    out["event_values"] = bin_values(events, n, bin_s)
    seeds = [float(x) for x in (out.get("seeds") or [])]
    strong = sorted((e for e in events if e["type"] != "speaker_change" and float(e["intensity"]) >= min_intensity),
                    key=lambda e: -float(e["intensity"]))  # fmt: skip
    added = 0
    for e in strong:
        t = float(e["t_start"])
        if all(abs(t - s) >= 45.0 for s in seeds):
            seeds.append(round(t, 2) if bin_s != 1.0 else int(t))
            added += 1
    out["seeds"] = sorted(seeds)
    out["mm_events"] = {"n": len(events), "seeds_added": added, "laughter_bins": sum(1 for v in out["laughter_values"] if v > 0)}
    return out


def pseudo_line(e: Mapping[str, Any]) -> str:
    label = PSEUDO_LABELS.get(str(e["type"]), "[EREIGNIS]")
    stufe = "stark" if float(e["intensity"]) >= 0.7 else ("mittel" if float(e["intensity"]) >= 0.4 else "leicht")
    return f"      {label} ({_clock(float(e['t_start']))}, {stufe})"


def interleave(sents: Sequence[Any], events: Sequence[Mapping[str, Any]], numbered_line, min_intensity: float = 0.3) -> str:
    """Nummerierte Sätze mit Pseudo-Sätzen dazwischen (eingerückt, ohne Nummer).

    ``numbered_line(sentence)`` rendert einen echten Satz wie im übrigen Prompt. Ein Ereignis steht hinter dem
    letzten Satz, der vor oder bei seinem Beginn anfängt; Sprecherwechsel fehlen (sie stehen schon im Satz)."""
    evs = sorted((e for e in events if e["type"] != "speaker_change" and float(e["intensity"]) >= min_intensity),
                 key=lambda e: float(e["t_start"]))  # fmt: skip
    if not sents:
        return ""
    a, b = float(sents[0].start), float(sents[-1].end) + 3.0
    evs = [e for e in evs if a <= float(e["t_start"]) <= b]
    lines: list[str] = []
    k = 0
    for n, s in enumerate(sents):
        lines.append(numbered_line(s))
        nxt = float(sents[n + 1].start) if n + 1 < len(sents) else float("inf")
        while k < len(evs) and float(evs[k]["t_start"]) < nxt:
            lines.append(pseudo_line(evs[k]))
            k += 1
    return "\n".join(lines)


def strip_pseudo(text: str) -> str:
    """Entfernt Pseudo-Marken (``[LACHT]`` usw.) aus Text für Captions, Titel und Post-Text."""
    # Nur Leerzeichen zusammenziehen, Zeilenumbrüche im Post-Text bleiben
    return re.sub(r"[ \t]{2,}", " ", _PSEUDO.sub("", str(text or ""))).strip()


__all__ = [
    "DEFAULTS",
    "PSEUDO_LABELS",
    "SCAN_VERSION",
    "apply_to_heat",
    "bin_values",
    "downscale_window",
    "interleave",
    "local_events",
    "merge",
    "normalize",
    "pseudo_line",
    "scan",
    "settings_from_policy",
    "strip_pseudo",
    "windows",
]
