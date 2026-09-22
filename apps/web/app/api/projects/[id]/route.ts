import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { startDeletionWorkflow } from "@/lib/temporal";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* DELETE { confirm_title }: Quelle löschen (PHASE4.md, Abschnitt 7). sources.status = deleted, deleted_at,
 * deletion_jobs (entity source, reason user_request), Audit source.delete_requested, DeletionWorkflow
 * deletion-<job_id> (ohne Temporal bleibt der Job queued, der Retention-Lauf holt ihn ab). */
export async function DELETE(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("source.delete");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });

  let body: { confirm_title?: unknown } = {};
  try {
    body = (await request.json()) as { confirm_title?: unknown };
  } catch {
    /* leerer Body erlaubt, dann fehlt die Bestätigung */
  }
  const confirm = typeof body.confirm_title === "string" ? body.confirm_title.trim() : "";
  if (confirm !== source.title.trim()) {
    return Response.json({ error: "Zur Bestätigung bitte den Titel des Projekts genau eingeben.", code: "confirm_mismatch" }, { status: 400 });
  }

  const job = await repo.requestSourceDeletion(id);
  if (!job) return Response.json({ error: "Projekt wurde bereits gelöscht" }, { status: 409 });
  const started = await startDeletionWorkflow(job.id);
  await repo.audit({
    action: "source.delete_requested",
    entity: "sources",
    entity_id: id,
    payload: { job_id: job.id, title: source.title, storage_key: source.storage_key, workflow_started: started, workflow_id: started ? `deletion-${job.id}` : null },
  });
  return Response.json({ ok: true, job, started, message: started ? "Löschung läuft. Der Nachweis erscheint unter Einstellungen, Löschung." : "Löschung eingeplant, Nachweis folgt. Der tägliche Retention-Lauf führt den Auftrag aus." });
}
