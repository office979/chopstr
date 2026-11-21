import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, notFound } from "@/lib/api/errors";
import { serializePublication } from "@/lib/api/serializers";
import { latestSnapshot } from "@/lib/publishing/performance";

export const dynamic = "force-dynamic";

export const GET = apiRoute<{ id: string }>("publish", async (_request, { params }) => {
  const repo = getApiRepo();
  const publication = await repo.getPublication(params.id);
  if (!publication) throw notFound("Publikation nicht gefunden.");
  /* Letzte Messung der Messreihe (Migration 0019); null ohne Messung oder ohne Migration */
  const metricsLatest = latestSnapshot(await repo.listMetricSnapshots([publication.id]));
  return apiJson({ publication: serializePublication(publication, { metrics_latest: metricsLatest }) });
});
