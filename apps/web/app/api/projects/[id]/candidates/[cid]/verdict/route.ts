import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { signalApprove } from "@/lib/temporal";
import type { Platform } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; cid: string }> };

interface VerdictBody {
  verdict?: unknown;
  reason?: unknown;
}

/* POST: menschliches Urteil. accepted -> Signal approve(candidate_id, destination) an project-<source_id>;
 * rejected -> Grund ist Pflicht (Lernsignal). Jede Aktion schreibt audit_log. */
export async function POST(request: NextRequest, { params }: Params) {
  const { id, cid } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });

  let body: VerdictBody;
  try {
    body = (await request.json()) as VerdictBody;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const verdict = body.verdict;
  if (verdict !== "accepted" && verdict !== "rejected") {
    return Response.json({ error: "verdict muss accepted oder rejected sein" }, { status: 400 });
  }
  const reason = typeof body.reason === "string" ? body.reason.trim().slice(0, 500) : "";
  if (verdict === "rejected" && !reason) {
    return Response.json({ error: "Beim Ablehnen ist ein kurzer Grund Pflicht" }, { status: 400 });
  }

  const existing = await repo.getCandidate(cid);
  if (!existing || existing.source_id !== id) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });
  if (existing.human_verdict === "edited") {
    return Response.json({ error: "Dieser Kandidat wurde durch eine neue Version ersetzt" }, { status: 409 });
  }

  const candidate = await repo.setCandidateVerdict(cid, verdict, reason || undefined);
  if (!candidate) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });

  let signaled = false;
  let destination: Platform | null = null;
  if (verdict === "accepted") {
    const brand = source.brand_profile_id ? await repo.getBrandProfile(source.brand_profile_id) : null;
    destination = source.brief.platform ?? brand?.default_platform ?? "linkedin";
    signaled = await signalApprove({ sourceId: id, candidateId: cid, destination });
  }

  await repo.audit({
    action: verdict === "accepted" ? "candidate.accepted" : "candidate.rejected",
    entity: "candidates",
    entity_id: cid,
    payload: {
      source_id: id,
      version: candidate.version,
      total: candidate.total,
      gate_passed: candidate.gate_passed,
      reason: reason || null,
      destination,
      signaled,
    },
  });

  return Response.json({ ok: true, candidate, signaled, destination });
}
