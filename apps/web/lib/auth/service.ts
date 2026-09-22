import "server-only";
import { cookies, headers } from "next/headers";
import { getRepo } from "@/lib/repo";
import { SESSION_COOKIE, SESSION_TTL_MS, sessionCookieOptions } from "@/lib/auth/cookies";
import { hashPassword, verifyPassword } from "@/lib/auth/password";
import { INVITE_TTL_MS, LOGIN_TOKEN_TTL_MS, randomToken } from "@/lib/auth/tokens";
import { checkRateLimit, clearAttempts, recordAttempt } from "@/lib/auth/rate-limit";
import { sendMail, type MailResult } from "@/lib/auth/mail";
import { appBaseUrl } from "@/lib/auth/url";
import { clientIp } from "@/lib/auth/guard";
import type { LoginTokenPurpose, Role, User } from "@/lib/repo/types";

/* Auth-Dienste für Server Actions: Sitzung anlegen und beenden, Anmeldung, Registrierung, Magic-Link,
 * Passwort-Reset, E-Mail-Bestätigung, Einladungs-Mails. Cookies dürfen nur in Server Actions und
 * Route-Handlern gesetzt werden, deshalb laufen alle Bestätigungsseiten über einen Button (Server Action). */

async function requestInfo(): Promise<{ ip: string | null; userAgent: string | null }> {
  try {
    const h = await headers();
    return { ip: clientIp(h), userAgent: h.get("user-agent")?.slice(0, 300) ?? null };
  } catch {
    return { ip: null, userAgent: null };
  }
}

/* Neue Sitzung: Zeile in sessions, Cookie mit der ID. Aktiver Workspace = gewünschter oder erste Mitgliedschaft. */
export async function startSession(userId: string, preferredWorkspaceId?: string | null): Promise<{ id: string; workspaceId: string | null }> {
  const repo = getRepo();
  let workspaceId = preferredWorkspaceId ?? null;
  if (!workspaceId) {
    const memberships = await repo.listMemberships(userId);
    workspaceId = memberships[0]?.workspace_id ?? null;
  }
  const id = randomToken(32);
  const { ip, userAgent } = await requestInfo();
  await repo.createSession({
    id,
    user_id: userId,
    workspace_id: workspaceId,
    expires_at: new Date(Date.now() + SESSION_TTL_MS).toISOString(),
    ip,
    user_agent: userAgent,
  });
  await repo.updateUser(userId, { last_login_at: new Date().toISOString() });
  const jar = await cookies();
  jar.set(SESSION_COOKIE, id, sessionCookieOptions());
  return { id, workspaceId };
}

export async function endSession(): Promise<void> {
  const jar = await cookies();
  const id = jar.get(SESSION_COOKIE)?.value;
  if (id) await getRepo().deleteSession(id);
  jar.set(SESSION_COOKIE, "", { ...sessionCookieOptions(0), maxAge: 0 });
}

export type LoginResult = { ok: true; user: User } | { ok: false; error: string; retryAfterS?: number };

/* E-Mail und Passwort mit Rate-Limit (5 Versuche pro 15 Minuten je E-Mail und IP) */
export async function loginWithPassword(email: string, password: string): Promise<LoginResult> {
  const { ip } = await requestInfo();
  const keys = [`email:${email}`, ip ? `ip:${ip}` : "ip:unknown"];
  const limit = checkRateLimit(keys);
  if (!limit.allowed) {
    return {
      ok: false,
      error: `Zu viele Versuche. Bitte in ${Math.ceil(limit.retryAfterS / 60)} Minuten erneut versuchen.`,
      retryAfterS: limit.retryAfterS,
    };
  }
  const repo = getRepo();
  const user = await repo.findUserByEmail(email);
  const valid = user ? await verifyPassword(user.password_hash, password) : await verifyPassword(null, password);
  if (!user || !valid) {
    recordAttempt(keys);
    return { ok: false, error: "E-Mail oder Passwort stimmen nicht." };
  }
  clearAttempts(keys);
  return { ok: true, user };
}

export interface RegisterInput {
  email: string;
  password: string;
  displayName: string;
  company: string;
}

export async function registerOwner(input: RegisterInput): Promise<{ user: User; workspaceId: string }> {
  const repo = getRepo();
  const passwordHash = await hashPassword(input.password);
  const user = await repo.createUser({ email: input.email, password_hash: passwordHash, display_name: input.displayName });
  const workspace = await repo.createWorkspaceWithOwner({
    user_id: user.id,
    email: user.email,
    display_name: input.displayName,
    company: input.company,
  });
  return { user, workspaceId: workspace.id };
}

async function issueToken(userId: string, purpose: LoginTokenPurpose): Promise<string> {
  const token = randomToken(32);
  await getRepo().createLoginToken({
    token,
    user_id: userId,
    purpose,
    expires_at: new Date(Date.now() + LOGIN_TOKEN_TTL_MS).toISOString(),
  });
  return token;
}

const SIGNATURE = "\n\nchopstr, EU-verarbeitet. Wenn du das nicht warst, kannst du diese Nachricht ignorieren.";

export async function sendMagicLink(user: User): Promise<MailResult> {
  const token = await issueToken(user.id, "magic_link");
  const link = `${await appBaseUrl()}/magic/${token}`;
  return sendMail({
    to: user.email,
    subject: "Dein Anmeldelink für chopstr",
    text: `Hallo ${user.display_name ?? ""},\n\nmit diesem Link meldest du dich an (15 Minuten gültig):\n${link}${SIGNATURE}`,
    link,
  });
}

export async function sendPasswordReset(user: User): Promise<MailResult> {
  const token = await issueToken(user.id, "password_reset");
  const link = `${await appBaseUrl()}/passwort/${token}`;
  return sendMail({
    to: user.email,
    subject: "Passwort zurücksetzen bei chopstr",
    text: `Hallo ${user.display_name ?? ""},\n\nmit diesem Link setzt du ein neues Passwort (15 Minuten gültig):\n${link}${SIGNATURE}`,
    link,
  });
}

export async function sendEmailVerification(user: User): Promise<MailResult> {
  const token = await issueToken(user.id, "verify_email");
  const link = `${await appBaseUrl()}/verifizieren/${token}`;
  return sendMail({
    to: user.email,
    subject: "E-Mail-Adresse bestätigen bei chopstr",
    text: `Hallo ${user.display_name ?? ""},\n\nbitte bestätige deine E-Mail-Adresse (15 Minuten gültig):\n${link}${SIGNATURE}`,
    link,
  });
}

export interface InviteMailInput {
  email: string;
  token: string;
  role: Role;
  workspaceName: string;
  invitedBy: string;
}

export async function sendInvite(input: InviteMailInput): Promise<MailResult & { link: string }> {
  const link = `${await appBaseUrl()}/einladung/${input.token}`;
  const days = Math.round(INVITE_TTL_MS / 86_400_000);
  const result = await sendMail({
    to: input.email,
    subject: `${input.invitedBy} lädt dich zu ${input.workspaceName} bei chopstr ein`,
    text: `Hallo,\n\n${input.invitedBy} hat dich als ${input.role} in den Workspace „${input.workspaceName}“ eingeladen.\nEinladung annehmen (${days} Tage gültig):\n${link}${SIGNATURE}`,
    link,
  });
  return { ...result, link };
}
