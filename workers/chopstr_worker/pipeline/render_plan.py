"""Render-Plan ``render_plan_v1`` (Vertrag ``packages/schema/CLIPS.md``): deterministisch, vollständig, JSON.

Aus dem Plan lässt sich der Render wiederholen: Segmente, Ausgabegröße und Bildrate, Reframe-Ergebnis
und Shots, Caption-Preset mit Safe Zones (für andere Größen als 9:16 proportional umgerechnet),
Titelkarte, Hook-Overlay, Audio-Preset, Quellen und Modulversionen. Keine Umgebungswerte (Fontpfade,
Filterverfügbarkeit) im Plan; die gehören zum Render-Ergebnis.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import captions_de, reframe

CONTRACT = "render_plan_v1"
RENDER_VERSION = "render_v1"
CAPTIONS_VERSION = "captions_v1"
OUTPUT_SIZES: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}
PLATFORM_ASPECT = {"tiktok": "9:16", "reels": "9:16", "shorts": "9:16", "linkedin": "4:5"}
TITLE_CARD_S = 2.5
HOOK_OVERLAY_S = 3.0
MICRO_FADE_MS = 20
HOOK_OVERLAY_DEFAULT = {"tiktok": True, "reels": True, "shorts": True, "linkedin": False}
AUDIO_PRESETS: dict[str, dict[str, float]] = {
    "master": {"lufs": -16.0, "true_peak": -1.5},
    "legacy_social": {"lufs": -14.0, "true_peak": -1.0},
}
DEFAULT_FPS = 25.0
VERSIONS = {"captions_de": CAPTIONS_VERSION, "render": RENDER_VERSION, "reframe": reframe.REFRAME_VERSION}


def output_size(aspect: str) -> tuple[int, int]:
    if aspect not in OUTPUT_SIZES:
        raise ValueError(f"Unbekanntes Seitenverhältnis {aspect!r} (erlaubt: {', '.join(OUTPUT_SIZES)})")
    return OUTPUT_SIZES[aspect]


def aspect_for_platform(platform: str) -> str:
    return PLATFORM_ASPECT.get(platform, "9:16")


def hook_overlay_enabled(platform: str, override: bool | None = None) -> bool:
    """Default je Plattform (tiktok/reels/shorts an, linkedin aus); ``override`` aus Markenprofil oder UI."""
    if override is not None:
        return bool(override)
    return HOOK_OVERLAY_DEFAULT.get(platform, False)


def caption_block(preset: str | captions_de.CaptionPreset, out_w: int, out_h: int, cards: int) -> dict[str, Any]:
    """Block ``captions``: Basis-Preset (Name oder Objekt für 1080x1920) auf die Ausgabegröße skaliert,
    Safe Zone als Randabstände. Ein bereits skaliertes Preset hier nicht übergeben (doppelte Skalierung)."""
    p = captions_de.scaled_preset(preset, out_w, out_h)
    return {
        "preset": p.name,
        "font": p.font,
        "font_px": p.font_px,
        "max_chars": p.max_chars,
        "baseline_y": p.baseline_y,
        "safe_zone": captions_de.safe_zone_margins(p, out_w, out_h),
        "cards": int(cards),
        "highlight": bool(p.highlight_words),
    }


def audio_block(preset: str = "master") -> dict[str, Any]:
    if preset not in AUDIO_PRESETS:
        raise ValueError(f"Unbekanntes Audio-Preset {preset!r}")
    p = AUDIO_PRESETS[preset]
    return {"preset": preset, "lufs": p["lufs"], "true_peak": p["true_peak"], "micro_fade_ms": MICRO_FADE_MS}


def normalize_segments(segments: list[dict]) -> list[dict]:
    out = []
    for s in segments:
        start, end = float(s["start"]), float(s["end"])
        if end <= start:
            raise ValueError(f"Segment mit Länge 0 oder negativ ({start:.2f} bis {end:.2f})")
        out.append({"start": round(start, 3), "end": round(end, 3), "role": str(s.get("role") or "body")})
    if not out:
        raise ValueError("Komposition ohne Segmente")
    return out


def plan_duration(plan: dict) -> float:
    return round(sum(float(s["end"]) - float(s["start"]) for s in plan["segments"]), 3)


def build_plan(
    *,
    platform: str,
    segments: list[dict],
    reframe_result: reframe.ReframeResult,
    caption_preset: str | captions_de.CaptionPreset,
    caption_cards: int,
    sources: dict[str, Any],
    aspect: str | None = None,
    src_fps: float | None = None,
    title_card: str | None = None,
    onscreen_hook: str | None = None,
    hook_overlay: bool | None = None,
    audio_preset: str = "master",
    filler_cuts: bool = False,
) -> dict[str, Any]:
    """Baut den Plan. ``caption_preset`` ist das Basis-Preset (Name oder 1080x1920-Objekt), die Skalierung passiert hier.
    ``sources`` erwartet ``storage_key``, ``transcript_version``, ``hook_version``, ``candidate_id``."""
    aspect = aspect or aspect_for_platform(platform)
    out_w, out_h = output_size(aspect)
    fps = float(src_fps) if src_fps else DEFAULT_FPS
    if (reframe_result.out_w, reframe_result.out_h) != (out_w, out_h):
        raise ValueError(
            f"Reframe wurde für {reframe_result.out_w}x{reframe_result.out_h} geplant, Plan braucht {out_w}x{out_h}"
        )
    title = (title_card or "").strip()
    hook = (onscreen_hook or "").strip()
    plan: dict[str, Any] = {
        "contract": CONTRACT,
        "platform": platform,
        "aspect": aspect,
        "output": {"width": out_w, "height": out_h, "fps": fps},
        "segments": normalize_segments(segments),
        "filler_cuts": bool(filler_cuts),
        "reframe": reframe_result.plan_block(),
        "shots": reframe_result.shots_json(),
        "captions": caption_block(caption_preset, out_w, out_h, caption_cards),
        "title_card": {"text": title, "seconds": TITLE_CARD_S} if title else None,
        "hook_overlay": {"text": hook, "seconds": HOOK_OVERLAY_S} if hook and hook_overlay_enabled(platform, hook_overlay) else None,
        "audio": audio_block(audio_preset),
        "sources": {
            "storage_key": sources.get("storage_key"),
            "transcript_version": sources.get("transcript_version"),
            "hook_version": sources.get("hook_version"),
            "candidate_id": sources.get("candidate_id"),
        },
        "versions": dict(VERSIONS),
    }
    json.dumps(plan)  # muss serialisierbar sein, sonst hier scheitern statt beim DB-Schreiben
    return plan


def plan_hash(plan: dict, hook_version: int | None, transcript_version: int | None) -> str:
    """Idempotenz-Hash aus Plan, Hook-Version und Transkriptversion (16 Hex-Zeichen)."""
    raw = json.dumps([plan, hook_version, transcript_version], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "AUDIO_PRESETS",
    "CAPTIONS_VERSION",
    "CONTRACT",
    "DEFAULT_FPS",
    "HOOK_OVERLAY_DEFAULT",
    "HOOK_OVERLAY_S",
    "MICRO_FADE_MS",
    "OUTPUT_SIZES",
    "PLATFORM_ASPECT",
    "RENDER_VERSION",
    "TITLE_CARD_S",
    "VERSIONS",
    "aspect_for_platform",
    "audio_block",
    "build_plan",
    "caption_block",
    "hook_overlay_enabled",
    "normalize_segments",
    "output_size",
    "plan_duration",
    "plan_hash",
]
