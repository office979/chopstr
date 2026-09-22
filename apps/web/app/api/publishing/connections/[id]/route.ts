import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* PATCH: Marke zuordnen ({ brand_profile_id: string | null }) */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.manage");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  let body: { brand_profile_id?: unknown; account_label?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const patch: { brand_profile_id?: string | null; account_label?: string } = {};
  if ("brand_profile_id" in body) {
    const brandId = typeof body.brand_profile_id === "string" && body.brand_profile_id ? body.brand_profile_id : null;
    if (brandId && !(await getRepo().getBrandProfile(brandId))) return Response.json({ error: "Markenprofil nicht gefunden" }, { status: 404 });
    patch.brand_profile_id = brandId;
  }
  if (typeof body.account_label === "string" && body.account_label.trim().length >= 2) patch.account_label = body.account_label.trim().slice(0, 120);
  const connection = await getPublishingRepo().updateConnection(id, patch);
  if (!connection) return Response.json({ error: "Verbindung nicht gefunden" }, { status: 404 });
  await getRepo().audit({ action: "connection.updated", entity: "platform_connections", entity_id: id, payload: patch });
  return Response.json({ ok: true, connection });
}

/* DELETE: trennen (status revoked, Zugangsdaten werden gelöscht) */
export async function DELETE(_request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.manage");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const connection = await getPublishingRepo().updateConnection(id, { status: "revoked" });
  if (!connection) return Response.json({ error: "Verbindung nicht gefunden" }, { status: 404 });
  await getRepo().audit({ action: "connection.revoked", entity: "platform_connections", entity_id: id, payload: { platform: connection.platform, account_label: connection.account_label } });
  return Response.json({ ok: true, connection });
}
