"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingRole, PublishingForbiddenError } from "@/lib/publishing/auth";
import type { FormState } from "@/lib/auth/form";

/* Opt-out Wochenreport (owner, admin): workspaces.weekly_report_enabled */
export async function setWeeklyReportAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requirePublishingRole("publishing.manage");
  } catch (error) {
    if (error instanceof PublishingForbiddenError) return { ok: false, message: error.message, errors: {} };
    throw error;
  }
  const enabled = formData.get("enabled") === "true";
  const value = await getPublishingRepo().setWeeklyReportEnabled(enabled);
  await getRepo().audit({ action: "workspace.weekly_report", entity: "workspaces", entity_id: null, payload: { enabled: value } });
  revalidatePath("/berichte");
  return { ok: true, message: value ? "Wochenbericht per E-Mail aktiviert." : "Wochenbericht per E-Mail abbestellt. Die Seite bleibt erreichbar.", errors: {} };
}
