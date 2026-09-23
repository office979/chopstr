"use server";

import { getRepo } from "@/lib/repo";
import { isDemoMode } from "@/lib/env";
import { startClipProjectWorkflow } from "@/lib/temporal";
import { requireRole } from "@/lib/session";
import { isForbiddenError } from "@/lib/auth/permissions";
import type { Platform, RightsStatus } from "@/lib/repo/types";

export interface DemoUploadInput {
  title: string;
  brand_profile_id: string | null;
  filename: string;
  filetype: string;
  size_bytes: number;
  rights_status: RightsStatus;
  rights_confirmed: boolean;
  /* Das Formular erhebt Zielgruppe, Wünsche, Plattform und Sprecherzahl nicht mehr. Die Felder
   * bleiben optional, damit ältere Aufrufer (API, Tests) weiterhin gültig sind. */
  expected_speakers?: number | null;
  brief_audience?: string;
  brief_wanted?: string;
  brief_exclude?: string;
  platform?: Platform | "";
  source_owner?: string;
  source_title?: string;
  source_url?: string;
}

/* Demo-Modus: legt nach dem simulierten Upload ein Projekt an (ohne tusd, ohne Temporal). */
export async function createDemoProject(input: DemoUploadInput): Promise<{ id: string } | { error: string }> {
  if (!isDemoMode() && process.env.NEXT_PUBLIC_DEMO_UPLOAD !== "true") {
    return { error: "Der simulierte Upload ist nur im Demo-Modus verfügbar." };
  }
  if (!input.rights_confirmed) return { error: "Die Rechte am Material müssen bestätigt werden." };
  if (!input.title.trim()) return { error: "Titel fehlt." };

  let session;
  try {
    session = await requireRole("source.upload");
  } catch (error) {
    if (isForbiddenError(error)) return { error: error.message };
    throw error;
  }
  const { workspaceId, userId: actorId } = session;
  const repo = getRepo();
  const id = globalThis.crypto.randomUUID();
  const source = await repo.createSource({
    id,
    brand_profile_id: input.brand_profile_id,
    title: input.title.trim(),
    original_filename: input.filename,
    mime_type: input.filetype,
    size_bytes: input.size_bytes,
    storage_key: `sources/${workspaceId}/${id}/${input.filename}`,
    rights_status: input.rights_status,
    rights_confirmed_by: actorId,
    source_owner: input.rights_status === "third_party" ? input.source_owner ?? null : null,
    source_title: input.rights_status === "third_party" ? input.source_title ?? null : null,
    source_url: input.rights_status === "third_party" ? input.source_url ?? null : null,
    expected_speakers: input.expected_speakers ?? null,
    brief: {
      audience: input.brief_audience || undefined,
      wanted: input.brief_wanted || undefined,
      exclude: input.brief_exclude || undefined,
      platform: input.platform || undefined,
    },
    status: "uploaded",
  });
  await repo.audit({ action: "upload.created", entity: "sources", entity_id: source.id, payload: { demo: true } });
  await repo.audit({ action: "rights.confirmed", entity: "sources", entity_id: source.id, payload: { rights_status: input.rights_status } });
  await startClipProjectWorkflow({ sourceId: source.id, workspaceId });
  return { id: source.id };
}
