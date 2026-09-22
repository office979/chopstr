import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import type { ManualMetricsInput } from "@/lib/repo/types-publishing";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

const KEYS: (keyof ManualMetricsInput)[] = ["views", "likes", "comments", "shares", "saves", "follows", "avg_watch_time_s"];

/* POST: Metriken von Hand eintragen (manuelle Verbindung oder Nachtrag) → performance_feedback mit metric_window = manual */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.publish");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const pub = getPublishingRepo();
  const publication = await pub.getPublication(id);
  if (!publication) return Response.json({ error: "Publikation nicht gefunden" }, { status: 404 });
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const input = {} as ManualMetricsInput;
  let any = false;
  for (const key of KEYS) {
    const raw = body[key];
    if (raw == null || raw === "") {
      input[key] = null;
      continue;
    }
    const n = typeof raw === "number" ? raw : Number(String(raw).replace(/\./g, "").replace(",", "."));
    if (!Number.isFinite(n) || n < 0) return Response.json({ error: `Ungültiger Wert für ${key}.` }, { status: 400 });
    input[key] = key === "avg_watch_time_s" ? n : Math.round(n);
    any = true;
  }
  if (!any) return Response.json({ error: "Bitte mindestens eine Kennzahl eintragen." }, { status: 400 });
  const feedback = await pub.upsertManualFeedback(publication, input);
  await getRepo().audit({ action: "publication.metrics_manual", entity: "performance_feedback", entity_id: feedback.id, payload: { publication_id: id, clip_id: publication.clip_id, ...input } });
  return Response.json({ ok: true, feedback });
}
