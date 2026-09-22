import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { parseSeriesInput } from "@/lib/series/input";

export const dynamic = "force-dynamic";

export async function GET() {
  const auth = await requirePublishingApi("series.manage");
  if (auth instanceof Response) return auth;
  return Response.json({ series: await getPublishingRepo().listSeries() });
}

/* POST: Serie anlegen (Name, Marke, Kadenz, Regeln) */
export async function POST(request: NextRequest) {
  const auth = await requirePublishingApi("series.manage");
  if (auth instanceof Response) return auth;
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const parsed = parseSeriesInput(body);
  if ("error" in parsed) return Response.json({ error: parsed.error }, { status: 400 });
  if (parsed.input.brand_profile_id && !(await getRepo().getBrandProfile(parsed.input.brand_profile_id))) return Response.json({ error: "Markenprofil nicht gefunden" }, { status: 404 });
  const series = await getPublishingRepo().createSeries(parsed.input);
  await getRepo().audit({ action: "series.created", entity: "series", entity_id: series.id, payload: { name: series.name, cadence: series.cadence, brand_profile_id: series.brand_profile_id } });
  return Response.json({ ok: true, series }, { status: 201 });
}
