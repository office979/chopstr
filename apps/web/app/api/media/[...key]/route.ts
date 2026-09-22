import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getSession } from "@/lib/session";
import { isTokenShape } from "@/lib/auth/tokens";
import { isDemoMode, isLocalMedia } from "@/lib/env";
import { isSafeMediaKey, localMediaPath, serveLocalFile } from "@/lib/media/local";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ key: string[] }> };

/* GET /api/media/<key> (MEDIA_MODE=local, NEXT_PUBLIC_MEDIA_BASE_URL=/api/media): Dateien aus
 * LOCAL_STORAGE_DIR/<derived-bucket>/<key>, für das Original aus dem sources-Bucket. Berechtigung:
 *   - Sitzung: der Key muss zu einer Quelle (storage_key, proxy_key, audio_key) oder einem Clip
 *     (file_key, poster_key, srt_key, vtt_key) des aktiven Workspace gehören, sonst 404;
 *   - Gast: ?t=<token> aus guest_approvals, erlaubt sind MP4 und Poster des freigegebenen Clips.
 * Range-Anfragen antworten 206 (Scrubbing im <video>), Cache-Control ist privat. */
async function handle(request: NextRequest, { params }: Params): Promise<Response> {
  if (!isLocalMedia() || isDemoMode()) return new Response("Nicht gefunden", { status: 404 });
  const { key: segments } = await params;
  const key = (segments ?? []).map((s) => decodeURIComponent(s)).join("/");
  if (!isSafeMediaKey(key)) return new Response("Nicht gefunden", { status: 404 });

  const token = request.nextUrl.searchParams.get("t");
  let bucket: "sources" | "derived" | null = null;
  if (token) {
    if (!isTokenShape(token)) return new Response("Nicht gefunden", { status: 404 });
    const view = await getRepo().getGuestApprovalByToken(token);
    if (view && (view.clip.file_key === key || view.clip.poster_key === key)) bucket = "derived";
  } else {
    const session = await getSession();
    if (!session) return Response.json({ error: "Bitte melde dich an.", code: "unauthorized" }, { status: 401 });
    bucket = await getRepo().resolveMediaBucket(key);
  }
  if (!bucket) return new Response("Nicht gefunden", { status: 404 });

  const filePath = localMediaPath(bucket, key);
  if (!filePath) return new Response("Nicht gefunden", { status: 404 });
  return serveLocalFile(filePath, key, request);
}

export async function GET(request: NextRequest, ctx: Params) {
  return handle(request, ctx);
}

export async function HEAD(request: NextRequest, ctx: Params) {
  return handle(request, ctx);
}
