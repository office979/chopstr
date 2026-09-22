import "server-only";
import { getSession, type Session } from "@/lib/session";
import { ACTION_DENIED, can, type Action } from "@/lib/auth/permissions";

/* Rollenprüfung für Route-Handler: liefert die Sitzung oder eine fertige JSON-Antwort (401 oder 403).
 *
 *   const auth = await requireApiRole("transcript.edit");
 *   if (auth instanceof Response) return auth;
 *
 * Server Actions und Seiten nutzen stattdessen requireRole() aus lib/session.ts (wirft ForbiddenError). */

export function unauthorized(message = "Bitte melde dich an."): Response {
  return Response.json({ error: message, code: "unauthorized" }, { status: 401 });
}

export function forbidden(action: Action): Response {
  return Response.json({ error: ACTION_DENIED[action], code: "forbidden", action }, { status: 403 });
}

export async function requireApiSession(): Promise<Session | Response> {
  const session = await getSession();
  return session ?? unauthorized();
}

export async function requireApiRole(action: Action): Promise<Session | Response> {
  const session = await getSession();
  if (!session) return unauthorized();
  if (!can(session.role, action)) return forbidden(action);
  return session;
}

/* Client-IP aus Proxy-Headern (für Rate-Limit und sessions.ip) */
export function clientIp(headers: Headers): string | null {
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0]?.trim() || null;
  return headers.get("x-real-ip") ?? null;
}
