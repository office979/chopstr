import type { Aspect, CaptionPreset, Platform } from "@/lib/repo/types";

/* Caption-Presets: Spiegel von workers/chopstr_worker/pipeline/captions_de.PRESETS (Pixel bei 1080×1920).
 * Safe Zones: TikTok oben 108, unten 320 (y = 1600), links 60, rechts 120 (x = 960). Reels 210 bis 1610.
 * Shorts 120 bis 1620. LinkedIn 120 bis 1700, 80 Rand; bei 4:5 proportional skaliert. */

export const OUTPUT_W = 1080;
export const OUTPUT_H = 1920;
const AVG_CHAR_EM = 0.56;
export const MAX_CPS = 17;

export interface SafeZone {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface CaptionPresetDef {
  name: CaptionPreset;
  safe: SafeZone;
  font: string;
  font_px: number;
  bold: boolean;
  max_lines: number;
  outline_px: number;
  box: boolean;
  bottom_margin_px: number;
  highlight_words: boolean;
  /* nur Anzeige in der stummen Vorschau */
  animated: boolean;
}

export const PRESETS: Record<CaptionPreset, CaptionPresetDef> = {
  tiktok_bold: {
    name: "tiktok_bold",
    safe: { top: 108, bottom: OUTPUT_H - 320, left: 60, right: OUTPUT_W - 120 },
    font: "Inter",
    font_px: 78,
    bold: true,
    max_lines: 2,
    outline_px: 5,
    box: false,
    bottom_margin_px: 260,
    highlight_words: true,
    animated: true,
  },
  reels_clean: {
    name: "reels_clean",
    safe: { top: 210, bottom: 1610, left: 60, right: OUTPUT_W - 120 },
    font: "Inter",
    font_px: 66,
    bold: true,
    max_lines: 2,
    outline_px: 3,
    box: false,
    bottom_margin_px: 260,
    highlight_words: true,
    animated: true,
  },
  shorts_clean: {
    name: "shorts_clean",
    safe: { top: 120, bottom: 1620, left: 60, right: OUTPUT_W - 120 },
    font: "Inter",
    font_px: 66,
    bold: true,
    max_lines: 2,
    outline_px: 3,
    box: false,
    bottom_margin_px: 260,
    highlight_words: true,
    animated: true,
  },
  linkedin_static: {
    name: "linkedin_static",
    safe: { top: 120, bottom: 1700, left: 80, right: OUTPUT_W - 80 },
    font: "Inter",
    font_px: 54,
    bold: false,
    max_lines: 2,
    outline_px: 0,
    box: true,
    bottom_margin_px: 200,
    highlight_words: false,
    animated: false,
  },
  corporate_third: {
    name: "corporate_third",
    safe: { top: 120, bottom: 1700, left: 80, right: OUTPUT_W - 80 },
    font: "Inter",
    font_px: 48,
    bold: false,
    max_lines: 2,
    outline_px: 0,
    box: true,
    bottom_margin_px: 160,
    highlight_words: false,
    animated: false,
  },
};

export const PLATFORM_DEFAULT_PRESET: Record<Platform, CaptionPreset> = {
  tiktok: "tiktok_bold",
  reels: "reels_clean",
  shorts: "shorts_clean",
  linkedin: "linkedin_static",
};

export const PLATFORM_ASPECT: Record<Platform, Aspect> = {
  tiktok: "9:16",
  reels: "9:16",
  shorts: "9:16",
  linkedin: "4:5",
};

/* Hochformat-Schalter (Standard an): ist er aus, behält der Clip das Format der Quelle.
 * Gewählt wird das nächstgelegene der vier unterstützten Seitenverhältnisse, damit Renderer,
 * Safe Zones und Caption-Presets weiterhin definierte Größen bekommen. */
const ASPECT_RATIOS: { aspect: Aspect; ratio: number }[] = [
  { aspect: "9:16", ratio: 9 / 16 },
  { aspect: "4:5", ratio: 4 / 5 },
  { aspect: "1:1", ratio: 1 },
  { aspect: "16:9", ratio: 16 / 9 },
];

export function aspectForSource(width: number | null | undefined, height: number | null | undefined): Aspect | null {
  if (!width || !height || width <= 0 || height <= 0) return null;
  const ratio = width / height;
  return ASPECT_RATIOS.reduce((best, c) => (Math.abs(c.ratio - ratio) < Math.abs(best.ratio - ratio) ? c : best)).aspect;
}

/* Zielformat eines Clips: Plattform-Standard, oder das Format der Quelle, wenn der Schalter aus ist.
 * Fehlen die Maße der Quelle (noch nicht geprüft), bleibt es beim Plattform-Standard. */
export function aspectFor(
  platform: Platform,
  source: { width?: number | null; height?: number | null } | null,
  keepSourceAspect = false,
): Aspect {
  if (!keepSourceAspect) return PLATFORM_ASPECT[platform];
  return aspectForSource(source?.width, source?.height) ?? PLATFORM_ASPECT[platform];
}

export const ASPECT_SIZE: Record<Aspect, { width: number; height: number }> = {
  "9:16": { width: 1080, height: 1920 },
  "4:5": { width: 1080, height: 1350 },
  "1:1": { width: 1080, height: 1080 },
  "16:9": { width: 1920, height: 1080 },
};

export function presetFor(nameOrPlatform: CaptionPreset | Platform | string): CaptionPresetDef {
  if (nameOrPlatform in PRESETS) return PRESETS[nameOrPlatform as CaptionPreset];
  const byPlatform = PLATFORM_DEFAULT_PRESET[nameOrPlatform as Platform];
  return PRESETS[byPlatform ?? "linkedin_static"];
}

/* Zeichen pro Zeile aus Schriftgröße (18 bei 78 px auf 900 px Breite) */
export function maxChars(fontPx: number, safeWidth: number): number {
  return Math.max(8, Math.floor(safeWidth / (Math.max(fontPx, 1) * AVG_CHAR_EM)));
}

export interface PresetLayout {
  preset: CaptionPresetDef;
  width: number;
  height: number;
  safe: SafeZone;
  font_px: number;
  max_chars: number;
  baseline_y: number;
}

/* Layout im Ausgabeformat: 9:16 direkt, andere Seitenverhältnisse proportional in der Höhe skaliert */
export function layoutFor(preset: CaptionPresetDef, aspect: Aspect): PresetLayout {
  const { width, height } = ASPECT_SIZE[aspect];
  const k = height / OUTPUT_H;
  const kx = width / OUTPUT_W;
  const safe: SafeZone = {
    top: Math.round(preset.safe.top * k),
    bottom: Math.round(preset.safe.bottom * k),
    left: Math.round(preset.safe.left * kx),
    right: Math.round(preset.safe.right * kx),
  };
  const fontPx = Math.round(preset.font_px * Math.min(k, 1) * (k < 1 ? 1.15 : 1));
  return {
    preset,
    width,
    height,
    safe,
    font_px: fontPx,
    max_chars: maxChars(fontPx, safe.right - safe.left),
    baseline_y: Math.round((preset.safe.bottom - preset.bottom_margin_px) * k),
  };
}
