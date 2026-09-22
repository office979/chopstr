"use server";

import { revalidatePath } from "next/cache";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { sendEmailVerification } from "@/lib/auth/service";
import { isEmail, normalizeEmail } from "@/lib/auth/tokens";
import { CONSOLE_LINK_HINT, field, type FormState } from "@/lib/auth/form";

const LOCALES = ["de-AT", "de-DE", "de-CH"];

/* Profil: Anzeigename, Sprache, E-Mail (Änderung setzt die Bestätigung zurück und schickt einen Link) */
export async function updateProfileAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const session = await requireSession();
  if (isDemoMode()) return { ok: false, message: "Demo-Modus: Profiländerungen werden nicht gespeichert.", errors: {} };
  const displayName = field(formData, "display_name", 80);
  const email = normalizeEmail(formData.get("email"));
  const locale = field(formData, "locale", 10);
  const errors: Record<string, string> = {};
  if (displayName.length < 2) errors.display_name = "Bitte einen Namen mit mindestens zwei Zeichen angeben.";
  if (!isEmail(email)) errors.email = "Bitte eine gültige E-Mail-Adresse angeben.";
  if (!LOCALES.includes(locale)) errors.locale = "Bitte eine Sprache wählen.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const repo = getRepo();
  const emailChanged = email !== session.email.toLowerCase();
  if (emailChanged) {
    const taken = await repo.findUserByEmail(email);
    if (taken && taken.id !== session.userId) {
      return { ok: false, message: "Diese E-Mail-Adresse wird bereits verwendet.", errors: { email: "Bitte eine andere Adresse wählen." } };
    }
  }
  const user = await repo.updateUser(session.userId, {
    display_name: displayName,
    locale,
    ...(emailChanged ? { email, email_verified_at: null } : {}),
  });
  if (!user) return { ok: false, message: "Konto nicht gefunden.", errors: {} };
  await repo.audit({ action: "profile.updated", entity: "users", entity_id: session.userId, payload: { email_changed: emailChanged, locale } });

  let hint: string | undefined;
  if (emailChanged) {
    const result = await sendEmailVerification(user);
    if (result.logged) hint = CONSOLE_LINK_HINT;
  }
  revalidatePath("/profil");
  return {
    ok: true,
    message: emailChanged ? "Profil gespeichert. Bitte bestätige die neue E-Mail-Adresse über den Link in deinem Postfach." : "Profil gespeichert.",
    errors: {},
    hint,
  };
}

export async function resendVerificationAction(): Promise<FormState> {
  const session = await requireSession();
  if (isDemoMode()) return { ok: false, message: "Demo-Modus: Es gibt nichts zu bestätigen.", errors: {} };
  const user = await getRepo().getUser(session.userId);
  if (!user) return { ok: false, message: "Konto nicht gefunden.", errors: {} };
  if (user.email_verified_at) return { ok: true, message: "Die Adresse ist bereits bestätigt.", errors: {} };
  const result = await sendEmailVerification(user);
  return { ok: true, message: "Bestätigungslink gesendet (15 Minuten gültig).", errors: {}, hint: result.logged ? CONSOLE_LINK_HINT : undefined };
}
