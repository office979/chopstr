import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* GET: Clip mit aktueller Hook-Version und aktuellen Captions */
export async function GET(_request: NextRequest, { params }: Params) {
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  const [hook, captions] = await Promise.all([repo.getCurrentHook(clipId), repo.getCurrentCaptions(clipId)]);
  return Response.json({ clip, hook, captions });
}
