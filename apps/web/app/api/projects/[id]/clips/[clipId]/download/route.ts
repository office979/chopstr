import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiSession } from "@/lib/auth/guard";
import { mediaUrl } from "@/lib/clips/labels";
import { EXPORT_BLOCKED_MESSAGE, exportBlocked, latestByClip } from "@/lib/guest/approval";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

const KINDS = { mp4: "file_key", srt: "srt_key", vtt: "vtt_key", poster: "poster_key" } as const;

/* GET ?kind=mp4|srt|vtt|poster: Export-Link mit Gast-Freigabe-Sperre (409, solange guest_approval_required ohne
 * approved-Entscheidung). Sonst Umleitung auf die Medien-URL; ein MP4-Download setzt den Clip auf exported. */
export async function GET(request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const kind = request.nextUrl.searchParams.get("kind") ?? "mp4";
  if (!(kind in KINDS)) return Response.json({ error: "kind muss mp4, srt, vtt oder poster sein" }, { status: 400 });
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  const approvals = latestByClip(await repo.listGuestApprovals(id));
  if (exportBlocked(clip, approvals.get(clip.id))) {
    return Response.json({ error: EXPORT_BLOCKED_MESSAGE, code: "guest_approval_pending" }, { status: 409 });
  }
  const key = clip[KINDS[kind as keyof typeof KINDS]];
  const url = mediaUrl(process.env.NEXT_PUBLIC_MEDIA_BASE_URL, key);
  if (!url) return Response.json({ error: "Datei noch nicht verfügbar" }, { status: 404 });

  if (kind === "mp4" && clip.status === "rendered") {
    await repo.updateClip(clip.id, { status: "exported" });
    await repo.audit({ action: "export.created", entity: "clips", entity_id: clip.id, payload: { source_id: id, kind, key } });
  }
  /* Lokaler Modus: NEXT_PUBLIC_MEDIA_BASE_URL ist relativ (/api/media), Response.redirect braucht eine absolute URL */
  return Response.redirect(new URL(url, request.nextUrl.origin), 302);
}
