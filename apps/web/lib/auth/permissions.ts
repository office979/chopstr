/* Rollen und Rechte (Matrix aus packages/schema/PHASE4.md, Abschnitt 2).
 *
 * Jede Route und jede Server Action prüft `can(role, action)` und antwortet bei Verstoß mit 403 und einer
 * deutschen Meldung (siehe lib/session.ts `requireRole` und lib/auth/guard.ts `requireApiRole`).
 * Die Datei hat keine Abhängigkeiten und kann auch im Client importiert werden (z. B. für die Navigation).
 *
 * Block B (Gast-Freigabe, Abrechnung, AVV, Löschung, CI-Manager) nutzt die bereits angelegten Aktionen
 * billing.manage, dpa.accept, source.delete, workspace.delete, brand.assets, guest_approval.request,
 * audit.read und export.read. Neue Aktionen bitte hier ergänzen, nicht in den Routen hart kodieren. */

export const ROLES = ["owner", "admin", "editor", "reviewer", "client"] as const;
export type Role = (typeof ROLES)[number];

export const ACTIONS = [
  /* Quellen */
  "source.upload",
  "source.delete",
  "source.read",
  /* Transkript und Kandidaten */
  "transcript.edit",
  "candidate.edit",
  "candidate.verdict",
  /* Clips und Hook-Studio */
  "hook.edit",
  "clip.render",
  "export.read",
  "guest_approval.request",
  /* Markenprofil und CI */
  "brand.edit",
  "brand.assets",
  /* Workspace-Verwaltung */
  "members.manage",
  "workspace.update",
  "workspace.delete",
  "billing.manage",
  "dpa.accept",
  "audit.read",
  /* API-Schlüssel, Webhooks, Entwicklerseite (Phase 5a) */
  "api.manage",
] as const;
export type Action = (typeof ACTIONS)[number];

/* Rollen, die eine Aktion ausführen dürfen. `client` ist zusätzlich über app.brand_scope auf seine Marke begrenzt. */
const MATRIX: Record<Action, readonly Role[]> = {
  "source.upload": ["owner", "admin", "editor"],
  "source.delete": ["owner", "admin", "editor"],
  "source.read": ["owner", "admin", "editor", "reviewer", "client"],
  "transcript.edit": ["owner", "admin", "editor"],
  "candidate.edit": ["owner", "admin", "editor"],
  "candidate.verdict": ["owner", "admin", "editor", "reviewer", "client"],
  "hook.edit": ["owner", "admin", "editor"],
  "clip.render": ["owner", "admin", "editor"],
  "export.read": ["owner", "admin"],
  "guest_approval.request": ["owner", "admin", "editor"],
  "brand.edit": ["owner", "admin", "editor"],
  "brand.assets": ["owner", "admin", "editor"],
  "members.manage": ["owner", "admin"],
  "workspace.update": ["owner", "admin"],
  "workspace.delete": ["owner"],
  "billing.manage": ["owner", "admin"],
  "dpa.accept": ["owner", "admin"],
  "audit.read": ["owner", "admin"],
  "api.manage": ["owner", "admin"],
};

export function can(role: Role | null | undefined, action: Action): boolean {
  if (!role) return false;
  return MATRIX[action].includes(role);
}

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

/* Rollen, die ein Mitglied vergeben darf: owner darf alles außer owner (Übertragung kommt später), admin darf keine admins anlegen */
export function assignableRoles(byRole: Role): Role[] {
  if (byRole === "owner") return ["admin", "editor", "reviewer", "client"];
  if (byRole === "admin") return ["editor", "reviewer", "client"];
  return [];
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Inhaber",
  admin: "Admin",
  editor: "Editor",
  reviewer: "Reviewer",
  client: "Kunde",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  owner: "Alles, inklusive Workspace löschen.",
  admin: "Mitglieder, Abrechnung, AVV, Audit-Log, alle Inhalte.",
  editor: "Upload, Transkript, Kandidaten, Hook-Studio, Markenprofil.",
  reviewer: "Kandidaten annehmen oder ablehnen, sonst nur lesen.",
  client: "Nur die eigene Marke: Kandidaten freigeben, Clips ansehen.",
};

/* Deutsche 403-Meldung je Aktion */
export const ACTION_DENIED: Record<Action, string> = {
  "source.upload": "Uploads sind für deine Rolle nicht freigegeben.",
  "source.delete": "Nur Editoren, Admins und Inhaber dürfen Quellen löschen.",
  "source.read": "Du hast keinen Zugriff auf dieses Projekt.",
  "transcript.edit": "Transkripte dürfen nur Editoren, Admins und Inhaber korrigieren.",
  "candidate.edit": "Kandidaten dürfen nur Editoren, Admins und Inhaber bearbeiten.",
  "candidate.verdict": "Du darfst diesen Kandidaten nicht beurteilen.",
  "hook.edit": "Das Hook-Studio ist für deine Rolle nur lesbar.",
  "clip.render": "Renders dürfen nur Editoren, Admins und Inhaber anstoßen.",
  "export.read": "Der Datenexport ist Inhabern und Admins vorbehalten.",
  "guest_approval.request": "Gast-Freigaben dürfen nur Editoren, Admins und Inhaber anfordern.",
  "brand.edit": "Das Markenprofil dürfen nur Editoren, Admins und Inhaber ändern.",
  "brand.assets": "CI-Assets dürfen nur Editoren, Admins und Inhaber hochladen.",
  "members.manage": "Mitglieder verwalten dürfen nur Inhaber und Admins.",
  "workspace.update": "Workspace-Einstellungen dürfen nur Inhaber und Admins ändern.",
  "workspace.delete": "Nur der Inhaber kann den Workspace löschen.",
  "billing.manage": "Abrechnung und Plan sind Inhabern und Admins vorbehalten.",
  "dpa.accept": "Den AV-Vertrag dürfen nur Inhaber und Admins annehmen.",
  "audit.read": "Das Audit-Log ist Inhabern und Admins vorbehalten.",
  "api.manage": "API-Schlüssel und Webhooks dürfen nur Inhaber und Admins verwalten.",
};

export class ForbiddenError extends Error {
  readonly status = 403;
  readonly action: Action;
  constructor(action: Action, message?: string) {
    super(message ?? ACTION_DENIED[action]);
    this.name = "ForbiddenError";
    this.action = action;
  }
}

export function isForbiddenError(error: unknown): error is ForbiddenError {
  return error instanceof ForbiddenError || (typeof error === "object" && error !== null && (error as { status?: number }).status === 403);
}
