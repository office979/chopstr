"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { sendPasswordReset, startSession } from "@/lib/auth/service";
import { hashPassword, passwordProblem } from "@/lib/auth/password";
import { isEmail, isTokenShape, normalizeEmail } from "@/lib/auth/tokens";
import { CONSOLE_LINK_HINT, field, type FormState } from "@/lib/auth/form";

/* Passwort vergessen: Reset-Link per E-Mail (15 Minuten) */
export async function requestResetAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) return { ok: true, message: "Demo-Modus: Passwort-Reset ist hier ohne Wirkung.", errors: {} };
  const email = normalizeEmail(formData.get("email"));
  if (!isEmail(email)) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors: { email: "Bitte eine gültige E-Mail-Adresse angeben." } };
  const repo = getRepo();
  const user = await repo.findUserByEmail(email);
  let hint: string | undefined;
  if (user) {
    const result = await sendPasswordReset(user);
    if (result.logged) hint = CONSOLE_LINK_HINT;
    await repo.auditAs({ workspace_id: null, actor_id: user.id }, { action: "auth.password_reset_requested", entity: "users", entity_id: user.id });
  }
  return { ok: true, message: `Wenn ein Konto für ${email} besteht, ist der Link zum Zurücksetzen unterwegs.`, errors: {}, hint };
}

/* Neues Passwort mit Token setzen, alle anderen Sitzungen beenden, direkt anmelden */
export async function resetPasswordAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) return { ok: true, message: "Demo-Modus: Passwort-Reset ist hier ohne Wirkung.", errors: {} };
  const token = field(formData, "token", 200);
  const password = typeof formData.get("password") === "string" ? (formData.get("password") as string) : "";
  const confirm = typeof formData.get("password_confirm") === "string" ? (formData.get("password_confirm") as string) : "";
  const errors: Record<string, string> = {};
  const pw = passwordProblem(password);
  if (pw) errors.password = pw;
  else if (password !== confirm) errors.password_confirm = "Die Passwörter stimmen nicht überein.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };
  if (!isTokenShape(token)) return { ok: false, message: "Der Link ist ungültig.", errors: {} };

  const repo = getRepo();
  const consumed = await repo.consumeLoginToken(token, "password_reset");
  if (!consumed) return { ok: false, message: "Der Link ist abgelaufen oder wurde schon benutzt. Bitte neu anfordern.", errors: {} };
  await repo.updateUser(consumed.user_id, { password_hash: await hashPassword(password) });
  await repo.deleteUserSessions(consumed.user_id);
  const started = await startSession(consumed.user_id);
  await repo.auditAs({ workspace_id: started.workspaceId, actor_id: consumed.user_id }, { action: "auth.password_changed", entity: "users", entity_id: consumed.user_id, payload: { via: "reset" } });
  redirect("/");
}
