import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { signalApprove } from "@/lib/temporal";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* POST: Render (erneut) anstoßen. Signal approve(candidate_id, platform) an project-<source_id>;
 * im Demo-Modus startet das Repository die Simulation. */
export async function POST(_request: NextRequest, { params }: Params) {
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  if (clip.status === "rendering") {
    return Response.json({ error: "Dieser Clip wird gerade gerendert" }, { status: 409 });
  }
  if (!clip.candidate_id) {
    return Response.json({ error: "Clip ohne Kandidat kann nicht neu gerendert werden" }, { status: 409 });
  }

  const updated = (await repo.requestClipRender(clipId)) ?? clip;
  const signaled = await signalApprove({ sourceId: id, candidateId: clip.candidate_id, destination: clip.platform });
  await repo.audit({
    action: "clip.render_requested",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, candidate_id: clip.candidate_id, platform: clip.platform, previous_status: clip.status, signaled },
  });
  return Response.json({ ok: true, clip: updated, signaled, demo: repo.kind === "demo" });
}
