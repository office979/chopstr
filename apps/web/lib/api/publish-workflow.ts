import "server-only";
import { isDemoMode } from "@/lib/env";

/* PublishWorkflow (PHASE5.md, 5b): Workflow-ID publish-<publication_id>, Argument [{ publication_id }]
 * (Dataclass PublishParams in workers/chopstr_worker/workflows/publish.py), CPU-Queue. Ohne Temporal bleibt
 * die Publikation `scheduled`; der Hinweis geht in die Antwort. Fehler werden geloggt, nicht weitergereicht. */

export interface PublishStart {
  started: boolean;
  workflow_id: string | null;
  hint: string | null;
}

export async function startPublishWorkflow(publicationId: string): Promise<PublishStart> {
  const workflowId = `publish-${publicationId}`;
  const taskQueue = process.env.TEMPORAL_TASK_QUEUE_CPU ?? "chopstr-cpu";
  const address = process.env.TEMPORAL_ADDRESS;
  if (isDemoMode() || !address) {
    console.info(`[temporal] Kein Temporal: PublishWorkflow ${workflowId} nicht gestartet, Publikation bleibt scheduled`);
    return { started: false, workflow_id: null, hint: "Kein Temporal erreichbar: Die Publikation bleibt geplant, bis ein Worker läuft." };
  }
  try {
    const { Connection, Client } = await import("@temporalio/client");
    const connection = await Connection.connect({ address });
    try {
      const client = new Client({ connection, namespace: process.env.TEMPORAL_NAMESPACE ?? "default" });
      await client.workflow.start("PublishWorkflow", { taskQueue, workflowId, args: [{ publication_id: publicationId }] });
      return { started: true, workflow_id: workflowId, hint: null };
    } finally {
      await connection.close();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.warn(`[temporal] PublishWorkflow ${workflowId} konnte nicht gestartet werden:`, message);
    return { started: false, workflow_id: null, hint: `Temporal nicht erreichbar (${message.slice(0, 120)}): Die Publikation bleibt geplant.` };
  }
}
