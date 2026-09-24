"""Render-Plan ``render_plan_v1`` (Vertrag ``packages/schema/CLIPS.md``): deterministisch, vollständig, JSON.

Aus dem Plan lässt sich der Render wiederholen: Segmente, Ausgabegröße und Bildrate, Reframe-Ergebnis
und Shots, Caption-Preset mit Safe Zones (für andere Größen als 9:16 proportional umgerechnet),
Titelkarte, Hook-Overlay, Audio-Preset, Quellen und Modulversionen. Keine Umgebungswerte (Fontpfade,
Filterverfügbarkeit) im Plan; die gehören zum Render-Ergebnis.

Phase 5c: bei ``reframe.strategy = slide_pip`` beginnt die Caption-Safe-Zone unter der Folie (``pip.y`` plus
Abstand), damit Captions, Titelkarte und Hook-Overlay in der Sprecherfläche liegen. ``captions.text_field``
steht nur im Plan, wenn die normalisierte Form (``text_norm``) eingebrannt wird; so bleiben Hashes bestehender
Pläne stabil.
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
# Langsamer Push-in je Einstellung: 8 Prozent über die Länge der Einstellung, linear.
# Nur bei umgerahmten Clips, also wenn das Ausgabeformat vom Format der Quelle abweicht. Behält der
# Clip das Format der Quelle (Hochformat-Schalter aus), bleibt das Bild unangetastet.
ZOOM_TO = 1.08
ZOOM_MIN_SHOT_S = 1.2
HOOK_OVERLAY_DEFAULT = {"tiktok": True, "reels": True, "shorts": True, "linkedin": False}
AUDIO_PRESETS: dict[str, dict[str, float]] = {
    "master": {"lufs": -16.0, "true_peak": -1.5},
    "legacy_social": {"lufs": -14.0, "true_peak": -1.0},
}
DEFAULT_FPS = 25.0
VERSIONS = {"captions_de": CAPTIONS_VERSION, "render": RENDER_VERSION, "reframe": reframe.REFRAME_VERSION}
WATERMARK_DEFAULTS: dict[str, Any] = {"enabled": False, "position": "bottom_right", "opacity": 0.85, "width_ratio": 0.18}


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


def caption_block(
    preset: str | captions_de.CaptionPreset,
    out_w: int,
    out_h: int,
    cards: int,
    font: str | None = None,
    min_top: int | None = None,
    text_field: str | None = None,
    bereits_skaliert: bool = False,
) -> dict[str, Any]:
    """Block ``captions``: Basis-Preset (Name oder Objekt für 1080x1920) auf die Ausgabegröße skaliert,
    Safe Zone als Randabstände. Ein bereits skaliertes Preset hier nicht übergeben (doppelte Skalierung).
    ``font`` ist der echte Familienname des Marken-Fonts; ohne ihn gilt der Preset-Font (Inter).
    ``min_top`` schiebt die Oberkante der Safe Zone nach unten (Folie oben bei ``slide_pip``).
    ``text_field = "text_norm"`` wird als Feld eingetragen; ``"text"`` ist der Default und bleibt weg."""
    p = preset if bereits_skaliert and isinstance(preset, captions_de.CaptionPreset) else captions_de.scaled_preset(preset, out_w, out_h)
    safe = captions_de.safe_zone_margins(p, out_w, out_h)
    if min_top is not None:
        safe["top"] = max(int(safe["top"]), int(min_top))
    # Alles, was das Bild verändert, gehört in den Block. Der Plan ist die Beschreibung dessen, was
    # gerendert wurde, und zugleich der Idempotenz-Schlüssel: was hier fehlt, ändert den Hash nicht,
    # und eine Änderung daran bliebe folgenlos, weil der Render als „schon vorhanden" übersprungen
    # würde. Genau das ist passiert, als der Block nur die Preset-Vorgaben trug: eine andere
    # Textfarbe kam nie im Clip an.
    block = {
        "preset": p.name,
        "font": (font or "").strip() or p.font,
        "font_px": p.font_px,
        "max_chars": p.max_chars,
        "baseline_y": p.baseline_y,
        "safe_zone": safe,
        "cards": int(cards),
        "highlight": bool(p.highlight_words),
        "bold": bool(p.bold),
        "all_caps": bool(p.all_caps),
        "max_lines": int(p.max_lines),
        "words_per_card": p.words_per_card,
        "outline_px": int(p.outline_px),
        "box": bool(p.box),
        "base_color": p.base_color,
        "highlight_color": p.highlight_color,
    }
    if text_field and text_field != "text":
        block["text_field"] = captions_de.check_text_field(text_field)
    return block


def brand_block(brand: dict[str, Any] | None = None) -> dict[str, Any]:
    """Block ``brand``: Font- und Logo-Asset des Markenprofils plus Wasserzeichen-Einstellung (keine Pfade)."""
    b = dict(brand or {})
    wm = {**WATERMARK_DEFAULTS, **dict(b.get("watermark") or {})}
    wm["enabled"] = bool(wm["enabled"]) and bool(b.get("logo_asset_id"))
    wm["opacity"] = min(1.0, max(0.0, float(wm["opacity"])))
    wm["width_ratio"] = min(0.5, max(0.05, float(wm["width_ratio"])))
    return {
        "font_asset_id": str(b["font_asset_id"]) if b.get("font_asset_id") else None,
        "logo_asset_id": str(b["logo_asset_id"]) if b.get("logo_asset_id") else None,
        "watermark": wm,
    }


def motion_block(reframe_result: reframe.ReframeResult, out_w: int, out_h: int) -> dict[str, Any]:
    """Block ``motion``: langsamer Push-in je Einstellung.

    Aktiv nur, wenn umgerahmt wird, das Ausgabeformat also vom Format der Quelle abweicht. Behält der
    Clip das Format der Quelle, bleibt das Bild unangetastet und es gibt keinen Zoom. Einstellungen
    unter ``min_shot_s`` bleiben still, damit kurze Schnitte nicht zappeln."""
    src_w, src_h = reframe_result.src_w, reframe_result.src_h
    same_format = bool(src_w and src_h) and abs((src_w / src_h) - (out_w / out_h)) < 0.01
    return {
        "zoom_to": 1.0 if same_format else ZOOM_TO,
        "min_shot_s": ZOOM_MIN_SHOT_S,
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
    caption_preset_skaliert: bool = False,
    sources: dict[str, Any],
    aspect: str | None = None,
    src_fps: float | None = None,
    title_card: str | None = None,
    onscreen_hook: str | None = None,
    hook_overlay: bool | None = None,
    audio_preset: str = "master",
    filler_cuts: bool = False,
    caption_font: str | None = None,
    brand: dict[str, Any] | None = None,
    caption_text_field: str | None = None,
) -> dict[str, Any]:
    """Baut den Plan. ``caption_preset`` ist das Basis-Preset (Name oder 1080x1920-Objekt), die Skalierung passiert hier.
    ``sources`` erwartet ``storage_key``, ``transcript_version``, ``hook_version``, ``candidate_id``.
    ``caption_font`` ist der Familienname des Marken-Fonts, ``brand`` die Asset-IDs und das Wasserzeichen.
    ``caption_text_field`` (``text`` | ``text_norm``) wählt die Wortform der Captions (Schweizerdeutsch-Beta)."""
    aspect = aspect or aspect_for_platform(platform)
    out_w, out_h = output_size(aspect)
    fps = float(src_fps) if src_fps else DEFAULT_FPS
    if (reframe_result.out_w, reframe_result.out_h) != (out_w, out_h):
        raise ValueError(
            f"Reframe wurde für {reframe_result.out_w}x{reframe_result.out_h} geplant, Plan braucht {out_w}x{out_h}"
        )
    title = (title_card or "").strip()
    hook = (onscreen_hook or "").strip()
    caption_top: int | None = None
    if reframe_result.strategy == "slide_pip" and reframe_result.pip is not None:
        caption_top = int(reframe_result.pip["y"]) + int(round(out_h * reframe.SLIDE_CAPTION_GAP_RATIO))
    plan: dict[str, Any] = {
        "contract": CONTRACT,
        "platform": platform,
        "aspect": aspect,
        "output": {"width": out_w, "height": out_h, "fps": fps},
        "segments": normalize_segments(segments),
        "filler_cuts": bool(filler_cuts),
        "reframe": reframe_result.plan_block(),
        "shots": reframe_result.shots_json(),
        "motion": motion_block(reframe_result, out_w, out_h),
        "captions": caption_block(
            caption_preset, out_w, out_h, caption_cards, caption_font, caption_top, caption_text_field, caption_preset_skaliert
        ),
        "title_card": {"text": title, "seconds": TITLE_CARD_S} if title else None,
        "hook_overlay": {"text": hook, "seconds": HOOK_OVERLAY_S} if hook and hook_overlay_enabled(platform, hook_overlay) else None,
        "audio": audio_block(audio_preset),
        "brand": brand_block(brand),
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
    "WATERMARK_DEFAULTS",
    "aspect_for_platform",
    "audio_block",
    "brand_block",
    "build_plan",
    "caption_block",
    "hook_overlay_enabled",
    "normalize_segments",
    "output_size",
    "plan_duration",
    "plan_hash",
]
