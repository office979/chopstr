"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import { requireRole } from "@/lib/session";
import { isForbiddenError } from "@/lib/auth/permissions";
import { sendMail } from "@/lib/auth/mail";
import { appBaseUrl } from "@/lib/auth/url";
import { CONSOLE_LINK_HINT, field, type FormState } from "@/lib/auth/form";

const WORKSPACE_DELETION_GRACE_DAYS = 30;

/* Workspace-Löschung anfordern (owner): 30 Tage Karenz, deletion_requested_at und deletion_scheduled_for,
 * E-Mail an den Inhaber (oder Konsole), Audit workspace.delete_requested. Danach legt der Retention-Lauf den Job an. */
export async function requestWorkspaceDeletionAction(_prev: FormState, formData: FormData): Promise<FormState> {
  let session;
  try {
    session = await requireRole("workspace.delete");
  } catch (error) {
    if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
    throw error;
  }
  const repo = getRepo();
  const ws = await repo.getWorkspace();
  if (ws.deletion_scheduled_for) return { ok: false, message: "Die Löschung ist bereits eingeplant.", errors: {} };
  const confirm = field(formData, "confirm_name", 120);
  if (confirm !== ws.name.trim()) return { ok: false, message: "Bitte den Namen des Teams genau eingeben.", errors: { confirm_name: `Erwartet: ${ws.name}` } };

  const scheduledFor = new Date(Date.now() + WORKSPACE_DELETION_GRACE_DAYS * 86_400_000).toISOString();
  const updated = await repo.requestWorkspaceDeletion(scheduledFor);
  const base = await appBaseUrl();
  const link = `${base}/einstellungen/loeschung`;
  const when = new Date(scheduledFor).toLocaleDateString("de-AT", { day: "2-digit", month: "2-digit", year: "numeric" });
  const mail = await sendMail({
    to: session.email,
    subject: `Löschung des Teams „${ws.name}“ eingeplant für ${when}`,
    text: [
      `Hallo ${session.displayName},`,
      "",
      `du hast die Löschung des Teams „${ws.name}“ angefordert. Sie wird am ${when} ausgeführt: alle Quellen, Clips, Transkripte und CI-Assets werden aus Objektspeicher und Datenbank entfernt, der Löschnachweis bleibt im Audit-Log.`,
      "",
      `Bis dahin kannst du die Löschung zurücknehmen: ${link}`,
      "",
      "chopstr · EU-verarbeitet",
    ].join("\n"),
    link,
  });
  await repo.audit({
    action: "workspace.delete_requested",
    entity: "workspaces",
    entity_id: updated.id,
    payload: { scheduled_for: scheduledFor, grace_days: WORKSPACE_DELETION_GRACE_DAYS, mail_delivered: mail.delivered, mail_logged: mail.logged },
  });
  revalidatePath("/einstellungen/loeschung");
  return {
    ok: true,
    message: `Löschung eingeplant für ${when}. Bis dahin kannst du sie zurücknehmen.`,
    errors: {},
    hint: mail.logged ? CONSOLE_LINK_HINT : undefined,
  };
}

export async function cancelWorkspaceDeletionAction(): Promise<FormState> {
  try {
    await requireRole("workspace.delete");
  } catch (error) {
    if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
    throw error;
  }
  const repo = getRepo();
  const ws = await repo.getWorkspace();
  if (!ws.deletion_scheduled_for) return { ok: false, message: "Es ist keine Löschung eingeplant.", errors: {} };
  const updated = await repo.cancelWorkspaceDeletion();
  await repo.audit({ action: "workspace.delete_canceled", entity: "workspaces", entity_id: updated.id, payload: { was_scheduled_for: ws.deletion_scheduled_for } });
  revalidatePath("/einstellungen/loeschung");
  return { ok: true, message: "Löschung zurückgenommen. Das Team bleibt bestehen.", errors: {} };
}
