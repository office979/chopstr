import type { BrandProfile, Candidate, Clip, Platform, Source } from "@/lib/repo/types";

/* Menschliche Annahme eines Kandidaten, gemeinsam für die Verdict-Route und die Render-Route.
 *
 * Die Analyse legt für jeden Kandidaten einen Clip-Entwurf an. Trägt der Kandidat einen harten
 * Risikohinweis oder eine freigaberelevante Behauptung, nimmt ihn die Automatik nicht an: das
 * Urteil bleibt leer, verdict_reason beginnt mit AUTO_HOLD_REASON_PREFIX, und kein Worker rendert
 * den Entwurf (docs/ENTSCHEIDUNGEN.md P27). Der Klick auf „Video clippen“ an so einem Clip ist die
 * menschliche Annahme; ein abgelehnter Kandidat wird gar nicht gerendert. */

/* Spiegel von AUTO_HOLD_REASON_PREFIX in workers/chopstr_worker/activities/analyze.py. */
export const AUTO_HOLD_REASON_PREFIX = "automatische Freigabe ausgesetzt: ";

/* Spiegel von AUTO_CLIP_PLATFORM in workers/chopstr_worker/activities/analyze.py: der letzte Rückfall,
 * wenn weder Markenprofil noch Briefing eine Plattform nennen. */
export const FALLBACK_CLIP_PLATFORM: Platform = "reels";

type VerdictFields = Pick<Candidate, "human_verdict" | "verdict_reason">;

/* Von der Automatik zurückgehalten: kein Urteil, Begründung mit dem Präfix der Analyse. */
export function isHeldCandidate(candidate: VerdictFields): boolean {
  return candidate.human_verdict == null && (candidate.verdict_reason ?? "").startsWith(AUTO_HOLD_REASON_PREFIX);
}

/* Standard-Plattform einer Quelle in derselben Reihenfolge wie analyze.clip_platform im Worker:
 * Markenprofil, Briefing, FALLBACK_CLIP_PLATFORM. */
export function defaultClipPlatform(
  brand: Pick<BrandProfile, "default_platform"> | null,
  source: Pick<Source, "brief">,
): Platform {
  return brand?.default_platform ?? source.brief?.platform ?? FALLBACK_CLIP_PLATFORM;
}

/* Plattform für eine Annahme ohne Plattformwahl: hat der Kandidat schon einen Clip (etwa den
 * Entwurf der Analyse), dessen Plattform, damit createClips genau diesen Clip wiederverwendet statt
 * einen zweiten anzulegen. Sonst die Standard-Plattform der Quelle. */
export function acceptancePlatform(
  candidateId: string,
  clips: Pick<Clip, "candidate_id" | "platform" | "status" | "created_at">[],
  brand: Pick<BrandProfile, "default_platform"> | null,
  source: Pick<Source, "brief">,
): Platform {
  const own = clips
    .filter((c) => c.candidate_id === candidateId && c.status !== "deleted")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  return own[0]?.platform ?? defaultClipPlatform(brand, source);
}

/* Automatik-Entwürfe des Kandidaten (created_by leer, noch draft) auf Plattformen, die bei einer
 * Annahme mit ausdrücklicher Plattformwahl nicht gewählt wurden. Sie werden gelöscht, sonst rendert
 * der lokale Worker sie mit, sobald der Kandidat angenommen ist. */
export function unchosenAutoDrafts<C extends Pick<Clip, "id" | "candidate_id" | "platform" | "status" | "created_by">>(
  candidateId: string,
  clips: C[],
  chosen: Platform[],
): C[] {
  return clips.filter(
    (c) => c.candidate_id === candidateId && c.created_by == null && c.status === "draft" && !chosen.includes(c.platform),
  );
}

export type RenderAcceptance =
  /* Angenommen: rendern wie bisher. */
  | { kind: "render" }
  /* Kein Urteil: der Klick ist die menschliche Annahme, erst das Urteil, dann rendern. */
  | { kind: "accept"; reason: string }
  /* Abgelehnt oder durch eine neue Fassung ersetzt: nicht rendern, mit Fehlertext (409). */
  | { kind: "refuse"; error: string };

/* Derselbe Text wie in der Verdict-Route. */
export const EDITED_ERROR = "Dieser Kandidat wurde durch eine neue Version ersetzt";

export function renderAcceptance(candidate: VerdictFields | null): RenderAcceptance {
  if (!candidate) return { kind: "render" };
  if (candidate.human_verdict === "rejected") {
    const reason = candidate.verdict_reason?.trim();
    return {
      kind: "refuse",
      error: reason ? `Dieser Vorschlag ist abgelehnt: ${reason}` : "Dieser Vorschlag ist abgelehnt.",
    };
  }
  if (candidate.human_verdict === "edited") return { kind: "refuse", error: EDITED_ERROR };
  if (candidate.human_verdict == null) {
    const held = isHeldCandidate(candidate) ? candidate.verdict_reason : null;
    return {
      kind: "accept",
      reason: held ? `angenommen beim Clippen, vorher ${held}` : "angenommen beim Clippen",
    };
  }
  return { kind: "render" };
}
