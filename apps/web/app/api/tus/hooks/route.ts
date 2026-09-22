import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { uploadMaxBytes } from "@/lib/env";
import { startClipProjectWorkflow } from "@/lib/temporal";
import { getSession } from "@/lib/session";
import type { Brief, Platform, RightsStatus } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

/* tusd v2 HTTP-Hooks. Body: { Type: 'pre-create' | 'post-finish' | ..., Event: { Upload: { ID, Size, MetaData, Storage } } }
 * Secret: Header `Hook-Secret` ODER Query-Parameter `?secret=` (tusd kann keine eigenen Header senden;
 * docker-compose ruft http://web:3000/api/tus/hooks?secret=$TUS_HOOK_SECRET auf). */

interface TusStorage {
  Type?: string;
  Bucket?: string;
  Key?: string;
  Path?: string;
}

interface TusUpload {
  ID?: string;
  Size?: number;
  SizeIsDeferred?: boolean;
  MetaData?: Record<string, string>;
  Storage?: TusStorage;
}

interface TusHookBody {
  Type?: string;
  Event?: { Upload?: TusUpload };
}

const RIGHTS: RightsStatus[] = ["own", "licensed", "third_party"];
const PLATFORMS: Platform[] = ["tiktok", "reels", "shorts", "linkedin"];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function reject(status: number, message: string) {
  return Response.json({ RejectUpload: true, HTTPResponse: { StatusCode: status, Body: message } });
}

function secretOk(request: NextRequest): { ok: boolean; warning?: string } {
  const expected = process.env.TUS_HOOK_SECRET;
  if (!expected) {
    return { ok: true, warning: "TUS_HOOK_SECRET nicht gesetzt, Hook wird ohne Prüfung angenommen (nur Entwicklung)" };
  }
  const header = request.headers.get("hook-secret");
  const query = request.nextUrl.searchParams.get("secret");
  return { ok: header === expected || query === expected };
}

export async function POST(request: NextRequest) {
  const check = secretOk(request);
  if (!check.ok) {
    return new Response("Ungültiges Hook-Secret", { status: 401 });
  }
  if (check.warning) console.warn(`[tus-hook] ${check.warning}`);

  let body: TusHookBody;
  try {
    body = (await request.json()) as TusHookBody;
  } catch {
    return new Response("Ungültiger JSON-Body", { status: 400 });
  }

  const upload = body.Event?.Upload ?? {};
  const meta = upload.MetaData ?? {};
  const size = typeof upload.Size === "number" ? upload.Size : Number(upload.Size ?? 0);

  switch (body.Type) {
    case "pre-create": {
      if (meta.rights_confirmed !== "true") {
        return reject(400, "Die Rechte am Material müssen bestätigt werden.");
      }
      if (!Number.isFinite(size) || size <= 0 || size > uploadMaxBytes()) {
        return reject(400, `Datei zu groß. Maximal ${Math.round(uploadMaxBytes() / (1024 * 1024 * 1024))} GB.`);
      }
      if (!meta.title?.trim()) {
        return reject(400, "Titel fehlt.");
      }
      return Response.json({});
    }

    case "post-finish": {
      const repo = getRepo();
      const session = getSession();
      const workspaceId = meta.workspace_id && UUID_RE.test(meta.workspace_id) ? meta.workspace_id : session.workspaceId;
      const rightsStatus = (RIGHTS as string[]).includes(meta.rights_status ?? "") ? (meta.rights_status as RightsStatus) : "own";
      const platform = (PLATFORMS as string[]).includes(meta.platform ?? "") ? (meta.platform as Platform) : undefined;
      const brief: Brief = {
        audience: meta.brief_audience || undefined,
        wanted: meta.brief_wanted || undefined,
        exclude: meta.brief_exclude || undefined,
        platform,
      };
      const expected = Number(meta.expected_speakers);
      const storageKey = upload.Storage?.Key ?? upload.Storage?.Path ?? upload.ID ?? "";
      const storageBucket = upload.Storage?.Bucket ?? null;
      const clientRef = meta.client_ref && UUID_RE.test(meta.client_ref) ? meta.client_ref : undefined;

      const source = await repo.createSource({
        id: clientRef,
        brand_profile_id: meta.brand_profile_id && UUID_RE.test(meta.brand_profile_id) ? meta.brand_profile_id : null,
        title: meta.title?.trim() || meta.filename || "Ohne Titel",
        original_filename: meta.filename ?? null,
        mime_type: meta.filetype ?? null,
        size_bytes: Number.isFinite(size) ? size : null,
        storage_key: storageKey,
        storage_bucket: storageBucket,
        rights_status: rightsStatus,
        rights_confirmed_by: session.actorId,
        source_owner: rightsStatus === "third_party" ? meta.source_owner ?? null : null,
        source_title: rightsStatus === "third_party" ? meta.source_title ?? null : null,
        source_url: rightsStatus === "third_party" ? meta.source_url ?? null : null,
        expected_speakers: Number.isFinite(expected) && expected > 0 ? Math.round(expected) : null,
        brief,
        status: "uploaded",
      });

      await repo.audit({
        action: "upload.created",
        entity: "sources",
        entity_id: source.id,
        payload: {
          storage_key: storageKey,
          storage_bucket: storageBucket,
          size_bytes: size,
          mime_type: meta.filetype ?? null,
          tus_id: upload.ID ?? null,
        },
      });
      await repo.audit({
        action: "rights.confirmed",
        entity: "sources",
        entity_id: source.id,
        payload: { rights_status: rightsStatus, confirmed_by: session.actorId },
      });

      const workflowId = await startClipProjectWorkflow({ sourceId: source.id, workspaceId });
      if (workflowId) {
        await repo.updateSource(source.id, { temporal_workflow_id: workflowId });
      }

      return Response.json({ source_id: source.id, workflow_id: workflowId });
    }

    default:
      /* pre-finish, post-create, post-receive, post-terminate: nichts zu tun */
      return Response.json({});
  }
}
