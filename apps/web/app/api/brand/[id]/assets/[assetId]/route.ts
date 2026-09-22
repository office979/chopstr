import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiSession } from "@/lib/auth/guard";
import { getStore } from "@/lib/storage";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; assetId: string }> };

/* GET: Asset-Datei für Vorschauen (@font-face, Logo-Bild) aus dem Objektspeicher, nur mit Sitzung */
export async function GET(_request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id, assetId } = await params;
  const asset = await getRepo().getBrandAsset(assetId);
  if (!asset || asset.brand_profile_id !== id) return Response.json({ error: "Asset nicht gefunden" }, { status: 404 });
  const object = await getStore().get("derived", asset.storage_key);
  if (!object) return Response.json({ error: "Datei nicht im Objektspeicher" }, { status: 404 });
  return new Response(object.body as unknown as BodyInit, {
    headers: {
      "Content-Type": object.contentType ?? asset.mime_type ?? "application/octet-stream",
      "Content-Length": String(object.body.byteLength),
      "Cache-Control": "private, max-age=3600",
      "Content-Disposition": `inline; filename="${asset.name.replace(/"/g, "")}"`,
    },
  });
}
