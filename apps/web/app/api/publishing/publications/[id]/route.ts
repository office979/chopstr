import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { signalPublish } from "@/lib/temporal";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

interface Body {
  action?: unknown;
  scheduled_for?: unknown;
  external_url?: unknown;
}

/* PATCH: { action: "cancel" } (Signal cancel, Status failed mit Hinweis), { action: "reschedule", scheduled_for }
 * (Signal reschedule), { action: "manual_url", external_url } (manuelle Publikation: Post-URL eintragen) */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.publish");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const pub = getPublishingRepo();
  const publication = await pub.getPublication(id);
  if (!publication) return Response.json({ error: "Publikation nicht gefunden" }, { status: 404 });
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const repo = getRepo();

  if (body.action === "cancel") {
    if (publication.status !== "scheduled") return Response.json({ error: "Nur eingeplante Publikationen lassen sich abbrechen." }, { status: 409 });
    const signaled = await signalPublish(id, "cancel");
    const updated = await pub.updatePublication(id, { status: "failed", error: "Vom Nutzer abgebrochen." });
    await repo.audit({ action: "publication.cancelled", entity: "publications", entity_id: id, payload: { signaled, clip_id: publication.clip_id } });
    return Response.json({ ok: true, publication: updated, signaled });
  }

  if (body.action === "reschedule") {
    if (publication.status !== "scheduled") return Response.json({ error: "Nur eingeplante Publikationen lassen sich umplanen." }, { status: 409 });
    const t = typeof body.scheduled_for === "string" ? Date.parse(body.scheduled_for) : NaN;
    if (!Number.isFinite(t)) return Response.json({ error: "Ungültiger Zeitpunkt." }, { status: 400 });
    if (t < Date.now() - 60_000) return Response.json({ error: "Der Zeitpunkt liegt in der Vergangenheit." }, { status: 400 });
    const iso = new Date(t).toISOString();
    const signaled = await signalPublish(id, "reschedule", iso);
    const updated = await pub.updatePublication(id, { scheduled_for: iso });
    await repo.audit({ action: "publication.rescheduled", entity: "publications", entity_id: id, payload: { scheduled_for: iso, signaled, clip_id: publication.clip_id } });
    return Response.json({ ok: true, publication: updated, signaled });
  }

  if (body.action === "manual_url") {
    if (publication.status !== "manual") return Response.json({ error: "Nur manuelle Publikationen bekommen eine Post-URL von Hand." }, { status: 409 });
    const url = typeof body.external_url === "string" ? body.external_url.trim().slice(0, 500) : "";
    if (!/^https:\/\/\S+$/.test(url)) return Response.json({ error: "Bitte eine https-URL angeben." }, { status: 400 });
    const updated = await pub.updatePublication(id, { external_url: url, published_at: publication.published_at ?? new Date().toISOString() });
    await repo.audit({ action: "publication.manual_url", entity: "publications", entity_id: id, payload: { external_url: url, clip_id: publication.clip_id } });
    return Response.json({ ok: true, publication: updated });
  }

  return Response.json({ error: "Unbekannte Aktion" }, { status: 400 });
}
