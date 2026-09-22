import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { isConnectionPlatform, providers, redirectUriFor } from "@/lib/publishing/registry";
import { OAUTH_STATE_COOKIE } from "@/lib/publishing/oauth-state";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ platform: string }> };

/* GET: OAuth-Callback. Prüft state gegen das Cookie, tauscht den Code, legt die Verbindung mit verschlüsselten
 * Zugangsdaten an (Capability Flags des Providers) und leitet auf die Verbindungen-Seite. */
export async function GET(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.manage");
  if (auth instanceof Response) return auth;
  const { platform } = await params;
  const back = new URL("/einstellungen/verbindungen", request.nextUrl.origin);
  const fail = (code: string, detail?: string) => {
    back.searchParams.set("fehler", code);
    if (detail) back.searchParams.set("detail", detail.slice(0, 200));
    return NextResponse.redirect(back);
  };
  if (!isConnectionPlatform(platform) || platform === "manual") return fail("plattform");
  const q = request.nextUrl.searchParams;
  const jar = await cookies();
  const expected = jar.get(OAUTH_STATE_COOKIE)?.value ?? "";
  jar.delete(OAUTH_STATE_COOKIE);
  const state = q.get("state") ?? "";
  if (!state || expected !== `${platform}:${state}`) return fail("state");
  const denied = q.get("error") ?? q.get("error_description");
  if (denied) return fail("abgelehnt", denied);
  const code = q.get("code");
  if (!code) return fail("code");

  const provider = providers[platform];
  try {
    const result = await provider.exchangeCode(code, redirectUriFor(platform, request.nextUrl.origin));
    const connection = await getPublishingRepo().createConnection({
      platform,
      account_label: result.account_label,
      external_account_id: result.external_account_id,
      credentials: result.credentials,
      capabilities: provider.capabilities(),
      brand_profile_id: null,
      expires_at: result.expires_at,
    });
    await getRepo().audit({
      action: "connection.created",
      entity: "platform_connections",
      entity_id: connection.id,
      payload: { platform, account_label: connection.account_label, external_account_id: connection.external_account_id, via: "oauth" },
    });
    back.searchParams.set("verbunden", platform);
    return NextResponse.redirect(back);
  } catch (error) {
    console.warn(`[publishing] OAuth ${platform} fehlgeschlagen:`, error instanceof Error ? error.message : error);
    return fail("austausch", error instanceof Error ? error.message : undefined);
  }
}
