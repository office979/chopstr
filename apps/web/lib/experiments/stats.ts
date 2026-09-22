import type { Publication, PerformanceFeedback, Experiment } from "@/lib/repo/types-publishing";
import { Rng, seedFromString } from "./random";

/* Hook-A/B (PHASE5.md): Entscheidung frühestens 48 h nach beiden Publikationen und ab min_exposure Views je Variante.
 * Konfidenz = Posterior P(A > B) über Beta-Verteilungen der Folgequote (follows / views), Monte-Carlo mit 2.000
 * Ziehungen und deterministischem Seed je Experiment. Ohne Server-Abhängigkeiten. */

export const DECISION_MIN_AGE_MS = 48 * 60 * 60 * 1000;
export const MC_DRAWS = 2000;

export interface VariantStats {
  views: number | null;
  follows: number | null;
  saves: number | null;
  likes: number | null;
  follows_per_1k: number | null;
  /* Zeitpunkt der Publikation (published_at, sonst created_at bei manual) */
  published_at: string | null;
  window: string | null;
}

/* Jüngstes Feedback je Clip: 7d vor 48h vor 6h vor manual, dann nach fetched_at */
const WINDOW_RANK: Record<string, number> = { "7d": 3, "48h": 2, "6h": 1, manual: 0 };

export function variantStats(clipId: string, publications: Publication[], feedback: PerformanceFeedback[]): VariantStats {
  const pubs = publications.filter((p) => p.clip_id === clipId);
  const published = pubs
    .map((p) => p.published_at ?? (p.status === "manual" ? p.created_at : null))
    .filter((d): d is string => Boolean(d))
    .sort()[0] ?? null;
  const fb = feedback
    .filter((f) => f.clip_id === clipId)
    .sort((a, b) => (WINDOW_RANK[b.metric_window] ?? 0) - (WINDOW_RANK[a.metric_window] ?? 0) || b.fetched_at.localeCompare(a.fetched_at))[0];
  if (!fb) return { views: null, follows: null, saves: null, likes: null, follows_per_1k: null, published_at: published, window: null };
  const follows1k = fb.follows_per_1k ?? (fb.views && fb.follows != null ? (fb.follows / fb.views) * 1000 : null);
  return { views: fb.views, follows: fb.follows, saves: fb.saves, likes: fb.likes, follows_per_1k: follows1k, published_at: published, window: fb.metric_window };
}

export interface DecisionCheck {
  ready: boolean;
  reasons: string[];
}

export function decisionCheck(experiment: Experiment, a: VariantStats | null, b: VariantStats | null, now = Date.now()): DecisionCheck {
  const reasons: string[] = [];
  if (experiment.status === "decided") return { ready: false, reasons: ["Das Experiment ist bereits entschieden."] };
  if (!a || !b) reasons.push("Beide Varianten brauchen einen Clip.");
  for (const [label, v] of [
    ["A", a],
    ["B", b],
  ] as const) {
    if (!v) continue;
    if (!v.published_at) {
      reasons.push(`Variante ${label} ist noch nicht veröffentlicht.`);
      continue;
    }
    const age = now - Date.parse(v.published_at);
    if (age < DECISION_MIN_AGE_MS) {
      const hours = Math.ceil((DECISION_MIN_AGE_MS - age) / 3_600_000);
      reasons.push(`Variante ${label}: 48 Stunden nach der Veröffentlichung sind noch nicht um (noch ${hours} h).`);
    }
    if (v.views == null) reasons.push(`Variante ${label}: noch keine Views gemeldet.`);
    else if (v.views < experiment.min_exposure) reasons.push(`Variante ${label}: ${v.views.toLocaleString("de-AT")} von ${experiment.min_exposure.toLocaleString("de-AT")} Views Mindestexposure.`);
  }
  return { ready: reasons.length === 0, reasons };
}

/* P(A > B) über Beta(follows + 1, views - follows + 1) je Variante; ohne Folge-Daten P über Saves, sonst null */
export function posteriorAOverB(a: VariantStats, b: VariantStats, seed: string): number | null {
  const pick = (v: VariantStats): [number, number] | null => {
    if (v.views == null || v.views <= 0) return null;
    const success = v.follows ?? v.saves ?? v.likes;
    if (success == null) return null;
    const s = Math.max(0, Math.min(v.views, success));
    return [s + 1, v.views - s + 1];
  };
  const pa = pick(a);
  const pb = pick(b);
  if (!pa || !pb) return null;
  const rng = new Rng(seedFromString(seed));
  let wins = 0;
  for (let i = 0; i < MC_DRAWS; i += 1) {
    if (rng.beta(pa[0], pa[1]) > rng.beta(pb[0], pb[1])) wins += 1;
  }
  return wins / MC_DRAWS;
}

export function successMetricLabel(v: VariantStats | null): string {
  if (!v) return "Folgequote";
  if (v.follows != null) return "Folgequote";
  if (v.saves != null) return "Save-Quote (kein Folge-Signal)";
  if (v.likes != null) return "Like-Quote (kein Folge-Signal)";
  return "Folgequote";
}
