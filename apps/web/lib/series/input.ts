import { PLATFORMS, isHookPattern, isPlatform } from "@/lib/clips/labels";
import { STRUCTURE_LABELS } from "@/lib/candidates/labels";
import { PRESETS } from "@/lib/clips/presets";
import type { SeriesCadence, SeriesInput, SeriesRules } from "@/lib/repo/types-publishing";

/* Eingabe einer Serie aus dem Formular prüfen (Name, Kadenz, Regeln). Ohne Server-Abhängigkeiten. */

export const CADENCES: SeriesCadence[] = ["weekly", "biweekly", "monthly", "none"];
const STRUCTURE_ORDER = Object.keys(STRUCTURE_LABELS);
const CAPTION_PRESETS = Object.keys(PRESETS);

export function parseSeriesInput(body: Record<string, unknown>): { input: SeriesInput } | { error: string } {
  const name = typeof body.name === "string" ? body.name.trim().slice(0, 120) : "";
  if (name.length < 2) return { error: "Bitte einen Namen mit mindestens zwei Zeichen angeben." };
  const cadence = CADENCES.includes(body.cadence as SeriesCadence) ? (body.cadence as SeriesCadence) : "weekly";
  const rawRules = (body.rules && typeof body.rules === "object" ? body.rules : {}) as Record<string, unknown>;
  const rules: SeriesRules = {
    structure: (STRUCTURE_ORDER as string[]).includes(String(rawRules.structure)) ? (rawRules.structure as SeriesRules["structure"]) : null,
    platforms: Array.isArray(rawRules.platforms) ? rawRules.platforms.filter(isPlatform) : PLATFORMS,
    caption_preset: (CAPTION_PRESETS as string[]).includes(String(rawRules.caption_preset)) ? (rawRules.caption_preset as SeriesRules["caption_preset"]) : null,
    hook_patterns: Array.isArray(rawRules.hook_patterns) ? rawRules.hook_patterns.filter(isHookPattern) : [],
    cover_template: typeof rawRules.cover_template === "string" && rawRules.cover_template.trim() ? rawRules.cover_template.trim().slice(0, 120) : null,
  };
  return {
    input: {
      name,
      description: typeof body.description === "string" && body.description.trim() ? body.description.trim().slice(0, 1000) : null,
      brand_profile_id: typeof body.brand_profile_id === "string" && body.brand_profile_id ? body.brand_profile_id : null,
      cadence,
      rules,
    },
  };
}

