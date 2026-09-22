import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadCandidate } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { badRequest } from "@/lib/api/errors";
import { POST as verdictPost } from "@/app/api/projects/[id]/candidates/[cid]/verdict/route";

export const dynamic = "force-dynamic";

/* { verdict, reason, platforms } → gleiche Logik wie das Review (Clips anlegen, Signal, Audit) */
export const POST = apiRoute<{ id: string }>("write", async (request: NextRequest, { params }) => {
  const body = await readJsonBody<{ verdict: string; reason?: string; platforms?: string[] }>(request, requestSchema("Verdict"), resolveRef);
  if (body.verdict === "rejected" && !body.reason?.trim()) throw badRequest("Beim Ablehnen ist ein Grund Pflicht.", "reason_required");
  const { candidate, source } = await loadCandidate(params.id);
  return delegate(verdictPost, request, { id: source.id, cid: candidate.id }, { method: "POST", body });
});
