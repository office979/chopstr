import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import type { Zeitmarke } from "@/lib/repo/types";
import { alsZahl } from "@/lib/zahl";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* Höchstens so viele Marken je Clip. Wer mehr setzt, baut keinen Clip mehr, sondern eine Montage;
 * und die Zeitleiste würde unlesbar. */
const MAX_MARKEN = 60;

/* Marken aus fremder Hand auf das Brauchbare zurechtschneiden: Zahlen, aufsteigend, keine zwei an
 * derselben Stelle. Der Renderer prüft ein zweites Mal, denn die API ist offen. */
export function markenPruefen(roh: unknown): Zeitmarke[] {
  if (!Array.isArray(roh)) return [];
  const sauber: Zeitmarke[] = [];
  for (const m of roh) {
    if (!m || typeof m !== "object") continue;
    const q = m as Record<string, unknown>;
    const ab = alsZahl(q.ab_s);
    const x = alsZahl(q.x);
    if (ab == null || x == null || ab < 0 || x < 0) continue;
    sauber.push({ ab_s: Math.round(ab * 100) / 100, x: Math.round(x) });
  }
  sauber.sort((a, b) => a.ab_s - b.ab_s);
  /* Zwei Marken an derselben Sekunde: die spätere gewinnt, sonst hinge das Ergebnis an der
   * Reihenfolge im Body. */
  const eindeutig = sauber.filter((m, i) => i === sauber.length - 1 || sauber[i + 1].ab_s !== m.ab_s);
  return eindeutig.slice(0, MAX_MARKEN);
}

/* PATCH: Entscheidungen aus der Zeitleiste setzen. Body: { zeitmarken: [{ab_s, x}] }.
 * Wirkt beim nächsten Render. */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: { zeitmarken?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const marken = markenPruefen(body.zeitmarken);
  const extras = await getPublishingRepo().updateClipExtras(clipId, { zeitmarken: marken });
  if (!extras) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  await repo.audit({ action: "clip.zeitmarken", entity: "clips", entity_id: clipId, payload: { source_id: id, anzahl: marken.length } });
  return Response.json({
    ok: true,
    zeitmarken: marken,
    needs_render: clip.status === "rendered" || clip.status === "exported",
  });
}
