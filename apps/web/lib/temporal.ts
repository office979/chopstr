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
