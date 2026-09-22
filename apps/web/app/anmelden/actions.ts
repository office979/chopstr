"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { loginWithPassword, sendMagicLink, startSession } from "@/lib/auth/service";
import { isEmail, normalizeEmail } from "@/lib/auth/tokens";
import { safeNext } from "@/lib/auth/url";
import { CONSOLE_LINK_HINT, field, type FormState } from "@/lib/auth/form";

/* Anmelden: E-Mail + Passwort (intent = password) oder Magic-Link senden (intent = magic) */
export async function loginAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) {
    return { ok: true, message: "Demo-Modus: Du bist bereits als „Demo“ angemeldet.", errors: {} };
  }
  const email = normalizeEmail(formData.get("email"));
  const intent = field(formData, "intent") || "password";
  const next = safeNext(field(formData, "next", 500));
  const errors: Record<string, string> = {};
  if (!isEmail(email)) errors.email = "Bitte eine gültige E-Mail-Adresse angeben.";

  if (intent === "magic") {
    if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };
    const user = await getRepo().findUserByEmail(email);
    /* Kein Hinweis, ob die Adresse existiert */
    let hint: string | undefined;
    if (user) {
      const result = await sendMagicLink(user);
      if (result.logged) hint = CONSOLE_LINK_HINT;
      await getRepo().auditAs({ workspace_id: null, actor_id: user.id }, { action: "auth.magic_link_sent", entity: "users", entity_id: user.id });
    }
    return { ok: true, message: `Wenn ein Konto für ${email} besteht, ist der Anmeldelink unterwegs (15 Minuten gültig).`, errors: {}, hint };
  }

  const password = typeof formData.get("password") === "string" ? (formData.get("password") as string) : "";
  if (!password) errors.password = "Bitte das Passwort eingeben.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const result = await loginWithPassword(email, password);
  if (!result.ok) {
    return { ok: false, message: result.error, errors: {} };
  }
  const started = await startSession(result.user.id);
  await getRepo().auditAs({ workspace_id: started.workspaceId, actor_id: result.user.id }, { action: "auth.login", entity: "users", entity_id: result.user.id, payload: { method: "password" } });
  redirect(next);
}
