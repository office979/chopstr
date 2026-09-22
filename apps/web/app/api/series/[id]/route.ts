import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { parseSeriesInput } from "@/lib/series/input";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* PATCH: Serie ändern ({ active } oder Felder wie beim Anlegen) */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("series.manage");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const pub = getPublishingRepo();
  if (!(await pub.getSeries(id))) return Response.json({ error: "Serie nicht gefunden" }, { status: 404 });
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (typeof body.active === "boolean" && Object.keys(body).length === 1) {
    const series = await pub.updateSeries(id, { active: body.active });
    await getRepo().audit({ action: "series.updated", entity: "series", entity_id: id, payload: { active: body.active } });
    return Response.json({ ok: true, series });
  }
  const parsed = parseSeriesInput(body);
  if ("error" in parsed) return Response.json({ error: parsed.error }, { status: 400 });
  const series = await pub.updateSeries(id, { ...parsed.input, ...(typeof body.active === "boolean" ? { active: body.active } : {}) });
  await getRepo().audit({ action: "series.updated", entity: "series", entity_id: id, payload: { name: parsed.input.name, cadence: parsed.input.cadence } });
  return Response.json({ ok: true, series });
}
