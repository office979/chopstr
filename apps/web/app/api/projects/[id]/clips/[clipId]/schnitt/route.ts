import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { alsZahl } from "@/lib/zahl";
import { aufraeumen, dauer, MIN_ABSCHNITT_S, type Schnitt } from "@/lib/clips/schnitt";
import type { CandidateSegment } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* Mehr Abschnitte ergeben keinen Clip mehr, sondern eine Montage; und die Zeitleiste würde
 * unlesbar. */
const MAX_ABSCHNITTE = 40;

/* Abschnitte aus fremder Hand auf das Brauchbare zurechtschneiden. Der Renderer prüft nicht noch
 * einmal, deshalb ist das hier die Stelle, an der Unsinn hängen bleiben muss. */
export function schnittPruefen(roh: unknown, quelleDauer: number | null): Schnitt | null {
  if (!Array.isArray(roh) || roh.length === 0) return null;
  const sauber: CandidateSegment[] = [];
  for (const a of roh.slice(0, MAX_ABSCHNITTE)) {
    if (!a || typeof a !== "object") continue;
    const q = a as Record<string, unknown>;
    const start = alsZahl(q.start);
    const end = alsZahl(q.end);
    if (start == null || end == null || start < 0 || end <= start) continue;
    const rolle = q.role === "teaser" ? "teaser" : "body";
    const bis = quelleDauer != null && quelleDauer > 0 ? Math.min(end, quelleDauer) : end;
    if (bis - start < MIN_ABSCHNITT_S) continue;
    sauber.push({ start: Math.round(start * 1000) / 1000, end: Math.round(bis * 1000) / 1000, role: rolle });
  }
  const fertig = aufraeumen(sauber);
  return fertig.length ? fertig : null;
}

/* PATCH: den Schnitt des Clips setzen. Body: { composition: [{start, end, role}] }.
 *
 * Geändert wird ausschließlich diese Liste; die hochgeladene Datei bleibt unangetastet. Wirksam
 * wird sie beim nächsten Clippen - und das stößt die Oberfläche direkt nach dem Speichern an. */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const [clip, source] = await Promise.all([repo.getClip(clipId), repo.getSource(id)]);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: { composition?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const schnitt = schnittPruefen(body.composition, source?.duration_s ?? null);
  if (!schnitt) return Response.json({ error: "Der Schnitt braucht mindestens einen brauchbaren Abschnitt" }, { status: 400 });

  const aktualisiert = await repo.updateClip(clipId, { composition: schnitt });
  if (!aktualisiert) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  await repo.audit({
    action: "clip.schnitt",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, abschnitte: schnitt.length, dauer_s: Math.round(dauer(schnitt) * 100) / 100 },
  });
  return Response.json({
    ok: true,
    composition: schnitt,
    dauer_s: Math.round(dauer(schnitt) * 100) / 100,
    needs_render: clip.status === "rendered" || clip.status === "exported",
  });
}
