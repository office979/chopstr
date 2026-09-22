import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { providerStatus, providers } from "@/lib/publishing/registry";
import { credentialsKeyConfigured } from "@/lib/publishing/crypto";

export const dynamic = "force-dynamic";

/* GET: Verbindungen des Workspace plus Provider-Status (konfiguriert?) */
export async function GET() {
  const auth = await requirePublishingApi("publishing.publish");
  if (auth instanceof Response) return auth;
  const connections = await getPublishingRepo().listConnections();
  return Response.json({ connections, providers: providerStatus(), credentials_key: credentialsKeyConfigured() });
}

interface Body {
  account_label?: unknown;
  brand_profile_id?: unknown;
}

/* POST: manuelle Verbindung anlegen (kein OAuth): Konto-Bezeichnung, optional Marke */
export async function POST(request: NextRequest) {
  const auth = await requirePublishingApi("publishing.manage");
  if (auth instanceof Response) return auth;
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const label = typeof body.account_label === "string" ? body.account_label.trim().slice(0, 120) : "";
  if (label.length < 2) return Response.json({ error: "Bitte eine Konto-Bezeichnung mit mindestens zwei Zeichen angeben." }, { status: 400 });
  const brandId = typeof body.brand_profile_id === "string" && body.brand_profile_id ? body.brand_profile_id : null;
  if (brandId && !(await getRepo().getBrandProfile(brandId))) return Response.json({ error: "Markenprofil nicht gefunden" }, { status: 404 });
  const connection = await getPublishingRepo().createConnection({
    platform: "manual",
    account_label: label,
    external_account_id: null,
    credentials: null,
    capabilities: providers.manual.capabilities(),
    brand_profile_id: brandId,
    expires_at: null,
  });
  await getRepo().audit({ action: "connection.created", entity: "platform_connections", entity_id: connection.id, payload: { platform: "manual", account_label: label, brand_profile_id: brandId } });
  return Response.json({ ok: true, connection }, { status: 201 });
}
