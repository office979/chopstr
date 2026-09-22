import "server-only";
import { AsyncLocalStorage } from "node:async_hooks";
import { cache } from "react";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { isDemoMode } from "@/lib/env";
import { SESSION_COOKIE, SESSION_TTL_MS, SESSION_REFRESH_AFTER_MS } from "@/lib/auth/cookies";
import { can, ForbiddenError, type Action, type Role } from "@/lib/auth/permissions";
import type { Membership } from "@/lib/repo/types";

/* Sitzung der Web-App (Phase 4).
 *
 * `getSession()` liest Cookie `chopstr_session` → Zeile in `sessions` → Nutzer → Mitgliedschaft im aktiven
 * Workspace und liefert { userId, email, displayName, workspaceId, role, brandScope } oder null.
 * `requireSession()` leitet ohne Sitzung auf /anmelden?next=… um; `requireRole(action)` prüft zusätzlich
 * die Rollenmatrix (lib/auth/permissions.ts) und wirft ForbiddenError (403, deutsche Meldung).
 *
 * Demo-Modus (ohne DATABASE_URL): fester Demo-Nutzer „Demo“ als owner, kein Login.
 *
 * Kontext ohne Cookie: `withSessionContext(session, fn)` setzt die Sitzung für einen Aufruf explizit
 * (tusd-Hook mit Upload-Token, Skripte). Repository-Methoden lesen immer über `currentSession()`.
 *
 * Gleitende Verlängerung: Sitzungen laufen 30 Tage; bei jedem Zugriff nach mehr als einem Tag wird
 * `sessions.expires_at` neu gesetzt, das Cookie erneuert proxy.ts. */

export interface AuthUser {
  sessionId: string | null;
  userId: string;
  email: string;
  displayName: string;
  emailVerified: boolean;
  locale: string;
  /* sessions.workspace_id, null wenn noch keiner gewählt */
  activeWorkspaceId: string | null;
  demo: boolean;
}

export interface Session extends AuthUser {
  workspaceId: string;
  workspaceName: string;
  role: Role;
  /* workspace_members.brand_profile_id, nur für client gesetzt */
  brandScope: string | null;
}

export const DEMO_WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
export const DEMO_USER_ID = "22222222-2222-4222-8222-222222222222";

export const DEMO_SESSION: Session = {
  sessionId: null,
  userId: DEMO_USER_ID,
  email: "demo@chopstr.local",
  displayName: "Demo",
  emailVerified: true,
  locale: "de-AT",
  activeWorkspaceId: DEMO_WORKSPACE_ID,
  demo: true,
  workspaceId: DEMO_WORKSPACE_ID,
  workspaceName: "PLACEMedia",
  role: "owner",
  brandScope: null,
};

export class UnauthorizedError extends Error {
  readonly status = 401;
  constructor(message = "Bitte melde dich an.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

const sessionStore = new AsyncLocalStorage<Session>();

/* Explizite Sitzung für einen Aufruf (tusd-Hook, Skripte): alle getSession()-Aufrufe darin liefern `session`. */
export function withSessionContext<T>(session: Session, fn: () => Promise<T>): Promise<T> {
  return sessionStore.run(session, fn);
}

async function readCookieSessionId(): Promise<string | null> {
  try {
    const jar = await cookies();
    return jar.get(SESSION_COOKIE)?.value ?? null;
  } catch {
    /* außerhalb eines Requests (Build, Skript) */
    return null;
  }
}

/* Nutzer aus Cookie und sessions-Zeile, ohne Workspace-Bindung. Pro Request gecacht. */
export const getAuthUser = cache(async (): Promise<AuthUser | null> => {
  const scoped = sessionStore.getStore();
  if (scoped) return scoped;
  if (isDemoMode()) return DEMO_SESSION;

  const sessionId = await readCookieSessionId();
  if (!sessionId) return null;

  const { getRepo } = await import("@/lib/repo");
  const repo = getRepo();
  const row = await repo.getSessionRow(sessionId);
  if (!row) return null;
  const expiresAt = Date.parse(row.expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await repo.deleteSession(sessionId);
    return null;
  }
  const user = await repo.getUser(row.user_id);
  if (!user) return null;

  if (expiresAt - Date.now() < SESSION_TTL_MS - SESSION_REFRESH_AFTER_MS) {
    await repo.touchSession(sessionId, new Date(Date.now() + SESSION_TTL_MS).toISOString());
  }

  return {
    sessionId,
    userId: user.id,
    email: user.email,
    displayName: user.display_name?.trim() || user.email,
    emailVerified: user.email_verified_at != null,
    locale: user.locale,
    activeWorkspaceId: row.workspace_id,
    demo: false,
  };
});

function toSession(user: AuthUser, m: Membership): Session {
  return {
    ...user,
    activeWorkspaceId: m.workspace_id,
    workspaceId: m.workspace_id,
    workspaceName: m.workspace_name,
    role: m.role,
    brandScope: m.role === "client" ? m.brand_profile_id : null,
  };
}

/* Sitzung mit aktivem Workspace. null ohne Cookie, ohne gültige Sitzung oder ohne Mitgliedschaft. */
export const getSession = cache(async (): Promise<Session | null> => {
  const scoped = sessionStore.getStore();
  if (scoped) return scoped;
  if (isDemoMode()) return DEMO_SESSION;

  const user = await getAuthUser();
  if (!user) return null;

  const { getRepo } = await import("@/lib/repo");
  const repo = getRepo();
  if (user.activeWorkspaceId) {
    const m = await repo.getMembership(user.userId, user.activeWorkspaceId);
    if (m) return toSession(user, m);
  }
  const memberships = await repo.listMemberships(user.userId);
  const first = memberships[0];
  if (!first) return null;
  if (user.sessionId) await repo.setSessionWorkspace(user.sessionId, first.workspace_id);
  return toSession(user, first);
});

/* Aktueller Pfad für ?next= (proxy.ts setzt den Header) */
async function currentPath(): Promise<string> {
  try {
    const h = await headers();
    return h.get("x-chopstr-path") || "/";
  } catch {
    return "/";
  }
}

export async function requireAuthUser(): Promise<AuthUser> {
  const user = await getAuthUser();
  if (user) return user;
  redirect(`/anmelden?next=${encodeURIComponent(await currentPath())}`);
}

/* Sitzung oder Umleitung: ohne Login → /anmelden, mit Login aber ohne Workspace → /workspaces */
export async function requireSession(): Promise<Session> {
  const session = await getSession();
  if (session) return session;
  const user = await getAuthUser();
  if (user) redirect("/workspaces");
  redirect(`/anmelden?next=${encodeURIComponent(await currentPath())}`);
}

/* Sitzung plus Rollenprüfung; wirft ForbiddenError (status 403) mit deutscher Meldung */
export async function requireRole(action: Action): Promise<Session> {
  const session = await requireSession();
  if (!can(session.role, action)) throw new ForbiddenError(action);
  return session;
}

/* Für Repository-Methoden: Sitzung oder UnauthorizedError (401). Keine Umleitung. */
export async function currentSession(): Promise<Session> {
  const session = await getSession();
  if (!session) throw new UnauthorizedError();
  return session;
}

/* Für Seiten: statt 403 zu werfen (Produktion blendet Fehlermeldungen aus) auf /verboten?aktion=… umleiten */
export async function requirePageRole(action: Action): Promise<Session> {
  const session = await requireSession();
  if (!can(session.role, action)) redirect(`/verboten?aktion=${encodeURIComponent(action)}`);
  return session;
}
