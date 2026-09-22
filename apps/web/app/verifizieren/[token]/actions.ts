"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { getAuthUser } from "@/lib/session";
import { isTokenShape } from "@/lib/auth/tokens";
import { field, type FormState } from "@/lib/auth/form";

/* E-Mail-Adresse bestätigen (nach Registrierung oder Adressänderung im Profil) */
export async function verifyEmailAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) return { ok: true, message: "Demo-Modus: Es gibt nichts zu bestätigen.", errors: {} };
  const token = field(formData, "token", 200);
  if (!isTokenShape(token)) return { ok: false, message: "Der Link ist ungültig.", errors: {} };
  const repo = getRepo();
  const consumed = await repo.consumeLoginToken(token, "verify_email");
  if (!consumed) return { ok: false, message: "Der Link ist abgelaufen oder wurde schon benutzt. Im Profil kannst du eine neue Bestätigung anfordern.", errors: {} };
  await repo.updateUser(consumed.user_id, { email_verified_at: new Date().toISOString() });
  const me = await getAuthUser();
  await repo.auditAs({ workspace_id: me?.activeWorkspaceId ?? null, actor_id: consumed.user_id }, { action: "auth.email_verified", entity: "users", entity_id: consumed.user_id });
  redirect(me ? "/profil" : "/anmelden");
}
