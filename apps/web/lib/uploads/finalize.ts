import "server-only";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { startClipProjectWorkflow } from "@/lib/temporal";
import { withSessionContext, type Session } from "@/lib/session";
import type { Brief, Platform, RightsStatus } from "@/lib/repo/types";

/* Gemeinsame Anlage einer Quelle nach abgeschlossenem Upload. Genutzt vom tusd-Hook (post-finish) und vom
 * direkten Upload (POST /api/uploads/direct, lokaler Testmodus): Quelle mit storage_key, Audit `upload.created`
 * und `rights.confirmed`, dann Temporal-Start. Ohne TEMPORAL_ADDRESS bleibt die Quelle `uploaded`, der lokale
 * Worker (python -m chopstr_worker.local_worker) holt sie per Polling ab. */

const RIGHTS: RightsStatus[] = ["own", "licensed", "third_party"];
const PLATFORMS: Platform[] = ["tiktok", "reels", "shorts", "linkedin"];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/* Metadaten wie beim tus-Upload: title, filename, filetype, rights_status, expected_speakers, brief_*, platform,
 * source_owner/title/url, client_ref. Alle Werte sind Strings (tus-MetaData, multipart-Felder). */
export type UploadMeta = Record<string, string | undefined>;

export interface FinalizeUploadInput {
  session: Session;
  /* Markenprofil aus Token oder geprüfter Formulareingabe, nicht aus freien Metadaten */
  brandProfileId: string | null;
  meta: UploadMeta;
  storageKey: string;
  storageBucket: string | null;
  sizeBytes: number | null;
  sha256?: string | null;
  tusId?: string | null;
  /* Audit-Herkunft: upload_token (tusd), api_upload_token (POST /api/v1/sources) oder direct */
  via: "upload_token" | "direct";
}

export interface FinalizeUploadResult {
  source_id: string;
  workflow_id: string | null;
}

export function parseRightsStatus(raw: string | undefined): RightsStatus {
  return (RIGHTS as string[]).includes(raw ?? "") ? (raw as RightsStatus) : "own";
}

export function parsePlatform(raw: string | undefined): Platform | undefined {
  return (PLATFORMS as string[]).includes(raw ?? "") ? (raw as Platform) : undefined;
}

export function isUuid(raw: string | undefined | null): raw is string {
  return typeof raw === "string" && UUID_RE.test(raw);
}

export async function finalizeUpload(input: FinalizeUploadInput): Promise<FinalizeUploadResult> {
  const { session, meta, storageKey, storageBucket, sizeBytes, via } = input;
  return withSessionContext(session, async () => {
    const repo = getRepo();
    const rightsStatus = parseRightsStatus(meta.rights_status);
    const brief: Brief = {
      audience: meta.brief_audience || undefined,
      wanted: meta.brief_wanted || undefined,
      exclude: meta.brief_exclude || undefined,
      platform: parsePlatform(meta.platform),
    };
    const expected = Number(meta.expected_speakers);
    const clientRef = isUuid(meta.client_ref) ? meta.client_ref : undefined;
    const mimeType = meta.filetype || null;
    const auditPayload = {
      storage_key: storageKey,
      storage_bucket: storageBucket,
      size_bytes: sizeBytes,
      mime_type: mimeType,
      sha256: input.sha256 ?? null,
      tus_id: input.tusId ?? null,
    };

    /* Phase 5a: POST /api/v1/sources mit upload = tus hat die Quelle schon als `uploading` angelegt (client_ref = source.id) */
    const pending = clientRef ? await repo.getSource(clientRef) : null;
    if (pending && pending.status === "uploading") {
      const completed = await getApiRepo().completeUploadingSource(pending.id, {
        storage_key: storageKey,
        original_filename: meta.filename || null,
        mime_type: mimeType,
        size_bytes: sizeBytes,
        sha256: input.sha256 ?? null,
      });
      if (completed) {
        await repo.audit({
          action: "upload.created",
          entity: "sources",
          entity_id: pending.id,
          payload: { ...auditPayload, via: via === "direct" ? "api_direct" : "api_upload_token" },
        });
        const workflowId = await startClipProjectWorkflow({ sourceId: pending.id, workspaceId: session.workspaceId });
        if (workflowId) await repo.updateSource(pending.id, { temporal_workflow_id: workflowId });
        return { source_id: pending.id, workflow_id: workflowId };
      }
    }

    const source = await repo.createSource({
      id: clientRef,
      brand_profile_id: input.brandProfileId,
      title: meta.title?.trim() || meta.filename || "Ohne Titel",
      original_filename: meta.filename || null,
      mime_type: mimeType,
      size_bytes: sizeBytes,
      sha256: input.sha256 ?? null,
      storage_key: storageKey,
      storage_bucket: storageBucket,
      rights_status: rightsStatus,
      rights_confirmed_by: session.userId,
      source_owner: rightsStatus === "third_party" ? meta.source_owner ?? null : null,
      source_title: rightsStatus === "third_party" ? meta.source_title ?? null : null,
      source_url: rightsStatus === "third_party" ? meta.source_url ?? null : null,
      expected_speakers: Number.isFinite(expected) && expected > 0 ? Math.round(expected) : null,
      brief,
      status: "uploaded",
    });

    await repo.audit({ action: "upload.created", entity: "sources", entity_id: source.id, payload: { ...auditPayload, via } });
    await repo.audit({
      action: "rights.confirmed",
      entity: "sources",
      entity_id: source.id,
      payload: { rights_status: rightsStatus, confirmed_by: session.userId },
    });

    const workflowId = await startClipProjectWorkflow({ sourceId: source.id, workspaceId: session.workspaceId });
    if (workflowId) await repo.updateSource(source.id, { temporal_workflow_id: workflowId });

    return { source_id: source.id, workflow_id: workflowId };
  });
}
