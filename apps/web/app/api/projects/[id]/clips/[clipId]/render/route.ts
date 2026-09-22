import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { signalApprove } from "@/lib/temporal";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* POST: Render (erneut) anstoßen. Signal approve(candidate_id, "platform:clip_id") an project-<source_id>;
 * ohne Temporal wird der Clip `draft` und der lokale Worker holt ihn ab; im Demo-Modus startet das Repository die Simulation. */
export async function POST(_request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
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

  /* Ziel "plattform:clip_id": der Worker rendert genau diesen Clip (wichtig für Hook-A/B, Variante B hat dieselbe Plattform) */
  const signaled = await signalApprove({ sourceId: id, candidateId: clip.candidate_id, destination: `${clip.platform}:${clipId}` });
  /* Ohne Signal (kein TEMPORAL_ADDRESS oder fehlgeschlagen) geht der Clip als `draft` in die Warteschlange des lokalen Workers */
  const updated = (await repo.requestClipRender(clipId, signaled)) ?? clip;
  await repo.audit({
    action: "clip.render_requested",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, candidate_id: clip.candidate_id, platform: clip.platform, previous_status: clip.status, signaled },
  });
  return Response.json({ ok: true, clip: updated, signaled, demo: repo.kind === "demo" });
}
