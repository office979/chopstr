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
  "9:16": "Hochformat",
  "4:5": "Fast quadratisch",
  "1:1": "Quadratisch",
  "16:9": "Querformat",
};

export const CLIP_STATUS_LABELS: Record<ClipStatus, string> = {
  draft: "Noch nicht erstellt",
  approved: "Freigegeben",
  rendering: "Wird erstellt",
  rendered: "Fertig",
  exported: "Heruntergeladen",
  failed: "Hat nicht geklappt",
  deleted: "Gelöscht",
};

export const PATTERN_ORDER: HookPattern[] = ["identity_call", "contrarian", "open_loop", "results_first", "mistake_warning"];

export const PATTERN_LABELS: Record<HookPattern, string> = {
  identity_call: "Direkt angesprochen",
  contrarian: "Widerspruch",
  open_loop: "Neugier wecken",
  results_first: "Ergebnis zuerst",
  mistake_warning: "Vor Fehler warnen",
};

export function patternLabel(p: HookPattern | null | undefined): string {
  return p ? (PATTERN_LABELS[p] ?? p) : "Ohne Muster";
}

export const RENDER_STAGES: RenderStage[] = ["copy", "reframe", "captions", "encode", "provenance"];

export const RENDER_STAGE_LABELS: Record<RenderStage, string> = {
  copy: "Texte schreiben",
  reframe: "Bildausschnitt wählen",
  captions: "Untertitel setzen",
  encode: "Video zusammenbauen",
  provenance: "Echtheitssiegel",
};

/* Werbekennzeichnung nach Land (Spiegel von copy_de.AD_LABELS) */
export const AD_LABELS: Record<Country, string> = { DE: "Anzeige", AT: "Werbung", CH: "Werbung" };

export function isPlatform(v: unknown): v is Platform {
  return typeof v === "string" && (PLATFORMS as string[]).includes(v);
}

export function isHookPattern(v: unknown): v is HookPattern {
  return typeof v === "string" && (PATTERN_ORDER as string[]).includes(v);
}

/* Lautheit im DACH-Format: „-16,0 LUFS, -1,5 dBTP“. Nur für „Details für Profis“. */
export function formatLoudness(lufs: number, dbtp: number): string {
  const f = (n: number) => n.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${f(lufs)} LUFS, ${f(dbtp)} dBTP`;
}

/* Zielwerte der Master-Edition (docs/ENTSCHEIDUNGEN.md, A1): -16 LUFS, -1,5 dBTP */
const LOUDNESS_TARGET_LUFS = -16;
const LOUDNESS_TOLERANCE_LUFS = 1;
const TRUE_PEAK_CEILING_DBTP = -1;

/* Lautheit in Alltagssprache. Die Zahlen stehen in „Details für Profis“. */
export function loudnessPlain(lufs: number, dbtp: number): string {
  if (dbtp > TRUE_PEAK_CEILING_DBTP) return "Ton übersteuert stellenweise";
  if (Math.abs(lufs - LOUDNESS_TARGET_LUFS) > LOUDNESS_TOLERANCE_LUFS) {
    return lufs < LOUDNESS_TARGET_LUFS ? "Ton ist eher leise" : "Ton ist eher laut";
  }
  return "Lautstärke passt";
}

export function formatClipDuration(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "Dauer offen";
  return `${s.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
}

/* Medien-URL aus NEXT_PUBLIC_MEDIA_BASE_URL + Key; ohne Basis oder Key (Demo) null */
export function mediaUrl(base: string | null | undefined, key: string | null | undefined): string | null {
  if (!key) return null;
  /* Ein Schluessel, der schon eine vollstaendige Adresse ist, wird durchgereicht. Das braucht der
   * Demo-Modus, wo Dateien aus public/ kommen und es gar keinen Speicher gibt. */
  if (/^(https?:)?\/\//.test(key) || key.startsWith("/")) return key;
  if (!base) return null;
  return `${base.replace(/\/$/, "")}/${key}`;
}

/* Medien-URL für die Gast-Freigabe: im lokalen Modus (MEDIA_MODE=local) prüft /api/media das Token ?t=,
 * sonst (CDN, MinIO) bleibt die URL wie sie ist */
export function guestMediaUrl(base: string | null | undefined, key: string | null | undefined, token: string | null): string | null {
  const url = mediaUrl(base, key);
  if (!url || !token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}t=${encodeURIComponent(token)}`;
}
