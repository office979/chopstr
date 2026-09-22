import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { uploadMaxBytes } from "@/lib/env";
import { startClipProjectWorkflow } from "@/lib/temporal";
import { withSessionContext, type Session } from "@/lib/session";
import { verifyUploadToken, type UploadTokenPayload } from "@/lib/auth/upload-token";
import { can } from "@/lib/auth/permissions";
import { getQuota } from "@/lib/billing/quota";
import type { Brief, Platform, RightsStatus } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

/* tusd v2 HTTP-Hooks. Body: { Type: 'pre-create' | 'post-finish' | ..., Event: { Upload: { ID, Size, MetaData, Storage } } }
 * Secret: Header `Hook-Secret` ODER Query-Parameter `?secret=` (tusd kann keine eigenen Header senden;
 * docker-compose ruft http://web:3000/api/tus/hooks?secret=$TUS_HOOK_SECRET auf).
 *
 * Der Hook hat keine Browser-Sitzung. Der Browser holt vor dem Upload ein Upload-Token (POST /api/uploads/token)
 * und schickt es als Metadatum `upload_token` mit. `pre-create` prüft Signatur, Ablauf, Rolle und Kontingent;
 * `post-finish` nimmt workspace_id, user_id und brand_profile_id aus dem Token (nicht aus freien Metadaten). */

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

/* Sitzung aus dem Upload-Token: Nutzer und Mitgliedschaft müssen noch bestehen */
async function sessionFromToken(payload: UploadTokenPayload): Promise<Session | { error: string; status: number }> {
  const repo = getRepo();
  const [user, membership] = await Promise.all([repo.getUser(payload.user_id), repo.getMembership(payload.user_id, payload.workspace_id)]);
  if (!user || !membership) return { error: "Upload-Token gehört zu keiner gültigen Mitgliedschaft.", status: 401 };
  if (!can(membership.role, "source.upload")) return { error: "Uploads sind für deine Rolle nicht freigegeben.", status: 403 };
  return {
    sessionId: null,
    userId: user.id,
    email: user.email,
    displayName: user.display_name ?? user.email,
    emailVerified: user.email_verified_at != null,
    locale: user.locale,
    activeWorkspaceId: membership.workspace_id,
    demo: false,
    workspaceId: membership.workspace_id,
    workspaceName: membership.workspace_name,
    role: membership.role,
    brandScope: membership.role === "client" ? membership.brand_profile_id : null,
  };
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
      const token = verifyUploadToken(meta.upload_token);
      if (!token.ok) return reject(401, token.error);
      const session = await sessionFromToken(token.payload);
      if ("error" in session) return reject(session.status, session.error);
      if (meta.rights_confirmed !== "true") {
        return reject(400, "Die Rechte am Material müssen bestätigt werden.");
      }
      if (!Number.isFinite(size) || size <= 0 || size > uploadMaxBytes()) {
        return reject(400, `Datei zu groß. Maximal ${Math.round(uploadMaxBytes() / (1024 * 1024 * 1024))} GB.`);
      }
      if (!meta.title?.trim()) {
        return reject(400, "Titel fehlt.");
      }
      const quota = await withSessionContext(session, () => getQuota(getRepo()));
      if (quota.exhausted) return reject(402, quota.message ?? "Stundenkontingent ausgeschöpft");
      return Response.json({});
    }

    case "post-finish": {
      const token = verifyUploadToken(meta.upload_token);
      if (!token.ok) return new Response(token.error, { status: 401 });
      const session = await sessionFromToken(token.payload);
      if ("error" in session) return new Response(session.error, { status: session.status });

      return withSessionContext(session, async () => {
        const repo = getRepo();
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
          brand_profile_id: token.payload.brand_profile_id,
          title: meta.title?.trim() || meta.filename || "Ohne Titel",
          original_filename: meta.filename ?? null,
          mime_type: meta.filetype ?? null,
          size_bytes: Number.isFinite(size) ? size : null,
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
            via: "upload_token",
          },
        });
        await repo.audit({
          action: "rights.confirmed",
          entity: "sources",
          entity_id: source.id,
          payload: { rights_status: rightsStatus, confirmed_by: session.userId },
        });

        const workflowId = await startClipProjectWorkflow({ sourceId: source.id, workspaceId: session.workspaceId });
        if (workflowId) {
          await repo.updateSource(source.id, { temporal_workflow_id: workflowId });
        }

        return Response.json({ source_id: source.id, workflow_id: workflowId });
      });
    }

    default:
      /* pre-finish, post-create, post-receive, post-terminate: nichts zu tun */
      return Response.json({});
  }
}
