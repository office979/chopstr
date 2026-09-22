import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole, requireApiSession } from "@/lib/auth/guard";
import { startDeletionWorkflow } from "@/lib/temporal";
import { latestByClip } from "@/lib/guest/approval";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* GET: Clip mit aktueller Hook-Version und aktuellen Captions */
export async function GET(_request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  const [hook, captions, approvals] = await Promise.all([repo.getCurrentHook(clipId), repo.getCurrentCaptions(clipId), repo.listGuestApprovals(id)]);
  return Response.json({ clip, hook, captions, guest_approval: latestByClip(approvals).get(clipId) ?? null });
}

/* DELETE: Clip löschen (Rolle source.delete): clips.status = deleted, deletion_jobs (entity clip), Audit clip.delete_requested,
 * DeletionWorkflow deletion-<job_id>; ohne Temporal bleibt der Job queued. */
export async function DELETE(_request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("source.delete");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  if (clip.status === "rendering") return Response.json({ error: "Dieser Clip wird gerade gerendert. Bitte warten." }, { status: 409 });
  const job = await repo.requestClipDeletion(clipId);
  if (!job) return Response.json({ error: "Clip wurde bereits gelöscht" }, { status: 409 });
  const started = await startDeletionWorkflow(job.id);
  await repo.audit({
    action: "clip.delete_requested",
    entity: "clips",
    entity_id: clipId,
    payload: { job_id: job.id, source_id: id, platform: clip.platform, file_key: clip.file_key, workflow_started: started, workflow_id: started ? `deletion-${job.id}` : null },
  });
  return Response.json({ ok: true, job, started, message: started ? "Löschung läuft." : "Löschung eingeplant, Nachweis folgt." });
}
