"use server";

import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { registerOwner, sendEmailVerification, startSession } from "@/lib/auth/service";
import { passwordProblem } from "@/lib/auth/password";
import { isEmail, normalizeEmail } from "@/lib/auth/tokens";
import { field, type FormState } from "@/lib/auth/form";

/* Registrierung: Nutzer, Workspace (Name = Firma) mit owner, Standard-Markenprofil, Starter-Test 14 Tage, Nutzungsperiode */
export async function registerAction(_prev: FormState, formData: FormData): Promise<FormState> {
  if (isDemoMode()) {
    return { ok: true, message: "Demo-Modus: Registrierung ist hier ohne Wirkung, du bist als „Demo“ angemeldet.", errors: {} };
  }
  const displayName = field(formData, "display_name", 80);
  const email = normalizeEmail(formData.get("email"));
  const password = typeof formData.get("password") === "string" ? (formData.get("password") as string) : "";
  const company = field(formData, "company", 80);

  const errors: Record<string, string> = {};
  if (displayName.length < 2) errors.display_name = "Bitte deinen Namen angeben.";
  if (!isEmail(email)) errors.email = "Bitte eine gültige E-Mail-Adresse angeben.";
  const pw = passwordProblem(password);
  if (pw) errors.password = pw;
  if (company.length < 2) errors.company = "Bitte den Namen deiner Firma oder Agentur angeben.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const repo = getRepo();
  if (await repo.findUserByEmail(email)) {
    return { ok: false, message: "Für diese E-Mail-Adresse gibt es bereits ein Konto.", errors: { email: "Bitte anmelden oder Passwort zurücksetzen." } };
  }

  const { user, workspaceId } = await registerOwner({ email, password, displayName, company });
  await startSession(user.id, workspaceId);
  await repo.auditAs(
    { workspace_id: workspaceId, actor_id: user.id },
    { action: "workspace.created", entity: "workspaces", entity_id: workspaceId, payload: { company, plan: "starter", trial_days: 14 } },
  );
  await sendEmailVerification(user);
  redirect("/");
}
