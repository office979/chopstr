"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { getAuthUser } from "@/lib/session";
import { startSession } from "@/lib/auth/service";
import { hashPassword, passwordProblem } from "@/lib/auth/password";
import { isTokenShape } from "@/lib/auth/tokens";
import { field, type FormState } from "@/lib/auth/form";

/* Einladung annehmen als angemeldeter Nutzer: Mitgliedschaft mit Rolle und Marke, accepted_at, Workspace wechseln */
export async function acceptInviteAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const token = field(formData, "token", 200);
  if (!isTokenShape(token)) return { ok: false, message: "Der Einladungslink ist ungültig.", errors: {} };
  const repo = getRepo();
  const me = await getAuthUser();
  if (!me) redirect(`/anmelden?next=${encodeURIComponent(`/einladung/${token}`)}`);
  const invite = await repo.getInvite(token);
  if (!invite) return { ok: false, message: "Diese Einladung gibt es nicht mehr.", errors: {} };
  const existing = await repo.getMembership(me.userId, invite.workspace_id);
  if (existing?.role === "owner") return { ok: false, message: "Du bist Inhaber dieses Teams, die Einladung ist für ein anderes Konto gedacht.", errors: {} };
  const accepted = await repo.acceptInvite(token, me.userId);
  if (!accepted) return { ok: false, message: "Die Einladung ist abgelaufen oder wurde schon angenommen.", errors: {} };
  if (me.sessionId) await repo.setSessionWorkspace(me.sessionId, invite.workspace_id);
  await repo.auditAs(
    { workspace_id: invite.workspace_id, actor_id: me.userId },
    { action: "member.joined", entity: "workspace_members", entity_id: me.userId, payload: { role: invite.role, brand_profile_id: invite.brand_profile_id, invited_by: invite.invited_by } },
  );
  redirect("/");
}

/* Einladung annehmen mit neuem Konto: Name und Passwort, E-Mail aus der Einladung */
export async function registerViaInviteAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) return { ok: true, message: "Demo-Modus: Einladungen sind hier ohne Wirkung.", errors: {} };
  const token = field(formData, "token", 200);
  const displayName = field(formData, "display_name", 80);
  const password = typeof formData.get("password") === "string" ? (formData.get("password") as string) : "";
  const errors: Record<string, string> = {};
  if (displayName.length < 2) errors.display_name = "Bitte deinen Namen angeben.";
  const pw = passwordProblem(password);
  if (pw) errors.password = pw;
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };
  if (!isTokenShape(token)) return { ok: false, message: "Der Einladungslink ist ungültig.", errors: {} };

  const repo = getRepo();
  const invite = await repo.getInvite(token);
  if (!invite || invite.accepted_at || Date.parse(invite.expires_at) <= Date.now()) {
    return { ok: false, message: "Die Einladung ist abgelaufen oder wurde schon angenommen.", errors: {} };
  }
  if (await repo.findUserByEmail(invite.email)) {
    return { ok: false, message: "Für diese E-Mail-Adresse gibt es schon ein Konto. Bitte melde dich an und öffne den Link erneut.", errors: {} };
  }
  const user = await repo.createUser({ email: invite.email, password_hash: await hashPassword(password), display_name: displayName });
  /* Die Einladung ging an diese Adresse, damit gilt sie als bestätigt */
  await repo.updateUser(user.id, { email_verified_at: new Date().toISOString() });
  const accepted = await repo.acceptInvite(token, user.id);
  if (!accepted) return { ok: false, message: "Die Einladung konnte nicht angenommen werden.", errors: {} };
  await startSession(user.id, invite.workspace_id);
  await repo.auditAs(
    { workspace_id: invite.workspace_id, actor_id: user.id },
    { action: "member.joined", entity: "workspace_members", entity_id: user.id, payload: { role: invite.role, brand_profile_id: invite.brand_profile_id, invited_by: invite.invited_by, registered: true } },
  );
  redirect("/");
}
