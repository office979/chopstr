import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { loadClipContext } from "@/lib/publishing/clip-context";
import { clipFeatures, recordDecision } from "@/lib/decision-log";
import { startPublishWorkflow } from "@/lib/temporal";
import type { PublicationInput } from "@/lib/repo/types-publishing";
import { connectionPlatformFor } from "@/lib/publishing/platforms";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* GET: Publikationen und Feedback des Clips, Gates, passende Verbindungen */
export async function GET(_request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.publish");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const ctx = await loadClipContext(id, clipId);
  if (!ctx) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  const pub = getPublishingRepo();
  const [publications, feedback, connections] = await Promise.all([pub.listPublicationsForClips([clipId]), pub.listFeedbackForClips([clipId]), pub.listConnections()]);
  return Response.json({ publications, feedback, gates: ctx.gates, connections: connections.filter((c) => c.status === "connected"), extras: ctx.extras });
}

interface Body {
  connection_id?: unknown;
  title?: unknown;
  caption?: unknown;
  scheduled_for?: unknown;
  external_url?: unknown;
  confirm?: unknown;
}

/* POST: Publikation anlegen (nach Bestätigung im Dialog). Gates prüfen, publications-Zeile (scheduled oder manual),
 * Decision Log `publish`, PublishWorkflow starten, Audit publication.created. Kein Autopublishing. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.publish");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const ctx = await loadClipContext(id, clipId);
  if (!ctx) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (body.confirm !== true) return Response.json({ error: "Bitte die Veröffentlichung bestätigen." }, { status: 400 });
  if (ctx.gates.length) return Response.json({ error: ctx.gates[0].message, gates: ctx.gates }, { status: 409 });

  const pub = getPublishingRepo();
  const connectionId = typeof body.connection_id === "string" ? body.connection_id : "";
  const connection = connectionId ? await pub.getConnection(connectionId) : null;
  if (!connection || connection.status !== "connected") return Response.json({ error: "Bitte eine aktive Verbindung wählen." }, { status: 400 });
  if (connection.platform !== "manual" && connection.platform !== connectionPlatformFor(ctx.clip.platform)) {
    return Response.json({ error: `Die Verbindung ist für ${connection.platform}, der Clip für ${ctx.clip.platform}.` }, { status: 400 });
  }
  const title = typeof body.title === "string" ? body.title.trim().slice(0, 200) : "";
  const caption = typeof body.caption === "string" ? body.caption.trim().slice(0, 3000) : "";
  let scheduledFor: string | null = null;
  if (typeof body.scheduled_for === "string" && body.scheduled_for) {
    const t = Date.parse(body.scheduled_for);
    if (!Number.isFinite(t)) return Response.json({ error: "Ungültiger Zeitpunkt." }, { status: 400 });
    if (t < Date.now() - 60_000) return Response.json({ error: "Der Zeitpunkt liegt in der Vergangenheit." }, { status: 400 });
    scheduledFor = new Date(t).toISOString();
  }
  const manual = connection.platform === "manual";
  const externalUrl = manual && typeof body.external_url === "string" && /^https:\/\//.test(body.external_url.trim()) ? body.external_url.trim().slice(0, 500) : null;

  const input: PublicationInput = {
    clip_id: clipId,
    connection_id: connection.id,
    platform: ctx.clip.platform,
    status: manual ? "manual" : "scheduled",
    scheduled_for: manual ? null : (scheduledFor ?? new Date().toISOString()),
    caption: caption || null,
    title: title || null,
    external_url: externalUrl,
    published_at: manual && externalUrl ? new Date().toISOString() : null,
  };
  const publication = await pub.createPublication(input);

  await recordDecision({
    decision_type: "publish",
    actor_type: "user",
    brand_profile_id: ctx.source.brand_profile_id,
    source_id: ctx.source.id,
    candidate_id: ctx.clip.candidate_id,
    clip_id: clipId,
    features: { ...clipFeatures(ctx.clip, ctx.hook), connection_platform: connection.platform, scheduled: Boolean(scheduledFor), manual },
    alternatives: [],
    chosen: { publication_id: publication.id, connection_id: connection.id, scheduled_for: input.scheduled_for, caption_chars: caption.length, title: title || null },
  });

  let started = false;
  if (!manual) {
    started = await startPublishWorkflow(publication.id);
    if (started) await pub.updatePublication(publication.id, { temporal_workflow_id: `publish-${publication.id}` });
  }
  await getRepo().audit({
    action: "publication.created",
    entity: "publications",
    entity_id: publication.id,
    payload: { clip_id: clipId, source_id: id, platform: ctx.clip.platform, connection_id: connection.id, connection_platform: connection.platform, status: input.status, scheduled_for: input.scheduled_for, workflow_started: started },
  });
  const fresh = (await pub.getPublication(publication.id)) ?? publication;
  return Response.json({
    ok: true,
    publication: fresh,
    started,
    message: manual
      ? "Manuelle Publikation angelegt. Poste den Export selbst und trage danach Post-URL und Metriken ein."
      : started
        ? scheduledFor
          ? "Publikation eingeplant. Der Worker veröffentlicht zum gewählten Zeitpunkt."
          : "Publikation eingeplant. Der Worker veröffentlicht jetzt."
        : "Publikation eingeplant. Der Worker holt sie ab, sobald er erreichbar ist.",
  });
}
