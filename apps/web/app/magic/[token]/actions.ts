"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { startSession } from "@/lib/auth/service";
import { isTokenShape } from "@/lib/auth/tokens";
import { safeNext } from "@/lib/auth/url";
import { field, type FormState } from "@/lib/auth/form";

/* Magic-Link bestätigen: Token verbrauchen, Sitzung anlegen, E-Mail gilt als bestätigt */
export async function confirmMagicAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) return { ok: true, message: "Demo-Modus: Du bist bereits als „Demo“ angemeldet.", errors: {} };
  const token = field(formData, "token", 200);
  const next = safeNext(field(formData, "next", 500));
  if (!isTokenShape(token)) return { ok: false, message: "Der Link ist ungültig.", errors: {} };
  const repo = getRepo();
  const consumed = await repo.consumeLoginToken(token, "magic_link");
  if (!consumed) return { ok: false, message: "Der Link ist abgelaufen oder wurde schon benutzt. Bitte einen neuen anfordern.", errors: {} };
  const user = await repo.getUser(consumed.user_id);
  if (!user) return { ok: false, message: "Das Konto existiert nicht mehr.", errors: {} };
  if (!user.email_verified_at) await repo.updateUser(user.id, { email_verified_at: new Date().toISOString() });
  const started = await startSession(user.id);
  await repo.auditAs({ workspace_id: started.workspaceId, actor_id: user.id }, { action: "auth.login", entity: "users", entity_id: user.id, payload: { method: "magic_link" } });
  redirect(next);
}
