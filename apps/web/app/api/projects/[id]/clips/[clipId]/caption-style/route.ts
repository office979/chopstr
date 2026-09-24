import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import { stilPruefen } from "@/lib/clips/caption-style";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* PATCH: Untertitel-Stil dieses Clips setzen (Migration 0008).
 *
 * Body: { caption_style: { font, font_px, words_per_card, ... } } oder null zum Zuruecksetzen.
 * Was der Renderer nicht kennt, wird hier schon verworfen: in der Datenbank soll nur stehen, was
 * auch Wirkung hat. Der Renderer prueft trotzdem ein zweites Mal, denn die API ist offen.
 *
 * Wirkt beim naechsten Render. Ein bereits gerenderter Clip bleibt, wie er ist, bis er neu laeuft. */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: { caption_style?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const style = body.caption_style == null ? {} : stilPruefen(body.caption_style);
  const extras = await getPublishingRepo().updateClipExtras(clipId, { caption_style: style });
  if (!extras) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  await repo.audit({
    action: "clip.caption_style",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, caption_style: style },
  });
  return Response.json({
    ok: true,
    caption_style: extras.caption_style,
    needs_render: clip.status === "rendered" || clip.status === "exported",
  });
}
