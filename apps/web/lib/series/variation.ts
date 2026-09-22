import type { Clip, CaptionPreset, CandidateStructure, HookPattern } from "@/lib/repo/types";
import type { Series, SeriesCadence } from "@/lib/repo/types-publishing";
import { PLATFORM_DEFAULT_PRESET } from "@/lib/clips/presets";

/* Content-Serien (PHASE5.md, Whitepaper 3.4): Variations-Prüfung und Kalender-Slots. Ohne Server-Abhängigkeiten. */

export interface ClipFeatures {
  clip_id: string;
  caption_preset: CaptionPreset | null;
  hook_pattern: HookPattern | null;
  structure: CandidateStructure | null;
  duration_s: number | null;
}

export const FEATURE_LABELS = { caption_preset: "Caption-Preset", hook_pattern: "Hook-Muster", structure: "Struktur", duration: "Länge (±15 %)" } as const;
export type FeatureKey = keyof typeof FEATURE_LABELS;

export function clipFeaturesFor(clip: Clip, hookPattern: HookPattern | null, structure: CandidateStructure | null): ClipFeatures {
  return {
    clip_id: clip.id,
    caption_preset: clip.render_plan?.captions.preset ?? PLATFORM_DEFAULT_PRESET[clip.platform] ?? null,
    hook_pattern: hookPattern,
    structure,
    duration_s: clip.duration_s ?? (clip.composition?.length ? clip.composition.reduce((acc, s) => acc + (s.end - s.start), 0) : null),
  };
}

export interface SimilarityHit {
  clip_id: string;
  matches: FeatureKey[];
}

export interface VariationResult {
  too_similar: boolean;
  compared: number;
  hits: SimilarityHit[];
  message: string | null;
}

export const SIMILARITY_THRESHOLD = 3;
export const COMPARE_LAST = 9;

/* Vergleich mit den letzten 9 Clips der Serie: drei oder mehr gleiche Merkmale → Warnung */
export function checkVariation(candidate: ClipFeatures, previous: ClipFeatures[]): VariationResult {
  const recent = previous.filter((p) => p.clip_id !== candidate.clip_id).slice(-COMPARE_LAST);
  const hits: SimilarityHit[] = [];
  for (const prev of recent) {
    const matches: FeatureKey[] = [];
    if (candidate.caption_preset && candidate.caption_preset === prev.caption_preset) matches.push("caption_preset");
    if (candidate.hook_pattern && candidate.hook_pattern === prev.hook_pattern) matches.push("hook_pattern");
    if (candidate.structure && candidate.structure === prev.structure) matches.push("structure");
    if (candidate.duration_s != null && prev.duration_s != null && prev.duration_s > 0 && Math.abs(candidate.duration_s - prev.duration_s) / prev.duration_s <= 0.15) matches.push("duration");
    if (matches.length >= SIMILARITY_THRESHOLD) hits.push({ clip_id: prev.clip_id, matches });
  }
  const tooSimilar = hits.length > 0;
  return {
    too_similar: tooSimilar,
    compared: recent.length,
    hits,
    message: tooSimilar
      ? `Zu ähnlich, Variante ziehen: ${hits.length} der letzten ${recent.length} Clips teilen ${hits[0].matches.map((m) => FEATURE_LABELS[m]).join(", ")}.`
      : null,
  };
}

/* Kalender: Slot-Index relativ zum Anker (created_at der Serie) nach Kadenz */
export const CADENCE_LABELS: Record<SeriesCadence, string> = { weekly: "wöchentlich", biweekly: "alle zwei Wochen", monthly: "monatlich", none: "ohne Rhythmus" };

export function slotStart(series: Pick<Series, "created_at" | "cadence">, index: number): Date {
  const anchor = new Date(series.created_at);
  anchor.setHours(0, 0, 0, 0);
  const d = new Date(anchor);
  if (series.cadence === "weekly") d.setDate(d.getDate() + index * 7);
  else if (series.cadence === "biweekly") d.setDate(d.getDate() + index * 14);
  else if (series.cadence === "monthly") d.setMonth(d.getMonth() + index);
  else d.setDate(d.getDate() + index * 7);
  return d;
}

export function currentSlotIndex(series: Pick<Series, "created_at" | "cadence">, now = new Date()): number {
  const anchor = new Date(series.created_at);
  anchor.setHours(0, 0, 0, 0);
  const days = Math.floor((now.getTime() - anchor.getTime()) / 86_400_000);
  if (series.cadence === "weekly") return Math.floor(days / 7);
  if (series.cadence === "biweekly") return Math.floor(days / 14);
  if (series.cadence === "monthly") return (now.getFullYear() - anchor.getFullYear()) * 12 + (now.getMonth() - anchor.getMonth());
  return Math.floor(days / 7);
}

export interface CalendarSlot {
  index: number;
  start: string;
  past: boolean;
  current: boolean;
  clip_ids: string[];
  /* Lücke: vergangener Slot ohne Clip (Orange) */
  gap: boolean;
}

export function calendarSlots(series: Series, clips: { id: string; series_index: number | null }[], now = new Date()): CalendarSlot[] {
  const cur = currentSlotIndex(series, now);
  const from = Math.max(0, cur - 8);
  const out: CalendarSlot[] = [];
  for (let i = from; i <= cur + 8; i += 1) {
    const ids = clips.filter((c) => c.series_index === i).map((c) => c.id);
    const past = i < cur;
    out.push({ index: i, start: slotStart(series, i).toISOString(), past, current: i === cur, clip_ids: ids, gap: past && ids.length === 0 });
  }
  return out;
}
