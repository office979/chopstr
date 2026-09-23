import type { BrandAssetKind, BrandCI } from "@/lib/repo/types";

/* Regeln für CI-Assets (PHASE4.md, Abschnitt 8). Ohne Server-Abhängigkeiten, auch im Client nutzbar. */

export const ASSET_KINDS: BrandAssetKind[] = ["font", "logo", "lower_third_bg", "watermark"];

export const ASSET_KIND_LABELS: Record<BrandAssetKind, string> = {
  font: "Font",
  logo: "Logo",
  lower_third_bg: "Bauchbinden-Hintergrund",
  watermark: "Wasserzeichen",
};

export const FONT_MAX_BYTES = 5 * 1024 * 1024;
export const IMAGE_MAX_BYTES = 2 * 1024 * 1024;

export const FONT_EXTENSIONS = ["ttf", "otf", "woff2"] as const;
export const IMAGE_EXTENSIONS = ["svg", "png"] as const;

export const LICENSE_TEXT = "Ich bestätige, dass ich die Lizenz für diese Datei besitze und sie für Renderings in diesem Team nutzen darf.";

export function isAssetKind(v: unknown): v is BrandAssetKind {
  return typeof v === "string" && (ASSET_KINDS as string[]).includes(v);
}

export function maxBytesFor(kind: BrandAssetKind): number {
  return kind === "font" ? FONT_MAX_BYTES : IMAGE_MAX_BYTES;
}

export function allowedExtensions(kind: BrandAssetKind): readonly string[] {
  return kind === "font" ? FONT_EXTENSIONS : IMAGE_EXTENSIONS;
}

export function extensionOf(name: string): string {
  const m = name.toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : "";
}

export function mimeFor(ext: string): string {
  switch (ext) {
    case "ttf":
      return "font/ttf";
    case "otf":
      return "font/otf";
    case "woff2":
      return "font/woff2";
    case "svg":
      return "image/svg+xml";
    case "png":
      return "image/png";
    default:
      return "application/octet-stream";
  }
}

export function fontFormat(ext: string): string {
  return ext === "woff2" ? "woff2" : ext === "otf" ? "opentype" : "truetype";
}

/* Fehlermeldung für eine Datei, null wenn sie passt */
export function validateAssetFile(kind: BrandAssetKind, name: string, size: number): string | null {
  const ext = extensionOf(name);
  if (!allowedExtensions(kind).includes(ext)) {
    return kind === "font" ? "Nur TTF, OTF oder WOFF2." : "Nur SVG oder PNG.";
  }
  if (size > maxBytesFor(kind)) {
    return kind === "font" ? "Fonts dürfen höchstens 5 MB groß sein." : "Bilder dürfen höchstens 2 MB groß sein.";
  }
  if (size === 0) return "Die Datei ist leer.";
  return null;
}

/* CI mit den Vorgabewerten (fallback Inter, Wasserzeichen aus) */
export function normalizeCI(ci: BrandCI | null | undefined): BrandCI {
  const base = ci ?? {};
  return {
    ...base,
    fonts: {
      primary_asset_id: base.fonts?.primary_asset_id ?? null,
      secondary_asset_id: base.fonts?.secondary_asset_id ?? null,
      fallback: base.fonts?.fallback ?? "Inter",
    },
    logo_asset_id: base.logo_asset_id ?? null,
    watermark: { enabled: base.watermark?.enabled ?? false },
  };
}
