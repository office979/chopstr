import type { NextRequest } from "next/server";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { loadClipContext } from "@/lib/publishing/clip-context";
import { gateReasons } from "@/lib/publishing/gates";
import { registerLinkForClip } from "@/lib/publishing/link-check-server";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* Sitzungsroute für die Oberfläche (Gepostet.tsx): dasselbe wie POST /api/v1/clips/{id}/links, nur mit
 * Anmeldung statt API-Schlüssel. Fehler als { error } wie die übrigen Routen unter /api/projects. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.publish");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const ctx = await loadClipContext(id, clipId);
  if (!ctx) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  let body: { url?: unknown; track_days?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (typeof body.url !== "string" || !body.url.trim()) return Response.json({ error: "Bitte einen Link einfügen." }, { status: 400 });
  const sperre = gateReasons(ctx.eintragen);
  if (sperre.length) return Response.json({ error: sperre[0].message, gates: sperre }, { status: 409 });
  const trackDays = typeof body.track_days === "number" && Number.isFinite(body.track_days) ? body.track_days : undefined;
  const result = await registerLinkForClip({ clip: ctx.clip, url: body.url.slice(0, 2000), trackDays, via: "ui" });
  if (!result.ok) return Response.json({ error: result.message, code: result.code, check: result.check }, { status: result.status });
  return Response.json({ ok: true, publication: result.publication, check: result.check, summary: result.summary });
}
