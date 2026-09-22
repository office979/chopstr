import "server-only";
import { getPublishingRepo } from "@/lib/repo/publishing";
import type { Candidate, Clip, HookVersion } from "@/lib/repo/types";
import type { DecisionInput, DecisionRow } from "@/lib/repo/types-publishing";

/* Decision Log der Web-App (A3: kein Lernen ohne Decision Log). Jede Entscheidung von Nutzer oder System landet in
 * decision_log mit Merkmalen, verworfenen Alternativen und Wahl. Fehler beim Schreiben werden geloggt und nicht
 * weitergereicht: die fachliche Aktion bleibt unabhängig vom Log gültig. Der Worker schreibt seine Einträge selbst
 * (workers/chopstr_worker/decision_log.py), die Formen sind kompatibel (features.patterns, chosen.pattern). */

export async function recordDecision(input: DecisionInput): Promise<DecisionRow | null> {
  try {
    return await getPublishingRepo().recordDecision(input);
  } catch (error) {
    console.warn(`[decision-log] ${input.decision_type} nicht gespeichert:`, error instanceof Error ? error.message : error);
    return null;
  }
}

/* Merkmale eines Kandidaten (Rubrik-Scores, Struktur, Länge, Gates, Flags) */
export function candidateFeatures(candidate: Candidate): Record<string, unknown> {
  const scores: Record<string, number> = {};
  for (const [k, v] of Object.entries(candidate.rubric?.scores ?? {})) scores[k] = v.value;
  return {
    scores,
    structure: candidate.structure,
    duration_s: candidate.rubric?.duration_s ?? candidate.end_s - candidate.start_s,
    speakers: candidate.rubric?.speakers?.length ?? null,
    total: candidate.total,
    gate_passed: candidate.gate_passed,
    gates: Object.fromEntries(Object.entries(candidate.gates ?? {}).map(([k, g]) => [k, g.passed])),
    risk_flags: candidate.risk_flags,
    version: candidate.version,
  };
}

/* Merkmale eines Clips für Hook- und Publish-Entscheidungen */
export function clipFeatures(clip: Clip, hook?: HookVersion | null): Record<string, unknown> {
  return {
    platform: clip.platform,
    aspect: clip.aspect,
    duration_s: clip.duration_s,
    status: clip.status,
    reframe_strategy: clip.render_plan?.reframe.strategy ?? null,
    caption_preset: clip.render_plan?.captions.preset ?? null,
    hook_pattern: hook?.pattern ?? null,
    guest_approval_required: clip.guest_approval_required,
  };
}
