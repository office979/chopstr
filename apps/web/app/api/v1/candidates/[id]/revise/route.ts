import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadCandidate } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { POST as revisePost } from "@/app/api/projects/[id]/candidates/[cid]/revise/route";

export const dynamic = "force-dynamic";

export const POST = apiRoute<{ id: string }>("write", async (request: NextRequest, { params }) => {
  const body = await readJsonBody(request, requestSchema("Revise"), resolveRef);
  const { candidate, source } = await loadCandidate(params.id);
  return delegate(revisePost, request, { id: source.id, cid: candidate.id }, { method: "POST", body });
});
