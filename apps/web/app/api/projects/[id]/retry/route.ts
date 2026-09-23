import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { startClipProjectWorkflow } from "@/lib/temporal";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* POST: Analyse einer fehlgeschlagenen Quelle noch einmal anstoßen.
 *
 * Die Datei liegt bereits im Objektspeicher, es muss also nichts neu hochgeladen werden — der Status
 * geht zurück auf `uploaded`, und von dort holt die Verarbeitung die Quelle wieder ab: mit Temporal
 * über einen neuen Workflow, ohne Temporal über das Polling des lokalen Workers. Beides braucht
 * denselben Status, deshalb wird er in jedem Fall gesetzt.
 *
 * Nur aus `failed` heraus. Eine laufende Analyse neu zu starten würde zwei Workflows auf dieselbe
 * Quelle loslassen. */
export async function POST(_request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("source.upload");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });
  if (source.status !== "failed") {
    return Response.json({ error: "Nur fehlgeschlagene Analysen lassen sich neu starten" }, { status: 409 });
  }
  if (!source.storage_key) {
    return Response.json({ error: "Zu diesem Projekt gibt es keine Datei mehr" }, { status: 409 });
  }

  await repo.updateSource(id, { status: "uploaded", status_message: null, temporal_workflow_id: null });
  const workflowId = await startClipProjectWorkflow({ sourceId: id, workspaceId: auth.workspaceId });
  if (workflowId) await repo.updateSource(id, { temporal_workflow_id: workflowId });

  await repo.audit({
    action: "source.retry_requested",
    entity: "sources",
    entity_id: id,
    payload: { previous_message: source.status_message, workflow_id: workflowId },
  });
  return Response.json({ ok: true, workflow_id: workflowId });
}
