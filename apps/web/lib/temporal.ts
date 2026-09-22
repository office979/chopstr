/* Temporal-Anbindung. Ohne TEMPORAL_ADDRESS (oder im Demo-Modus) wird nur geloggt. */
import { isDemoMode } from "@/lib/env";

export interface StartWorkflowArgs {
  sourceId: string;
  workspaceId: string;
}

export async function startClipProjectWorkflow({
  sourceId,
  workspaceId,
}: StartWorkflowArgs): Promise<string | null> {
  const workflowId = `project-${sourceId}`;
  const taskQueue = process.env.TEMPORAL_TASK_QUEUE_CPU ?? "chopstr-cpu";
  const address = process.env.TEMPORAL_ADDRESS;

  if (isDemoMode() || !address) {
    console.info(
      `[temporal] Demo-Modus: ClipProjectWorkflow ${workflowId} auf ${taskQueue} nicht gestartet`,
    );
    return null;
  }

  const { Connection, Client } = await import("@temporalio/client");
  const connection = await Connection.connect({ address });
  try {
    const client = new Client({
      connection,
      namespace: process.env.TEMPORAL_NAMESPACE ?? "default",
    });
    const handle = await client.workflow.start("ClipProjectWorkflow", {
      taskQueue,
      workflowId,
      /* Muss zu ClipProjectParams in workers/chopstr_worker/workflows/clip_project.py passen */
      args: [{ source_id: sourceId, workspace_id: workspaceId }],
    });
    return handle.workflowId;
  } finally {
    await connection.close();
  }
}

export interface ApproveSignalArgs {
  sourceId: string;
  candidateId: string;
  destination: string;
}

/* Freigabe-Signal an den laufenden ClipProjectWorkflow (Signal `approve(candidate_id, destination)`).
 * Liefert true, wenn das Signal zugestellt wurde; Fehler werden geloggt und nicht weitergereicht,
 * damit das menschliche Urteil unabhängig von Temporal gespeichert bleibt. */
export async function signalApprove({ sourceId, candidateId, destination }: ApproveSignalArgs): Promise<boolean> {
  const workflowId = `project-${sourceId}`;
  const address = process.env.TEMPORAL_ADDRESS;

  if (isDemoMode() || !address) {
    console.info(`[temporal] Demo-Modus: Signal approve(${candidateId}, ${destination}) an ${workflowId} nur geloggt`);
    return false;
  }

  try {
    const { Connection, Client } = await import("@temporalio/client");
    const connection = await Connection.connect({ address });
    try {
      const client = new Client({
        connection,
        namespace: process.env.TEMPORAL_NAMESPACE ?? "default",
      });
      const handle = client.workflow.getHandle(workflowId);
      await handle.signal("approve", candidateId, destination);
      return true;
    } finally {
      await connection.close();
    }
  } catch (error) {
    console.warn(`[temporal] Signal approve an ${workflowId} fehlgeschlagen:`, error instanceof Error ? error.message : error);
    return false;
  }
}

/* Lösch-Workflow (PHASE4.md, Abschnitt 7): DeletionWorkflow mit ID deletion-<job_id> auf der CPU-Queue,
 * Argument { job_id } (Dataclass DeletionParams in workers/chopstr_worker/workflows/deletion.py).
 * Liefert true, wenn der Start gelang; ohne Temporal (Demo oder keine Adresse) bleibt der Job `queued`
 * und der tägliche RetentionWorkflow holt ihn ab. Fehler werden geloggt, nicht weitergereicht. */
export async function startDeletionWorkflow(jobId: string): Promise<boolean> {
  const workflowId = `deletion-${jobId}`;
  const taskQueue = process.env.TEMPORAL_TASK_QUEUE_CPU ?? "chopstr-cpu";
  const address = process.env.TEMPORAL_ADDRESS;

  if (isDemoMode() || !address) {
    console.info(`[temporal] Kein Temporal: DeletionWorkflow ${workflowId} nicht gestartet, Job bleibt queued (Retention-Lauf)`);
    return false;
  }

  try {
    const { Connection, Client } = await import("@temporalio/client");
    const connection = await Connection.connect({ address });
    try {
      const client = new Client({ connection, namespace: process.env.TEMPORAL_NAMESPACE ?? "default" });
      await client.workflow.start("DeletionWorkflow", { taskQueue, workflowId, args: [{ job_id: jobId }] });
      return true;
    } finally {
      await connection.close();
    }
  } catch (error) {
    console.warn(`[temporal] DeletionWorkflow ${workflowId} konnte nicht gestartet werden:`, error instanceof Error ? error.message : error);
    return false;
  }
}

/* Publishing (PHASE5.md, 5b): PublishWorkflow mit ID publish-<publication_id> auf der CPU-Queue, Argument
 * { publication_id } (Dataclass PublishParams in workers/chopstr_worker/workflows/publish.py). Ohne Temporal bleibt die
 * Publikation `scheduled`; der Worker holt sie beim nächsten Lauf ab. Fehler werden geloggt, nicht weitergereicht. */
export async function startPublishWorkflow(publicationId: string): Promise<boolean> {
  const workflowId = `publish-${publicationId}`;
  const taskQueue = process.env.TEMPORAL_TASK_QUEUE_CPU ?? "chopstr-cpu";
  const address = process.env.TEMPORAL_ADDRESS;

  if (isDemoMode() || !address) {
    console.info(`[temporal] Kein Temporal: PublishWorkflow ${workflowId} nicht gestartet, Publikation bleibt scheduled`);
    return false;
  }

  try {
    const { Connection, Client } = await import("@temporalio/client");
    const connection = await Connection.connect({ address });
    try {
      const client = new Client({ connection, namespace: process.env.TEMPORAL_NAMESPACE ?? "default" });
      await client.workflow.start("PublishWorkflow", { taskQueue, workflowId, args: [{ publication_id: publicationId }] });
      return true;
    } finally {
      await connection.close();
    }
  } catch (error) {
    console.warn(`[temporal] PublishWorkflow ${workflowId} konnte nicht gestartet werden:`, error instanceof Error ? error.message : error);
    return false;
  }
}

/* Signale an den PublishWorkflow: `cancel` (vor dem Publish) und `reschedule(iso)` (neuer Zeitpunkt). */
export async function signalPublish(publicationId: string, signal: "cancel" | "reschedule", scheduledFor?: string): Promise<boolean> {
  const workflowId = `publish-${publicationId}`;
  const address = process.env.TEMPORAL_ADDRESS;

  if (isDemoMode() || !address) {
    console.info(`[temporal] Kein Temporal: Signal ${signal} an ${workflowId} nur geloggt`);
    return false;
  }

  try {
    const { Connection, Client } = await import("@temporalio/client");
    const connection = await Connection.connect({ address });
    try {
      const client = new Client({ connection, namespace: process.env.TEMPORAL_NAMESPACE ?? "default" });
      const handle = client.workflow.getHandle(workflowId);
      if (signal === "reschedule") await handle.signal("reschedule", scheduledFor ?? new Date().toISOString());
      else await handle.signal("cancel");
      return true;
    } finally {
      await connection.close();
    }
  } catch (error) {
    console.warn(`[temporal] Signal ${signal} an ${workflowId} fehlgeschlagen:`, error instanceof Error ? error.message : error);
    return false;
  }
}
