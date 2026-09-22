import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* POST { version }: Markenprofil auf einen Stand aus brand_profile_versions zurücksetzen. Vorher wird der aktuelle
 * Stand als neuer Snapshot gesichert. Rolle brand.edit. Audit brand_profile.restored. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("brand.edit");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  let body: { version?: unknown };
  try {
    body = (await request.json()) as { version?: unknown };
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const version = Number(body.version);
  if (!Number.isInteger(version) || version < 1) return Response.json({ error: "version muss eine positive Zahl sein" }, { status: 400 });
  const repo = getRepo();
  const restored = await repo.restoreBrandProfileVersion(id, version);
  if (!restored) return Response.json({ error: "Version nicht gefunden" }, { status: 404 });
  await repo.audit({
    action: "brand_profile.restored",
    entity: "brand_profiles",
    entity_id: id,
    payload: { from_history_version: version, now_version: restored.version },
  });
  return Response.json({ ok: true, profile: restored, message: `Stand ${version} wiederhergestellt (jetzt Version ${restored.version}).` });
}
