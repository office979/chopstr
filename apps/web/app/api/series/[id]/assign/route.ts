import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { checkVariation, clipFeaturesFor, currentSlotIndex, type ClipFeatures } from "@/lib/series/variation";
import type { ClipWithExtras } from "@/lib/repo/types-publishing";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

async function featuresFor(clip: ClipWithExtras): Promise<ClipFeatures> {
  const repo = getRepo();
  const [hook, candidate] = await Promise.all([repo.getCurrentHook(clip.id), clip.candidate_id ? repo.getCandidate(clip.candidate_id) : Promise.resolve(null)]);
  return clipFeaturesFor(clip, hook?.pattern ?? null, candidate?.structure ?? null);
}

/* POST: Clip einer Serie zuordnen ({ clip_id, confirm }). Variations-Prüfung gegen die letzten 9 Clips der Serie;
 * bei „zu ähnlich“ Antwort 200 mit warning und ohne Zuordnung, bis confirm = true kommt. { clip_id: null } löst die Zuordnung. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("series.manage");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const pub = getPublishingRepo();
  const series = await pub.getSeries(id);
  if (!series) return Response.json({ error: "Serie nicht gefunden" }, { status: 404 });
  let body: { clip_id?: unknown; confirm?: unknown; remove?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const clipId = typeof body.clip_id === "string" ? body.clip_id : "";
  if (!clipId) return Response.json({ error: "clip_id fehlt" }, { status: 400 });
  const clip = (await pub.listClipsByIds([clipId]))[0];
  if (!clip) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  if (body.remove === true) {
    const extras = await pub.updateClipExtras(clipId, { series_id: null, series_index: null });
    await getRepo().audit({ action: "series.clip_removed", entity: "clips", entity_id: clipId, payload: { series_id: id } });
    return Response.json({ ok: true, extras });
  }

  const existing = (await pub.listSeriesClips(id)).filter((c) => c.id !== clipId);
  const previous = await Promise.all(existing.slice(-9).map(featuresFor));
  const candidate = await featuresFor(clip);
  const variation = checkVariation(candidate, previous);
  if (variation.too_similar && body.confirm !== true) {
    return Response.json({ ok: false, warning: variation });
  }
  const slot = clip.series_id === id && clip.series_index != null ? clip.series_index : currentSlotIndex(series);
  const extras = await pub.updateClipExtras(clipId, { series_id: id, series_index: slot });
  await getRepo().audit({
    action: "series.clip_assigned",
    entity: "clips",
    entity_id: clipId,
    payload: { series_id: id, series_name: series.name, series_index: slot, too_similar: variation.too_similar, hits: variation.hits.length },
  });
  return Response.json({ ok: true, extras, variation, series });
}
