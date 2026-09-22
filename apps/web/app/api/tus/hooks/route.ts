import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { uploadMaxBytes } from "@/lib/env";
import { withSessionContext, type Session } from "@/lib/session";
import { verifyUploadToken, type UploadTokenPayload } from "@/lib/auth/upload-token";
import { can } from "@/lib/auth/permissions";
import { getQuota } from "@/lib/billing/quota";
import { finalizeUpload } from "@/lib/uploads/finalize";

export const dynamic = "force-dynamic";

/* tusd v2 HTTP-Hooks. Body: { Type: 'pre-create' | 'post-finish' | ..., Event: { Upload: { ID, Size, MetaData, Storage } } }
 * Secret: Header `Hook-Secret` ODER Query-Parameter `?secret=` (tusd kann keine eigenen Header senden;
 * docker-compose ruft http://web:3000/api/tus/hooks?secret=$TUS_HOOK_SECRET auf).
 *
 * Der Hook hat keine Browser-Sitzung. Der Browser holt vor dem Upload ein Upload-Token (POST /api/uploads/token)
 * und schickt es als Metadatum `upload_token` mit. `pre-create` prüft Signatur, Ablauf, Rolle und Kontingent;
 * `post-finish` nimmt workspace_id, user_id und brand_profile_id aus dem Token (nicht aus freien Metadaten) und legt
 * die Quelle über lib/uploads/finalize.ts an (gemeinsam mit dem direkten Upload im lokalen Testmodus). */

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

      const result = await finalizeUpload({
        session,
        brandProfileId: token.payload.brand_profile_id,
        meta,
        storageKey: upload.Storage?.Key ?? upload.Storage?.Path ?? upload.ID ?? "",
        storageBucket: upload.Storage?.Bucket ?? null,
        sizeBytes: Number.isFinite(size) ? size : null,
        tusId: upload.ID ?? null,
        via: "upload_token",
      });
      return Response.json(result);
    }

    default:
      /* pre-finish, post-create, post-receive, post-terminate: nichts zu tun */
      return Response.json({});
  }
}
