import { PATTERN_ORDER } from "@/lib/clips/labels";
import type { HookPattern, HookVariant } from "@/lib/repo/types";
import type { HookPatternStat } from "@/lib/repo/types-publishing";
import { Rng, seedFromString } from "./random";

/* Port von workers/chopstr_worker/learning.py `thompson_order`: Beta(chosen + 1, shown - chosen + 1) je Muster,
 * multipliziert mit dem Reward-Mittel (1,0 ohne Daten, auf 3 gedeckelt). Muster ohne Statistik zählen als ungezeigt
 * (reine Exploration). Deterministisch über einen Seed je Clip. */

const REWARD_CAP = 3.0;

export function thompsonOrder(stats: HookPatternStat[], seed: number): HookPattern[] {
  const rng = new Rng(seed);
  const byPattern = new Map(stats.map((s) => [s.pattern, s]));
  const scored: { score: number; pattern: HookPattern }[] = [];
  for (const p of PATTERN_ORDER) {
    const s = byPattern.get(p);
    const shown = Math.max(0, s?.shown ?? 0);
    const chosen = Math.max(0, Math.min(shown, s?.chosen ?? 0));
    const sample = rng.beta(chosen + 1, shown - chosen + 1);
    const n = s?.reward_n ?? 0;
    const factor = n > 0 ? Math.min(REWARD_CAP, (s?.reward_sum ?? 0) / n) : 1.0;
    scored.push({ score: sample * factor, pattern: p });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.map((s) => s.pattern);
}

export interface OrderedVariants {
  variants: HookVariant[];
  /* true, wenn die Reihenfolge aus der Lernschleife stammt (Statistik vorhanden) */
  learned: boolean;
  order: HookPattern[];
}

/* Fünf Varianten nach Thompson-Reihenfolge sortieren; ohne Statistik bleibt die Standardreihenfolge */
export function orderVariants(variants: HookVariant[], stats: HookPatternStat[], clipId: string): OrderedVariants {
  const hasData = stats.some((s) => s.shown > 0 || s.reward_n > 0);
  if (!hasData || variants.length === 0) return { variants, learned: false, order: PATTERN_ORDER };
  const order = thompsonOrder(stats, seedFromString(clipId));
  const rank = new Map(order.map((p, i) => [p, i]));
  const sorted = [...variants].sort((a, b) => (rank.get(a.pattern) ?? 99) - (rank.get(b.pattern) ?? 99));
  return { variants: sorted, learned: true, order };
}
