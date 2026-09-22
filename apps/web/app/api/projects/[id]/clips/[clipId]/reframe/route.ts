import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import { recordDecision } from "@/lib/decision-log";
import type { ReframeOverride } from "@/lib/repo/types-publishing";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

const OVERRIDES: ReframeOverride[] = ["talking_head", "two_speakers", "neutral", "slide_pip"];

/* PATCH: Reframe-Strategie überschreiben (5c): { reframe_override: null | talking_head | two_speakers | neutral | slide_pip }.
 * Wirkt beim nächsten Render; der Worker liest clips.reframe_override. */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  let body: { reframe_override?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const value = body.reframe_override;
  const override = value == null || value === "" || value === "auto" ? null : (OVERRIDES as string[]).includes(String(value)) ? (value as ReframeOverride) : undefined;
  if (override === undefined) return Response.json({ error: "Unbekannte Strategie" }, { status: 400 });
  const extras = await getPublishingRepo().updateClipExtras(clipId, { reframe_override: override });
  if (!extras) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  const source = await repo.getSource(id);
  await recordDecision({
    decision_type: "reframe_strategy",
    actor_type: "user",
    brand_profile_id: source?.brand_profile_id ?? null,
    source_id: id,
    candidate_id: clip.candidate_id,
    clip_id: clipId,
    features: { platform: clip.platform, detected: clip.render_plan?.reframe.strategy ?? null, detector: clip.render_plan?.reframe.detector ?? null },
    alternatives: OVERRIDES.filter((o) => o !== override).map((o) => ({ strategy: o })),
    chosen: { strategy: override ?? "auto" },
  });
  await repo.audit({ action: "clip.reframe_override", entity: "clips", entity_id: clipId, payload: { source_id: id, reframe_override: override, previous: clip.render_plan?.reframe.strategy ?? null } });
  return Response.json({ ok: true, extras, needs_render: clip.status === "rendered" || clip.status === "exported" });
}
