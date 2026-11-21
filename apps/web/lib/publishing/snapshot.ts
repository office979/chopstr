import type { MetricSet, MetricWindow } from "@/lib/repo/types-publishing";
import type { LinkPlatform } from "./links";
import { emptyPublicMetrics, type PublicMetricSet, type PublicMetricSource, type PublicMetricsResult } from "./public-metrics";

/* Eine Messung für die Zeitreihe (POST /api/internal/metrics mit mode "snapshot").
 *
 *   tracking oauth: wie bisher über den Provider der Verbindung (metricsViaRegistry).
 *   tracking link:  öffentliche Leser (YouTube, X); gehört der Beitrag einer Verbindung und liefern die
 *                   öffentlichen Leser nichts, dann über die Verbindung.
 * Rein: Provider und Leser kommen als Funktionen herein. Wirft nie; Fehler stehen in error. */

const LINK_PLATFORMS: readonly LinkPlatform[] = ["youtube", "tiktok", "instagram", "x", "linkedin"];

export interface SnapshotPublication {
  platform: string;
  external_id: string | null;
  connection_id: string | null;
  tracking?: "oauth" | "link" | "off";
}

export interface SnapshotDeps {
  readPublic: (platform: LinkPlatform, externalId: string) => Promise<PublicMetricsResult>;
  /* Messung über die verbundene Plattform; null, wenn keine nutzbare Verbindung da ist */
  viaConnection: (window: MetricWindow) => Promise<{ metrics: Partial<MetricSet>; error?: string } | null>;
}

export interface SnapshotResult {
  metrics: PublicMetricSet;
  source: PublicMetricSource;
  raw: unknown;
  error: string | null;
}

/* Clip-Formate und Verbindungs-Plattformen auf die Link-Plattform abbilden (ältere Zeilen speichern shorts, reels) */
export function linkPlatformOf(platform: string): LinkPlatform | null {
  if (platform === "shorts") return "youtube";
  if (platform === "reels") return "instagram";
  return (LINK_PLATFORMS as readonly string[]).includes(platform) ? (platform as LinkPlatform) : null;
}

function merge(partial: Partial<MetricSet>): PublicMetricSet {
  const out: Record<string, unknown> = { ...emptyPublicMetrics() };
  const src = partial as Record<string, unknown>;
  for (const k of Object.keys(out)) if (src[k] !== undefined) out[k] = src[k];
  return out as unknown as PublicMetricSet;
}

export async function takeSnapshot(pub: SnapshotPublication, window: MetricWindow, deps: SnapshotDeps): Promise<SnapshotResult> {
  const viaOauth = async (prefix: string | null): Promise<SnapshotResult> => {
    const r = await deps.viaConnection(window).catch((e: unknown) => ({ metrics: {}, error: e instanceof Error ? e.message : String(e) }));
    if (!r) return { metrics: emptyPublicMetrics(), source: "oauth", raw: null, error: prefix ?? "Keine nutzbare Verbindung." };
    return { metrics: merge(r.metrics), source: "oauth", raw: null, error: r.error ?? null };
  };

  if (pub.tracking === "off") return { metrics: emptyPublicMetrics(), source: "oauth", raw: null, error: "Messung ist abgeschaltet." };
  if (pub.tracking !== "link") return viaOauth(null);

  const platform = linkPlatformOf(pub.platform);
  if (!platform || !pub.external_id) return { metrics: emptyPublicMetrics(), source: "public_api", raw: null, error: "Publikation ohne Plattform oder externe ID." };
  const pr = await deps.readPublic(platform, pub.external_id);
  if (pr.ok) return { metrics: pr.metrics, source: pr.source, raw: pr.raw, error: null };
  if (pub.connection_id && pr.error !== "nicht_gefunden") return viaOauth(pr.message);
  return { metrics: emptyPublicMetrics(), source: "public_api", raw: null, error: pr.message };
}
