import { can, type Action, type Role } from "@/lib/auth/permissions";

/* Rollen für Publishing, Serien und Experimente (Phase 5b). Ergänzt lib/auth/permissions.ts, ohne die Datei zu ändern:
 * `canExt(role, action)` versteht die alten Aktionen und die vier neuen. Kein Autopublishing: `publishing.publish` erlaubt
 * das Anlegen einer Publikation nach Bestätigung, ausgeführt wird sie erst über den Worker oder von Hand. */

export const PUBLISHING_ACTIONS = ["publishing.manage", "publishing.publish", "series.manage", "experiments.manage"] as const;
export type PublishingAction = (typeof PUBLISHING_ACTIONS)[number];
export type ExtAction = Action | PublishingAction;

const MATRIX: Record<PublishingAction, readonly Role[]> = {
  "publishing.manage": ["owner", "admin"],
  "publishing.publish": ["owner", "admin", "editor"],
  "series.manage": ["owner", "admin", "editor"],
  "experiments.manage": ["owner", "admin", "editor"],
};

export const PUBLISHING_ACTION_DENIED: Record<PublishingAction, string> = {
  "publishing.manage": "Verbindungen zu Plattformen dürfen nur Inhaber und Admins verwalten.",
  "publishing.publish": "Veröffentlichen dürfen nur Editoren, Admins und Inhaber.",
  "series.manage": "Serien dürfen nur Editoren, Admins und Inhaber anlegen und zuordnen.",
  "experiments.manage": "Hook-Experimente dürfen nur Editoren, Admins und Inhaber anlegen und entscheiden.",
};

export function isPublishingAction(v: unknown): v is PublishingAction {
  return typeof v === "string" && (PUBLISHING_ACTIONS as readonly string[]).includes(v);
}

export function canExt(role: Role | null | undefined, action: ExtAction): boolean {
  if (!role) return false;
  if (isPublishingAction(action)) return MATRIX[action].includes(role);
  return can(role, action);
}

export function deniedMessage(action: PublishingAction): string {
  return PUBLISHING_ACTION_DENIED[action];
}
