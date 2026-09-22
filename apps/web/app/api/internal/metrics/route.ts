import type { NextRequest } from "next/server";
import { checkInternalSecret } from "@/lib/api/internal-auth";
import { apiErrorResponse, apiJson } from "@/lib/api/errors";
import { metricsViaRegistry, type MetricWindow } from "@/lib/api/internal-publish";

export const dynamic = "force-dynamic";

const WINDOWS: MetricWindow[] = ["6h", "48h", "7d"];

/* Worker → Web: { publication_id, window } → { metrics: { views, likes, comments, shares, saves, follows, avg_watch_time_s, retention_curve } },
 * nicht garantierte Felder null (Capability Flags). Ohne Provider-Modul: alle Felder null plus Hinweis. */
export async function POST(request: NextRequest) {
  const denied = checkInternalSecret(request);
  if (denied) return denied;
  let body: { publication_id?: unknown; window?: unknown } = {};
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return apiErrorResponse(400, "invalid_json", "Ungültiger JSON-Body.");
  }
  if (typeof body.publication_id !== "string" || !body.publication_id) return apiErrorResponse(400, "validation_failed", "publication_id fehlt.");
  if (typeof body.window !== "string" || !WINDOWS.includes(body.window as MetricWindow)) return apiErrorResponse(400, "validation_failed", "window muss 6h, 48h oder 7d sein.");
  const result = await metricsViaRegistry(body.publication_id, body.window as MetricWindow);
  return apiJson({ metrics: result.metrics, available: result.available, error: result.error });
}
