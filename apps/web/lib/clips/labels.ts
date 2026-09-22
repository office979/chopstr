import type { Aspect, ClipStatus, Country, HookPattern, Platform, RenderStage } from "@/lib/repo/types";

/* Deutsche Labels für Clips, Plattformen, Hook-Muster und Render-Schritte (nur Anzeige) */

export const PLATFORMS: Platform[] = ["tiktok", "reels", "shorts", "linkedin"];

export const PLATFORM_LABELS: Record<Platform, string> = {
  tiktok: "TikTok",
  reels: "Reels",
  shorts: "Shorts",
  linkedin: "LinkedIn",
};

export const ASPECT_LABELS: Record<Aspect, string> = {
  "9:16": "9:16",
  "4:5": "4:5",
  "1:1": "1:1",
  "16:9": "16:9",
};

export const CLIP_STATUS_LABELS: Record<ClipStatus, string> = {
  draft: "Entwurf",
  approved: "Freigegeben",
  rendering: "Wird gerendert",
  rendered: "Gerendert",
  exported: "Exportiert",
  failed: "Fehlgeschlagen",
  deleted: "Gelöscht",
};

export const PATTERN_ORDER: HookPattern[] = ["identity_call", "contrarian", "open_loop", "results_first", "mistake_warning"];

export const PATTERN_LABELS: Record<HookPattern, string> = {
  identity_call: "Identitäts-Anruf",
  contrarian: "Gegenposition",
  open_loop: "Offene Schleife",
  results_first: "Ergebnis zuerst",
  mistake_warning: "Fehler-Warnung",
};

export function patternLabel(p: HookPattern | null | undefined): string {
  return p ? (PATTERN_LABELS[p] ?? p) : "Ohne Muster";
}

export const RENDER_STAGES: RenderStage[] = ["copy", "reframe", "captions", "encode", "provenance"];

export const RENDER_STAGE_LABELS: Record<RenderStage, string> = {
  copy: "Copy",
  reframe: "Reframe",
  captions: "Captions",
  encode: "Encode",
  provenance: "Provenienz",
};

/* Werbekennzeichnung nach Land (Spiegel von copy_de.AD_LABELS) */
export const AD_LABELS: Record<Country, string> = { DE: "Anzeige", AT: "Werbung", CH: "Werbung" };

export function isPlatform(v: unknown): v is Platform {
  return typeof v === "string" && (PLATFORMS as string[]).includes(v);
}

export function isHookPattern(v: unknown): v is HookPattern {
  return typeof v === "string" && (PATTERN_ORDER as string[]).includes(v);
}

/* Lautheit im DACH-Format: „-16,0 LUFS, -1,5 dBTP“ */
export function formatLoudness(lufs: number, dbtp: number): string {
  const f = (n: number) => n.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${f(lufs)} LUFS, ${f(dbtp)} dBTP`;
}

export function formatClipDuration(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "Dauer offen";
  return `${s.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
}

/* Medien-URL aus NEXT_PUBLIC_MEDIA_BASE_URL + Key; ohne Basis oder Key (Demo) null */
export function mediaUrl(base: string | null | undefined, key: string | null | undefined): string | null {
  if (!base || !key) return null;
  return `${base.replace(/\/$/, "")}/${key.replace(/^\//, "")}`;
}

/* Medien-URL für die Gast-Freigabe: im lokalen Modus (MEDIA_MODE=local) prüft /api/media das Token ?t=,
 * sonst (CDN, MinIO) bleibt die URL wie sie ist */
export function guestMediaUrl(base: string | null | undefined, key: string | null | undefined, token: string | null): string | null {
  const url = mediaUrl(base, key);
  if (!url || !token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}t=${encodeURIComponent(token)}`;
}
