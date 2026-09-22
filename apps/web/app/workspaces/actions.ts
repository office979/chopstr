"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { requireAuthUser } from "@/lib/session";
import type { FormState } from "@/lib/auth/form";

/* Workspace wechseln: schreibt sessions.workspace_id */
export async function switchWorkspaceAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const workspaceId = String(formData.get("workspace_id") ?? "");
  const me = await requireAuthUser();
  if (isDemoMode() || !me.sessionId) redirect("/");
  const repo = getRepo();
  const membership = await repo.getMembership(me.userId, workspaceId);
  if (!membership) return { ok: false, message: "Du bist in diesem Workspace kein Mitglied.", errors: {} };
  await repo.setSessionWorkspace(me.sessionId, workspaceId);
  await repo.auditAs({ workspace_id: workspaceId, actor_id: me.userId }, { action: "auth.workspace_switched", entity: "workspaces", entity_id: workspaceId });
  redirect("/");
}
