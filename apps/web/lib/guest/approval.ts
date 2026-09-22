import type { Clip, GuestApproval, GuestDecision } from "@/lib/repo/types";

/* Gast-Freigabe (PHASE4.md, Abschnitt 4): Status je Clip und Export-Sperre. Ohne Server-Abhängigkeiten. */

export const GUEST_APPROVAL_TTL_MS = 14 * 24 * 60 * 60 * 1000;

export type GuestStatus = "none" | "pending" | "expired" | GuestDecision;

export const GUEST_STATUS_LABELS: Record<GuestStatus, string> = {
  none: "Niemand gefragt",
  pending: "Wartet auf Antwort",
  expired: "Link abgelaufen",
  approved: "Freigegeben",
  changes: "Änderungen gewünscht",
  rejected: "Abgelehnt",
};

export const DECISION_LABELS: Record<GuestDecision, string> = {
  approved: "Freigegeben",
  changes: "Änderungen gewünscht",
  rejected: "Abgelehnt",
};

export function isGuestDecision(v: unknown): v is GuestDecision {
  return v === "approved" || v === "changes" || v === "rejected";
}

export function isExpired(a: GuestApproval, now = Date.now()): boolean {
  return Boolean(a.expires_at && Date.parse(a.expires_at) <= now);
}

/* Jüngste Freigabe je Clip (Liste ist neueste zuerst sortiert) */
export function latestByClip(approvals: GuestApproval[]): Map<string, GuestApproval> {
  const out = new Map<string, GuestApproval>();
  for (const a of approvals) {
    if (!out.has(a.clip_id)) out.set(a.clip_id, a);
  }
  return out;
}

export function guestStatus(clip: Pick<Clip, "guest_approval_required">, latest: GuestApproval | undefined, now = Date.now()): GuestStatus {
  if (!clip.guest_approval_required && !latest) return "none";
  if (!latest) return "pending";
  if (latest.decision) return latest.decision;
  return isExpired(latest, now) ? "expired" : "pending";
}

/* Export gesperrt, solange guest_approval_required und keine approved-Entscheidung vorliegt */
export function exportBlocked(clip: Pick<Clip, "guest_approval_required">, latest: GuestApproval | undefined): boolean {
  if (!clip.guest_approval_required) return false;
  return latest?.decision !== "approved";
}

export const EXPORT_BLOCKED_MESSAGE = "Noch gesperrt: Du wartest auf die Antwort der Person, die du gefragt hast.";
