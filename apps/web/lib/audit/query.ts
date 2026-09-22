import type { AuditFilter } from "@/lib/repo/types";

/* Filter der Audit-Seite und des CSV-Exports aus Query-Parametern (Aktion, Akteur, Zeitraum, Seite) */

export const AUDIT_PAGE_SIZE = 50;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface AuditQuery {
  action: string;
  actor: string;
  from: string;
  to: string;
  page: number;
}

type Params = Record<string, string | string[] | undefined>;

function one(params: Params, key: string): string {
  const v = params[key];
  return (Array.isArray(v) ? v[0] : v)?.trim() ?? "";
}

export function parseAuditQuery(params: Params): AuditQuery {
  const page = Number(one(params, "seite") || "1");
  return {
    action: one(params, "aktion").slice(0, 80),
    actor: UUID_RE.test(one(params, "akteur")) ? one(params, "akteur") : "",
    from: DATE_RE.test(one(params, "von")) ? one(params, "von") : "",
    to: DATE_RE.test(one(params, "bis")) ? one(params, "bis") : "",
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

export function toAuditFilter(q: AuditQuery, limit = AUDIT_PAGE_SIZE, offset = (q.page - 1) * AUDIT_PAGE_SIZE): AuditFilter {
  return {
    action: q.action || undefined,
    actor_id: q.actor || undefined,
    from: q.from || undefined,
    to: q.to || undefined,
    limit,
    offset,
  };
}

export function auditQueryString(q: Partial<AuditQuery>): string {
  const sp = new URLSearchParams();
  if (q.action) sp.set("aktion", q.action);
  if (q.actor) sp.set("akteur", q.actor);
  if (q.from) sp.set("von", q.from);
  if (q.to) sp.set("bis", q.to);
  if (q.page && q.page > 1) sp.set("seite", String(q.page));
  const s = sp.toString();
  return s ? `?${s}` : "";
}
