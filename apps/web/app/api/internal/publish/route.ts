import type { NextRequest } from "next/server";
import { checkInternalSecret } from "@/lib/api/internal-auth";
import { apiErrorResponse, apiJson } from "@/lib/api/errors";
import { publishViaRegistry } from "@/lib/api/internal-publish";

export const dynamic = "force-dynamic";

/* Worker → Web: { publication_id } → { status: "published" | "failed", external_id, external_url, error }.
 * Das Posten selbst macht lib/publishing/registry (Welle 5b); fehlt es, kommt status failed mit Hinweis. */
export async function POST(request: NextRequest) {
  const denied = checkInternalSecret(request);
  if (denied) return denied;
  let body: { publication_id?: unknown } = {};
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return apiErrorResponse(400, "invalid_json", "Ungültiger JSON-Body.");
  }
  if (typeof body.publication_id !== "string" || !body.publication_id) return apiErrorResponse(400, "validation_failed", "publication_id fehlt.");
  const result = await publishViaRegistry(body.publication_id);
  return apiJson(result);
}
