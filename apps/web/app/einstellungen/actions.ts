"use server";

import { revalidatePath } from "next/cache";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { requireRole, requireSession } from "@/lib/session";
import { assignableRoles, isForbiddenError, isRole, type Role } from "@/lib/auth/permissions";
import { sendInvite } from "@/lib/auth/service";
import { hashPassword, passwordProblem, verifyPassword } from "@/lib/auth/password";
import { INVITE_TTL_MS, isEmail, isTokenShape, normalizeEmail } from "@/lib/auth/tokens";
import { CONSOLE_LINK_HINT, field, type FormState } from "@/lib/auth/form";

const DATA_REGIONS = ["eu-central-1", "eu-west-1", "eu-north-1", "hetzner-fsn1", "hetzner-nbg1", "hetzner-hel1"];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function denied(error: unknown): FormState | null {
  if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
  return null;
}

/* Allgemein: Name, Datenregion, Aufbewahrung (owner, admin) */
export async function updateWorkspaceAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requireRole("workspace.update");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const name = field(formData, "name", 80);
  const dataRegion = field(formData, "data_region", 40);
  const retention = Number(field(formData, "retention_days", 6));
  const renderRetention = Number(field(formData, "render_retention_days", 6));
  const errors: Record<string, string> = {};
  if (name.length < 2) errors.name = "Bitte einen Namen mit mindestens zwei Zeichen angeben.";
  if (!DATA_REGIONS.includes(dataRegion)) errors.data_region = "Bitte eine EU-Region wählen.";
  if (!Number.isInteger(retention) || retention < 1 || retention > 3650) errors.retention_days = "1 bis 3650 Tage.";
  if (!Number.isInteger(renderRetention) || renderRetention < 1 || renderRetention > 3650) errors.render_retention_days = "1 bis 3650 Tage.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const repo = getRepo();
  const ws = await repo.updateWorkspace({ name, data_region: dataRegion, retention_days: retention, render_retention_days: renderRetention });
  await repo.audit({
    action: "workspace.updated",
    entity: "workspaces",
    entity_id: ws.id,
    payload: { name, data_region: dataRegion, retention_days: retention, render_retention_days: renderRetention },
  });
  revalidatePath("/einstellungen");
  return { ok: true, message: isDemoMode() ? "Gespeichert (Demo, nur im Speicher)." : "Workspace gespeichert.", errors: {} };
}

/* Mitglieder: Einladung per E-Mail mit Rolle und optional Marke (client: Pflicht) */
export async function inviteMemberAction(_prev: FormState, formData: FormData): Promise<FormState> {
  let session;
  try {
    session = await requireRole("members.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const email = normalizeEmail(formData.get("email"));
  const roleRaw = field(formData, "role", 20);
  const brandRaw = field(formData, "brand_profile_id", 40);
  const errors: Record<string, string> = {};
  if (!isEmail(email)) errors.email = "Bitte eine gültige E-Mail-Adresse angeben.";
  if (!isRole(roleRaw) || roleRaw === "owner" || !assignableRoles(session.role).includes(roleRaw)) {
    errors.role = "Diese Rolle darfst du nicht vergeben.";
  }
  const role = roleRaw as Exclude<Role, "owner">;
  let brandProfileId: string | null = null;
  if (brandRaw) {
    if (!UUID_RE.test(brandRaw)) errors.brand_profile_id = "Markenprofil ungültig.";
    else brandProfileId = brandRaw;
  }
  if (role === "client" && !brandProfileId) errors.brand_profile_id = "Kunden brauchen eine Marke.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const repo = getRepo();
  if (brandProfileId && !(await repo.getBrandProfile(brandProfileId))) {
    return { ok: false, message: "Markenprofil nicht gefunden.", errors: { brand_profile_id: "Bitte ein Markenprofil dieses Workspaces wählen." } };
  }
  const members = await repo.listMembers();
  if (members.some((m) => m.email.toLowerCase() === email)) {
    return { ok: false, message: "Diese Person ist bereits Mitglied.", errors: { email: "Bereits im Workspace." } };
  }
  const invite = await repo.createInvite({
    email,
    role,
    brand_profile_id: role === "client" ? brandProfileId : brandProfileId,
    expires_at: new Date(Date.now() + INVITE_TTL_MS).toISOString(),
  });
  const mail = await sendInvite({ email, token: invite.token, role, workspaceName: session.workspaceName, invitedBy: session.displayName });
  await repo.audit({
    action: "member.invited",
    entity: "workspace_invites",
    entity_id: null,
    payload: { email, role, brand_profile_id: brandProfileId, expires_at: invite.expires_at, delivered: mail.delivered },
  });
  revalidatePath("/einstellungen/mitglieder");
  return {
    ok: true,
    message: `Einladung an ${email} als ${role} erstellt (7 Tage gültig).`,
    errors: {},
    hint: mail.logged ? `${CONSOLE_LINK_HINT} Link: ${mail.link}` : undefined,
  };
}

export async function updateMemberAction(_prev: FormState, formData: FormData): Promise<FormState> {
  let session;
  try {
    session = await requireRole("members.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const userId = field(formData, "user_id", 40);
  const roleRaw = field(formData, "role", 20);
  const brandRaw = field(formData, "brand_profile_id", 40);
  if (!UUID_RE.test(userId)) return { ok: false, message: "Mitglied ungültig.", errors: {} };
  if (!isRole(roleRaw) || roleRaw === "owner" || !assignableRoles(session.role).includes(roleRaw)) {
    return { ok: false, message: "Diese Rolle darfst du nicht vergeben.", errors: {} };
  }
  if (userId === session.userId) return { ok: false, message: "Die eigene Rolle kannst du nicht ändern.", errors: {} };
  const repo = getRepo();
  const target = (await repo.listMembers()).find((m) => m.user_id === userId);
  if (!target) return { ok: false, message: "Mitglied nicht gefunden.", errors: {} };
  if (target.role === "owner") return { ok: false, message: "Der Inhaber behält seine Rolle.", errors: {} };
  if (session.role === "admin" && target.role === "admin") return { ok: false, message: "Admins können andere Admins nicht ändern.", errors: {} };
  const brandProfileId = brandRaw && UUID_RE.test(brandRaw) ? brandRaw : null;
  if (roleRaw === "client" && !brandProfileId) return { ok: false, message: "Kunden brauchen eine Marke.", errors: {} };
  await repo.updateMember(userId, { role: roleRaw, brand_profile_id: roleRaw === "client" ? brandProfileId : null });
  await repo.audit({
    action: "member.role_changed",
    entity: "workspace_members",
    entity_id: userId,
    payload: { from: target.role, to: roleRaw, brand_profile_id: roleRaw === "client" ? brandProfileId : null },
  });
  revalidatePath("/einstellungen/mitglieder");
  return { ok: true, message: `Rolle von ${target.display_name ?? target.email} auf ${roleRaw} gesetzt.`, errors: {} };
}

export async function removeMemberAction(_prev: FormState, formData: FormData): Promise<FormState> {
  let session;
  try {
    session = await requireRole("members.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const userId = field(formData, "user_id", 40);
  if (!UUID_RE.test(userId)) return { ok: false, message: "Mitglied ungültig.", errors: {} };
  if (userId === session.userId) return { ok: false, message: "Du kannst dich nicht selbst entfernen.", errors: {} };
  const repo = getRepo();
  const target = (await repo.listMembers()).find((m) => m.user_id === userId);
  if (!target) return { ok: false, message: "Mitglied nicht gefunden.", errors: {} };
  if (target.role === "owner") return { ok: false, message: "Der Inhaber kann nicht entfernt werden.", errors: {} };
  if (session.role === "admin" && target.role === "admin") return { ok: false, message: "Admins können andere Admins nicht entfernen.", errors: {} };
  await repo.removeMember(userId);
  await repo.audit({ action: "member.removed", entity: "workspace_members", entity_id: userId, payload: { email: target.email, role: target.role } });
  revalidatePath("/einstellungen/mitglieder");
  return { ok: true, message: `${target.display_name ?? target.email} wurde entfernt.`, errors: {} };
}

export async function revokeInviteAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requireRole("members.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const token = field(formData, "token", 200);
  if (!isTokenShape(token)) return { ok: false, message: "Einladung ungültig.", errors: {} };
  const repo = getRepo();
  const ok = await repo.revokeInvite(token);
  if (ok) await repo.audit({ action: "member.invite_revoked", entity: "workspace_invites", entity_id: null, payload: { token_prefix: token.slice(0, 6) } });
  revalidatePath("/einstellungen/mitglieder");
  return ok ? { ok: true, message: "Einladung zurückgezogen.", errors: {} } : { ok: false, message: "Einladung nicht gefunden.", errors: {} };
}

/* Sicherheit: Passwort ändern (aktuelles Passwort nötig, wenn eines gesetzt ist), andere Sitzungen beenden */
export async function changePasswordAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const session = await requireSession();
  if (isDemoMode()) return { ok: false, message: "Demo-Modus: Passwörter werden nicht gespeichert.", errors: {} };
  const current = typeof formData.get("current_password") === "string" ? (formData.get("current_password") as string) : "";
  const next = typeof formData.get("password") === "string" ? (formData.get("password") as string) : "";
  const confirm = typeof formData.get("password_confirm") === "string" ? (formData.get("password_confirm") as string) : "";
  const errors: Record<string, string> = {};
  const pw = passwordProblem(next);
  if (pw) errors.password = pw;
  else if (next !== confirm) errors.password_confirm = "Die Passwörter stimmen nicht überein.";
  const repo = getRepo();
  const user = await repo.getUser(session.userId);
  if (!user) return { ok: false, message: "Konto nicht gefunden.", errors: {} };
  if (user.password_hash && !(await verifyPassword(user.password_hash, current))) {
    errors.current_password = "Das aktuelle Passwort stimmt nicht.";
  }
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };
  await repo.updateUser(user.id, { password_hash: await hashPassword(next) });
  const closed = await repo.deleteUserSessions(user.id, session.sessionId ?? undefined);
  await repo.audit({ action: "auth.password_changed", entity: "users", entity_id: user.id, payload: { via: "settings", sessions_closed: closed } });
  revalidatePath("/einstellungen/sicherheit");
  return { ok: true, message: closed > 0 ? `Passwort geändert, ${closed} andere Sitzung(en) beendet.` : "Passwort geändert.", errors: {} };
}

export async function revokeSessionAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const session = await requireSession();
  if (isDemoMode()) return { ok: false, message: "Demo-Modus: keine Sitzungen.", errors: {} };
  const id = field(formData, "session_id", 200);
  const repo = getRepo();
  const mine = await repo.listUserSessions(session.userId);
  if (!mine.some((s) => s.id === id)) return { ok: false, message: "Sitzung nicht gefunden.", errors: {} };
  if (id === session.sessionId) return { ok: false, message: "Die aktuelle Sitzung beendest du über „Abmelden“.", errors: {} };
  await repo.deleteSession(id);
  await repo.audit({ action: "auth.session_revoked", entity: "users", entity_id: session.userId, payload: { session_prefix: id.slice(0, 6) } });
  revalidatePath("/einstellungen/sicherheit");
  return { ok: true, message: "Sitzung beendet.", errors: {} };
}

export async function revokeOtherSessionsAction(): Promise<FormState> {
  const session = await requireSession();
  if (isDemoMode()) return { ok: false, message: "Demo-Modus: keine Sitzungen.", errors: {} };
  const repo = getRepo();
  const closed = await repo.deleteUserSessions(session.userId, session.sessionId ?? undefined);
  await repo.audit({ action: "auth.sessions_revoked", entity: "users", entity_id: session.userId, payload: { sessions_closed: closed } });
  revalidatePath("/einstellungen/sicherheit");
  return { ok: true, message: closed > 0 ? `${closed} andere Sitzung(en) beendet.` : "Keine anderen Sitzungen aktiv.", errors: {} };
}
