import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import { dauer as schnittDauer } from "@/lib/clips/schnitt";
import { lesen } from "@/lib/clips/effekte";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* Höchstens so viele Effekte je Clip. Wer mehr setzt, betont nichts mehr, sondern wackelt. */
const MAX_EFFEKTE = 12;

/* PATCH: die Effekte dieses Clips setzen. Body: { effekte: [{art, ab_s, dauer_s}] }.
 *
 * Eine LEERE Liste ist eine Aussage und kein Nichts: sie heisst „ich will keine", und der
 * Renderlauf legt dann auch keine automatischen mehr an (Migration 0015). Genau deshalb schreibt
 * diese Route immer, auch wenn nichts drinsteht.
 */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: { effekte?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (!Array.isArray(body.effekte)) {
    return Response.json({ error: "effekte muss eine Liste sein" }, { status: 400 });
  }
  /* Dieselbe Prüfung wie in der Oberfläche und im Renderer. Die Schnittstelle ist offen, also
   * wird hier ein zweites Mal geprüft statt darauf zu vertrauen, dass die Seite sauber liefert. */
  const effekte = lesen(body.effekte, schnittDauer(clip.composition)).slice(0, MAX_EFFEKTE);
  const extras = await getPublishingRepo().updateClipExtras(clipId, { effekte });
  if (!extras) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  await repo.audit({
    action: "clip.effekte",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, anzahl: effekte.length },
  });
  return Response.json({
    ok: true,
    effekte,
    needs_render: clip.status === "rendered" || clip.status === "exported",
  });
}
