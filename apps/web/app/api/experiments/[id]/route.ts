import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { decisionCheck, posteriorAOverB, variantStats } from "@/lib/experiments/stats";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* POST: Gewinner setzen ({ winner: "A" | "B" }). Nur wenn beide Varianten 48 h veröffentlicht sind und die Mindestexposure
 * erreicht ist; Konfidenz (P(A > B)) wird gespeichert, Audit experiment.decided. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("experiments.manage");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const pub = getPublishingRepo();
  const experiment = await pub.getExperiment(id);
  if (!experiment) return Response.json({ error: "Experiment nicht gefunden" }, { status: 404 });
  let body: { winner?: unknown; hypothesis?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (typeof body.hypothesis === "string" && body.winner === undefined) {
    const updated = await pub.updateExperiment(id, { hypothesis: body.hypothesis.trim().slice(0, 500) || null });
    return Response.json({ ok: true, experiment: updated });
  }
  if (body.winner !== "A" && body.winner !== "B") return Response.json({ error: "winner muss A oder B sein" }, { status: 400 });
  const clips = await pub.listClipsForExperiment(id);
  const a = clips.find((c) => c.variant === "A") ?? null;
  const b = clips.find((c) => c.variant === "B") ?? null;
  if (!a || !b) return Response.json({ error: "Beide Varianten brauchen einen Clip." }, { status: 409 });
  const ids = [a.id, b.id];
  const [publications, feedback] = await Promise.all([pub.listPublicationsForClips(ids), pub.listFeedbackForClips(ids)]);
  const sa = variantStats(a.id, publications, feedback);
  const sb = variantStats(b.id, publications, feedback);
  const check = decisionCheck(experiment, sa, sb);
  if (!check.ready) return Response.json({ error: check.reasons[0], reasons: check.reasons }, { status: 409 });
  const confidence = posteriorAOverB(sa, sb, id);
  const winner = body.winner === "A" ? a : b;
  const updated = await pub.updateExperiment(id, { status: "decided", winner_clip_id: winner.id, confidence, decided_at: new Date().toISOString() });
  await getRepo().audit({
    action: "experiment.decided",
    entity: "experiments",
    entity_id: id,
    payload: { winner: body.winner, winner_clip_id: winner.id, confidence, views_a: sa.views, views_b: sb.views, follows_a: sa.follows, follows_b: sb.follows },
  });
  return Response.json({ ok: true, experiment: updated, confidence });
}
