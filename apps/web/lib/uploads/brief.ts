import type { ClipFormat, Platform } from "@/lib/repo/types";
import { PLATFORMS } from "@/lib/clips/labels";

/* Das kurze Briefing beim Upload (Master-Prompt Phase 5: Markenprofil und drei Briefing-Felder).
 *
 * Drei Freitexte und die Plattform, alle freiwillig, dazu das Bildformat der Clips. Gespeichert
 * wird über die vorhandenen Metadaten des Uploads (brief_audience, brief_wanted, brief_exclude,
 * platform, format), die lib/uploads/finalize.ts und upload/actions.ts in `sources.brief`
 * schreiben. */

export interface BriefInput {
  audience: string;
  wanted: string;
  exclude: string;
  platform: Platform | "";
  format: ClipFormat;
}

/* Die drei Formate in der Reihenfolge der Oberfläche. Hochformat zuerst: es ist der Standard. */
export const CLIP_FORMATS: { id: ClipFormat; name: string; hinweis: string }[] = [
  { id: "9:16", name: "Hochformat", hinweis: "9:16 für TikTok, Reels, Shorts" },
  { id: "16:9", name: "Querformat", hinweis: "16:9 für YouTube und Website" },
  { id: "both", name: "Beide", hinweis: "Jeder Clip in beiden Formaten" },
];

export const DEFAULT_CLIP_FORMAT: ClipFormat = "9:16";

/* Unbekannt oder leer heisst Hochformat, wie vor der Formatwahl. */
export function parseClipFormat(raw: string | undefined | null): ClipFormat {
  return CLIP_FORMATS.some((f) => f.id === raw) ? (raw as ClipFormat) : DEFAULT_CLIP_FORMAT;
}

/* Ein Briefing ist ein Satz, kein Dokument. Mehr würde im Prompt nur Platz kosten. */
export const BRIEF_MAX_CHARS = 300;

/* Vorbelegung aus dem Markenprofil. Das Profil kennt nur die Standard-Plattform; Zielgruppe,
 * Wünsche und Ausschlüsse hat es nicht und bleiben deshalb leer, statt geraten zu werden. */
export function briefDefaults(profile: { platform: Platform } | null | undefined): BriefInput {
  return { audience: "", wanted: "", exclude: "", platform: profile?.platform ?? "", format: DEFAULT_CLIP_FORMAT };
}

/* Die Felder als Upload-Metadaten: nur, was ausgefüllt ist, getrimmt und gekürzt. Eine unbekannte
 * Plattform fällt weg, wie in finalize.parsePlatform. Das Format geht immer mit. */
export function briefMetadata(input: BriefInput): Record<string, string> {
  const out: Record<string, string> = {};
  const text = (v: string) => v.replace(/\s+/g, " ").trim().slice(0, BRIEF_MAX_CHARS);
  if (text(input.audience)) out.brief_audience = text(input.audience);
  if (text(input.wanted)) out.brief_wanted = text(input.wanted);
  if (text(input.exclude)) out.brief_exclude = text(input.exclude);
  if (input.platform && (PLATFORMS as string[]).includes(input.platform)) out.platform = input.platform;
  out.format = parseClipFormat(input.format);
  return out;
}
