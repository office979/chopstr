import "server-only";
import { redirect } from "next/navigation";
import { getSession, requireSession, type Session } from "@/lib/session";
import { unauthorized } from "@/lib/auth/guard";
import { canExt, deniedMessage, type PublishingAction } from "@/lib/auth/permissions-publishing";

/* Rollenprüfung für die Publishing-Aktionen (Ergänzung zu lib/session.ts und lib/auth/guard.ts, die nur `Action` kennen). */

export async function requirePublishingPage(action: PublishingAction): Promise<Session> {
  const session = await requireSession();
  if (!canExt(session.role, action)) redirect(`/verboten?aktion=${encodeURIComponent(action)}`);
  return session;
}

export function forbiddenPublishing(action: PublishingAction): Response {
  return Response.json({ error: deniedMessage(action), code: "forbidden", action }, { status: 403 });
}

export async function requirePublishingApi(action: PublishingAction): Promise<Session | Response> {
  const session = await getSession();
  if (!session) return unauthorized();
  if (!canExt(session.role, action)) return forbiddenPublishing(action);
  return session;
}

export class PublishingForbiddenError extends Error {
  readonly status = 403;
  constructor(action: PublishingAction) {
    super(deniedMessage(action));
    this.name = "PublishingForbiddenError";
  }
}

/* Für Server Actions */
export async function requirePublishingRole(action: PublishingAction): Promise<Session> {
  const session = await requireSession();
  if (!canExt(session.role, action)) throw new PublishingForbiddenError(action);
  return session;
}
