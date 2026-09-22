import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { clientIp, requireApiRole } from "@/lib/auth/guard";
import { DPA_VERSION } from "@/lib/legal/docs";

export const dynamic = "force-dynamic";

const IP_RE = /^(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f:]+)$/i;

/* POST { company, representative, accepted: true }: AVV annehmen (PHASE4.md, Abschnitt 6) → dpa_acceptances,
 * workspaces.dpa_signed_at, Audit dpa.accepted. Rolle dpa.accept (owner, admin). */
export async function POST(request: NextRequest) {
  const auth = await requireApiRole("dpa.accept");
  if (auth instanceof Response) return auth;
  let body: { company?: unknown; representative?: unknown; accepted?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const company = typeof body.company === "string" ? body.company.trim().slice(0, 160) : "";
  const representative = typeof body.representative === "string" ? body.representative.trim().slice(0, 160) : "";
  if (company.length < 2) return Response.json({ error: "Bitte die Firma angeben.", field: "company" }, { status: 400 });
  if (representative.length < 2) return Response.json({ error: "Bitte die vertretende Person angeben.", field: "representative" }, { status: 400 });
  if (body.accepted !== true) return Response.json({ error: "Bitte die Annahme bestätigen.", field: "accepted" }, { status: 400 });

  const rawIp = clientIp(request.headers);
  const ip = rawIp && IP_RE.test(rawIp) ? rawIp : null;
  const repo = getRepo();
  const acceptance = await repo.acceptDpa({ version: DPA_VERSION, company, representative, ip });
  await repo.audit({
    action: "dpa.accepted",
    entity: "dpa_acceptances",
    entity_id: acceptance.id,
    payload: { version: DPA_VERSION, company, representative, ip },
  });
  return Response.json({ ok: true, acceptance }, { status: 201 });
}
