import type { NextRequest } from "next/server";
import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { ApiError, apiJson } from "@/lib/api/errors";
import { loadPublication } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { serializePublication } from "@/lib/api/serializers";
import { latestSnapshot } from "@/lib/publishing/performance";
import { stopTracking } from "@/lib/publishing/tracking-server";

export const dynamic = "force-dynamic";

/* Scope publish ist der bestehende Vertrag dieser Route (vor der Lese-API); /publications/{id}/metrics
 * braucht nur read. Bewusst nicht geändert, damit bestehende Schlüssel nicht anders behandelt werden. */
export const GET = apiRoute<{ id: string }>("publish", async (_request, { params }) => {
  const publication = await loadPublication(params.id);
  /* Letzte Messung der Messreihe (Migration 0019) mit einer Zeile statt der ganzen Reihe; null ohne
   * Messung oder ohne Migration */
  const last = await getApiRepo().latestMetricSnapshot(publication.id);
  const metricsLatest = last ? latestSnapshot([last]) : null;
  return apiJson({ publication: serializePublication(publication, { metrics_latest: metricsLatest }) });
});

/* Messung eines verfolgten Links beenden: { "tracking": "off" }. Löscht nichts; zweimal ist harmlos. */
export const PATCH = apiRoute<{ id: string }>("publish", async (request: NextRequest, { params, auth }) => {
  await readJsonBody<{ tracking: "off" }>(request, requestSchema("PublicationPatch"), resolveRef);
  const result = await stopTracking({ publicationId: params.id, via: "api", apiKeyId: auth.key.id });
  if (!result.ok) throw new ApiError(result.status, result.code, result.message);
  return apiJson({ publication: serializePublication(result.publication), changed: result.changed });
});
