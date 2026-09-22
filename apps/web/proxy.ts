import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth/cookies";

/* Next 16: proxy.ts (früher middleware.ts). Geschützte Bereiche leiten ohne Sitzungs-Cookie auf /anmelden um,
 * API-Routen antworten 401. Die eigentliche Sitzungsprüfung (Zeile in sessions, Mitgliedschaft, Rolle) macht
 * lib/session.ts serverseitig; hier wird nur das Cookie geprüft und gleitend verlängert (30 Tage ab letztem Zugriff).
 * Im Demo-Modus (ohne DATABASE_URL) gibt es keine Umleitung. */

const PUBLIC_PATHS: RegExp[] = [
  /^\/anmelden(\/|$)/,
  /^\/registrieren(\/|$)/,
  /^\/passwort(\/|$)/,
  /^\/magic\//,
  /^\/einladung\//,
  /^\/verifizieren\//,
  /^\/freigabe\//,
  /^\/api\/freigabe\//,
  /^\/rechtliches(\/|$)/,
  /^\/api\/tus\/hooks(\/|$)/,
  /^\/api\/auth\//,
  /^\/api\/billing\/webhook(\/|$)/,
];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-chopstr-path", `${pathname}${search}`);

  const demo = !process.env.DATABASE_URL;
  const isPublic = PUBLIC_PATHS.some((re) => re.test(pathname));
  const sessionId = request.cookies.get(SESSION_COOKIE)?.value;

  if (demo || isPublic || sessionId) {
    const response = NextResponse.next({ request: { headers: requestHeaders } });
    if (sessionId && !demo) {
      response.cookies.set(SESSION_COOKIE, sessionId, sessionCookieOptions());
    }
    return response;
  }

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Bitte melde dich an.", code: "unauthorized" }, { status: 401 });
  }
  const url = request.nextUrl.clone();
  url.pathname = "/anmelden";
  url.search = `?next=${encodeURIComponent(`${pathname}${search}`)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|icon\\.svg|brand/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff2?|txt)$).*)"],
};
