import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadPublication } from "@/lib/api/lookup";
import { serializePublication } from "@/lib/api/serializers";
import { latestSnapshot } from "@/lib/publishing/performance";

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
