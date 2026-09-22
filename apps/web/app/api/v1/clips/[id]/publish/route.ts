import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, conflict, notFound, paymentRequired } from "@/lib/api/errors";
import { loadClip } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { serializePublication } from "@/lib/api/serializers";
import { startPublishWorkflow } from "@/lib/api/publish-workflow";
import { getQuota } from "@/lib/billing/quota";
import { latestByClip } from "@/lib/guest/approval";

export const dynamic = "force-dynamic";

interface PublishBody {
  connection_id: string;
  scheduled_for?: string | null;
  caption?: string | null;
  title?: string | null;
}

/* Kein Autopublishing: jede Publikation entsteht aus einem Aufruf mit Scope publish. Gates nach PHASE5.md:
 * Clip rendered (oder exported), Kandidat accepted, Gast-Freigabe approved falls verlangt, AVV angenommen,
 * Plan features.publishing (402). Danach publications-Zeile und PublishWorkflow publish-<id>. */
export const POST = apiRoute<{ id: string }>("publish", async (request: NextRequest, { params, auth }) => {
  const body = await readJsonBody<PublishBody>(request, requestSchema("Publish"), resolveRef);
  const repo = getRepo();
  const apiRepo = getApiRepo();
  const { clip, source } = await loadClip(params.id);

  const quota = await getQuota(repo);
  if (!quota.plan?.features?.publishing) {
    throw paymentRequired(`Publishing ist im Tarif ${quota.plan?.name ?? "Starter"} nicht enthalten. Ab Pro verfügbar.`, "plan_gate");
  }
  const workspace = await repo.getWorkspace();
  if (!workspace.dpa_signed_at) throw conflict("Der AV-Vertrag ist noch nicht angenommen. Bitte unter /rechtliches/avv annehmen.", "dpa_missing");
  if (clip.status !== "rendered" && clip.status !== "exported") throw conflict(`Clip ist nicht gerendert (Status ${clip.status}).`, "clip_not_rendered");
  if (!clip.candidate_id) throw conflict("Clip hat keinen Kandidaten.", "candidate_missing");
  const candidate = await repo.getCandidate(clip.candidate_id);
  if (candidate?.human_verdict !== "accepted") throw conflict(`Kandidat ist nicht angenommen (Urteil ${candidate?.human_verdict ?? "offen"}).`, "candidate_not_accepted");
  if (clip.guest_approval_required) {
    const latest = latestByClip(await repo.listGuestApprovals(source.id)).get(clip.id);
    if (latest?.decision !== "approved") throw conflict("Gast-Freigabe fehlt.", "guest_approval_missing");
  }

  const connection = await apiRepo.getPlatformConnection(body.connection_id);
  if (!connection) throw notFound("Verbindung nicht gefunden.");
  if (connection.status !== "connected") throw conflict(`Verbindung ist ${connection.status === "expired" ? "abgelaufen" : "widerrufen"}.`, "connection_unavailable");

  let scheduledFor: string | null = null;
  if (body.scheduled_for) {
    const when = new Date(body.scheduled_for);
    if (when.getTime() < Date.now() - 60_000) throw conflict("scheduled_for liegt in der Vergangenheit.", "scheduled_in_past");
    scheduledFor = when.toISOString();
  }

  const publication = await apiRepo.createPublication({
    clip_id: clip.id,
    connection_id: connection.id,
    platform: connection.platform,
    scheduled_for: scheduledFor,
    caption: body.caption?.trim() || null,
    title: body.title?.trim() || null,
  });
  const start = await startPublishWorkflow(publication.id);
  if (start.workflow_id) await apiRepo.setPublicationWorkflow(publication.id, start.workflow_id);
  await repo.audit({
    action: "publication.created",
    entity: "publications",
    entity_id: publication.id,
    payload: { clip_id: clip.id, source_id: source.id, connection_id: connection.id, platform: connection.platform, scheduled_for: scheduledFor, via: "api", api_key_id: auth.key.id, workflow_started: start.started },
  });
  const fresh = (await apiRepo.getPublication(publication.id)) ?? publication;
  return apiJson({ publication: serializePublication(fresh), workflow_started: start.started, hint: start.hint }, 201);
});
