import type { Platform } from "@/lib/repo/types";
import { PLATFORMS } from "@/lib/clips/labels";

/* Das kurze Briefing beim Upload (Master-Prompt Phase 5: Markenprofil und drei Briefing-Felder).
 *
 * Drei Freitexte und die Plattform, alle freiwillig. Gespeichert wird über die vorhandenen
 * Metadaten des Uploads (brief_audience, brief_wanted, brief_exclude, platform), die
 * lib/uploads/finalize.ts und upload/actions.ts schon in `sources.brief` schreiben. */

export interface BriefInput {
  audience: string;
  wanted: string;
  exclude: string;
  platform: Platform | "";
}

/* Ein Briefing ist ein Satz, kein Dokument. Mehr würde im Prompt nur Platz kosten. */
export const BRIEF_MAX_CHARS = 300;

/* Vorbelegung aus dem Markenprofil. Das Profil kennt nur die Standard-Plattform; Zielgruppe,
 * Wünsche und Ausschlüsse hat es nicht und bleiben deshalb leer, statt geraten zu werden. */
export function briefDefaults(profile: { platform: Platform } | null | undefined): BriefInput {
  return { audience: "", wanted: "", exclude: "", platform: profile?.platform ?? "" };
}

/* Die Felder als Upload-Metadaten: nur, was ausgefüllt ist, getrimmt und gekürzt. Eine unbekannte
 * Plattform fällt weg, wie in finalize.parsePlatform. */
export function briefMetadata(input: BriefInput): Record<string, string> {
  const out: Record<string, string> = {};
  const text = (v: string) => v.replace(/\s+/g, " ").trim().slice(0, BRIEF_MAX_CHARS);
  if (text(input.audience)) out.brief_audience = text(input.audience);
  if (text(input.wanted)) out.brief_wanted = text(input.wanted);
  if (text(input.exclude)) out.brief_exclude = text(input.exclude);
  if (input.platform && (PLATFORMS as string[]).includes(input.platform)) out.platform = input.platform;
  return out;
}
