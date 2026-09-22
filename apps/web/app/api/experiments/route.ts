import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { loadClipContext } from "@/lib/publishing/clip-context";
import { clipFeatures, recordDecision } from "@/lib/decision-log";
import { patternLabel } from "@/lib/clips/labels";

export const dynamic = "force-dynamic";

interface Body {
  source_id?: unknown;
  clip_id?: unknown;
  variant_index?: unknown;
  hypothesis?: unknown;
}

/* POST: „Variante B anlegen“ aus dem Hook-Studio. Neuer Clip mit gleicher Komposition und Plattform (variant B), Original
 * wird A, experiments-Zeile mit Hypothese (draft). Hook-Version für B aus einer anderen Variante (variant_index). */
export async function POST(request: NextRequest) {
  const auth = await requirePublishingApi("experiments.manage");
  if (auth instanceof Response) return auth;
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const sourceId = typeof body.source_id === "string" ? body.source_id : "";
  const clipId = typeof body.clip_id === "string" ? body.clip_id : "";
  const ctx = sourceId && clipId ? await loadClipContext(sourceId, clipId) : null;
  if (!ctx) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  if (ctx.extras.experiment_id) return Response.json({ error: "Dieser Clip gehört schon zu einem Experiment." }, { status: 409 });
  const hook = ctx.hook;
  if (!hook) return Response.json({ error: "Der Clip hat noch keine Hook-Version (erst rendern)." }, { status: 409 });
  const variants = (await getRepo().listHookVersions(clipId)).reverse().find((v) => v.variants.length > 0)?.variants ?? [];
  const idx = typeof body.variant_index === "number" ? body.variant_index : Number(body.variant_index);
  const variant = Number.isInteger(idx) ? variants[idx] : undefined;
  if (!variant) return Response.json({ error: "Bitte eine Hook-Variante für B wählen." }, { status: 400 });
  if (variant.spoken === hook.spoken_hook && variant.onscreen === hook.onscreen_hook) {
    return Response.json({ error: "Variante B braucht einen anderen Hook als Variante A." }, { status: 400 });
  }
  const hypothesis = typeof body.hypothesis === "string" && body.hypothesis.trim()
    ? body.hypothesis.trim().slice(0, 500)
    : `${patternLabel(variant.pattern)} erzielt eine höhere Folgequote als ${patternLabel(hook.pattern)}.`;

  const pub = getPublishingRepo();
  const experiment = await pub.createExperiment({ candidate_id: ctx.clip.candidate_id, hypothesis });
  const clone = await pub.cloneClipForVariant(clipId, experiment.id, { spoken: variant.spoken, onscreen: variant.onscreen, pattern: variant.pattern });
  await recordDecision({
    decision_type: "hook_selected",
    actor_type: "user",
    brand_profile_id: ctx.source.brand_profile_id,
    source_id: sourceId,
    candidate_id: ctx.clip.candidate_id,
    clip_id: clone.id,
    features: { ...clipFeatures(ctx.clip, hook), experiment_id: experiment.id, variant: "B", patterns: variants.map((v) => v.pattern) },
    alternatives: variants.filter((v) => v !== variant).map((v) => ({ pattern: v.pattern, spoken: v.spoken })),
    chosen: { pattern: variant.pattern, spoken: variant.spoken, onscreen: variant.onscreen },
  });
  await getRepo().audit({
    action: "experiment.created",
    entity: "experiments",
    entity_id: experiment.id,
    payload: { source_id: sourceId, clip_a: clipId, clip_b: clone.id, platform: ctx.clip.platform, hypothesis, pattern_a: hook.pattern, pattern_b: variant.pattern },
  });
  return Response.json({ ok: true, experiment, clip_b: clone, href: `/experimente/${experiment.id}` }, { status: 201 });
}
