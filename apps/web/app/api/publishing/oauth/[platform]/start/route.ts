import { randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { requirePublishingApi } from "@/lib/publishing/auth";
import { isConnectionPlatform, providers, redirectUriFor } from "@/lib/publishing/registry";
import { OAUTH_STATE_COOKIE } from "@/lib/publishing/oauth-state";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ platform: string }> };



/* GET: OAuth-Start. State im httpOnly-Cookie (10 Minuten), Weiterleitung zur Plattform. Nicht konfigurierte Provider
 * leiten mit Hinweis zurück auf die Verbindungen-Seite. */
export async function GET(request: NextRequest, { params }: Params) {
  const auth = await requirePublishingApi("publishing.manage");
  if (auth instanceof Response) return auth;
  const { platform } = await params;
  const back = new URL("/einstellungen/verbindungen", request.nextUrl.origin);
  if (!isConnectionPlatform(platform) || platform === "manual") {
    back.searchParams.set("fehler", "plattform");
    return NextResponse.redirect(back);
  }
  const provider = providers[platform];
  if (!provider.configured()) {
    back.searchParams.set("fehler", "nicht_konfiguriert");
    back.searchParams.set("plattform", platform);
    return NextResponse.redirect(back);
  }
  const state = randomBytes(24).toString("base64url");
  const redirectUri = redirectUriFor(platform, request.nextUrl.origin);
  let url: string;
  try {
    url = provider.authorizeUrl(state, redirectUri);
  } catch (error) {
    back.searchParams.set("fehler", "start");
    back.searchParams.set("detail", error instanceof Error ? error.message : "Unbekannter Fehler");
    return NextResponse.redirect(back);
  }
  const jar = await cookies();
  jar.set(OAUTH_STATE_COOKIE, `${platform}:${state}`, {
    httpOnly: true,
    sameSite: "lax",
    secure: (process.env.APP_ENV ?? process.env.NODE_ENV) === "production",
    path: "/api/publishing/oauth",
    maxAge: 600,
  });
  return NextResponse.redirect(url);
}
