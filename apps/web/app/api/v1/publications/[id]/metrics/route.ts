import type { NextRequest } from "next/server";
import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, badRequest } from "@/lib/api/errors";
import { loadPublication } from "@/lib/api/lookup";
import { buildPublicationMetrics, parseSeriesQuery } from "@/lib/publishing/performance";

export const dynamic = "force-dynamic";

/* Messwerte einer Publikation: letzte Messung, feste Fenster (performance_feedback mit follows_per_1k,
 * saves_per_1k, outlier_score, reward) und die Messreihe (metric_snapshots, ?since=, ?limit=). Dazu
 * engagement_rate je Messung und der Plausibilitätshinweis anomaly (lib/publishing/performance.ts). */
export const GET = apiRoute<{ id: string }>("read", async (request: NextRequest, { params }) => {
  const query = parseSeriesQuery(request.nextUrl.searchParams);
  if ("error" in query) throw badRequest(query.error, "validation_failed");
  const repo = getApiRepo();
  const publication = await loadPublication(params.id);
  const [snapshots, feedback] = await Promise.all([repo.listMetricSnapshots([publication.id]), repo.listWindowFeedback([publication.id])]);
  return apiJson({ tracking: publication.tracking ?? "oauth", tracking_until: publication.tracking_until ?? null, ...buildPublicationMetrics(publication.id, snapshots, feedback, query) });
});
