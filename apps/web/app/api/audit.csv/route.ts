import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { parseAuditQuery, toAuditFilter } from "@/lib/audit/query";

export const dynamic = "force-dynamic";

const MAX_ROWS = 10_000;

/* Excel im DACH-Raum erwartet Semikolon und BOM */
function cell(value: unknown): string {
  const text = value == null ? "" : typeof value === "string" ? value : JSON.stringify(value);
  return /[";\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/* GET /api/audit.csv?aktion=&akteur=&von=&bis= (owner, admin): bis zu 10.000 Zeilen mit denselben Filtern wie die Seite */
export async function GET(request: NextRequest) {
  const auth = await requireApiRole("audit.read");
  if (auth instanceof Response) return auth;

  const params: Record<string, string> = {};
  request.nextUrl.searchParams.forEach((v, k) => {
    params[k] = v;
  });
  const q = parseAuditQuery(params);
  const repo = getRepo();
  const page = await repo.listAudit(toAuditFilter(q, MAX_ROWS, 0));

  const header = ["id", "zeitpunkt", "aktion", "akteur", "akteur_id", "akteur_typ", "objekt", "objekt_id", "nutzlast"];
  const lines = [header.join(";")];
  for (const r of page.rows) {
    lines.push([r.id, r.at, r.action, r.actor_label ?? "", r.actor_id ?? "", r.actor_type, r.entity ?? "", r.entity_id ?? "", r.payload ?? ""].map(cell).join(";"));
  }
  await repo.audit({ action: "audit.exported", entity: "audit_log", entity_id: null, payload: { rows: page.rows.length, total: page.total, filter: q } });

  const stamp = new Date().toISOString().slice(0, 10);
  return new Response(`﻿${lines.join("\r\n")}\r\n`, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="chopstr-audit-${stamp}.csv"`,
      "Cache-Control": "no-store",
    },
  });
}
