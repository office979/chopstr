import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import type { ClipReview } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* Mehr Clips auf einmal ergeben keine Übersicht mehr, und ein versehentliches Sammelverwerfen
 * soll nicht das ganze Projekt treffen. */
const MAX_AUF_EINMAL = 100;

const ERLAUBT: ClipReview[] = ["offen", "bereit", "verworfen"];

/* PATCH: den Prüfstand eines oder mehrerer Clips setzen. Body: { clip_ids: [], review }.
 *
 * Bewusst umkehrbar und ohne Nebenwirkung: „verworfen" versteckt den Clip in der Übersicht,
 * löscht aber nichts. Das endgültige Löschen bleibt an seiner eigenen Stelle (DELETE auf den
 * Clip), mit Löschauftrag und Nachweis. */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id } = await params;

  let body: { clip_ids?: unknown; review?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const review = body.review;
  if (typeof review !== "string" || !ERLAUBT.includes(review as ClipReview)) {
    return Response.json({ error: `review muss eines von ${ERLAUBT.join(", ")} sein` }, { status: 400 });
  }
  const ids = Array.isArray(body.clip_ids) ? body.clip_ids.filter((x): x is string => typeof x === "string") : [];
  if (ids.length === 0) return Response.json({ error: "clip_ids fehlt" }, { status: 400 });
  if (ids.length > MAX_AUF_EINMAL) {
    return Response.json({ error: `Höchstens ${MAX_AUF_EINMAL} Clips auf einmal` }, { status: 400 });
  }

  const repo = getRepo();
  const vorhandene = await repo.listClips(id);
  const erlaubteIds = new Set(vorhandene.map((c) => c.id));
  /* Fremde Kennungen werden übergangen und nicht als Fehler gemeldet: die Liste kann veraltet
   * sein, und ein halb durchgeführter Sammelbefehl ist schlimmer als ein übergangener Clip. */
  const ziele = ids.filter((x) => erlaubteIds.has(x));
  if (ziele.length === 0) return Response.json({ error: "Kein Clip aus diesem Projekt dabei" }, { status: 404 });

  const geaendert = [];
  for (const clipId of ziele) {
    const c = await repo.updateClip(clipId, { review: review as ClipReview });
    if (c) geaendert.push(c);
  }

  await repo.audit({
    action: "clip.review",
    entity: "clips",
    entity_id: ziele[0],
    payload: { source_id: id, review, anzahl: geaendert.length, clip_ids: ziele },
  });

  return Response.json({ ok: true, review, clips: geaendert });
}
