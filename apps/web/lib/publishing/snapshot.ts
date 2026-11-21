import type { MetricSet, MetricWindow } from "@/lib/repo/types-publishing";
import type { LinkPlatform } from "./links";
import { emptyPublicMetrics, type PublicMetricSet, type PublicMetricSource, type PublicMetricsErrorCode, type PublicMetricsResult } from "./public-metrics";

/* Eine Messung für die Zeitreihe (POST /api/internal/metrics mit mode "snapshot").
 *
 *   tracking oauth: wie bisher über den Provider der Verbindung (metricsViaRegistry).
 *   tracking link:  öffentliche Leser (YouTube, X); gehört der Beitrag einer Verbindung und liefern die
 *                   öffentlichen Leser nichts, dann über die Verbindung.
 * Rein: Provider und Leser kommen als Funktionen herein. Wirft nie; Fehler stehen in error (Text für den
 * Worker und das Log) und error_code (SNAPSHOT_ERROR_CODES). Der Worker speichert beides als
 * "<code>: <text>" in metric_snapshots.error; die öffentliche API zeigt nur Code und eine feste Meldung
 * (lib/publishing/performance.ts). */

/* Fehlerarten einer Messung. Die ersten fünf entstehen hier, die übrigen im Worker (run_snapshot). */
export const SNAPSHOT_ERROR_CODES = [
  "nicht_konfiguriert",
  "nicht_verbunden",
  "keine_verbindung",
  "nicht_gefunden",
  "plattform_fehler",
  "abgeschaltet",
  "ungueltig",
  "messdienst_nicht_erreichbar",
  "messdienst_fehler",
  "konfiguration",
] as const;
export type SnapshotErrorCode = (typeof SNAPSHOT_ERROR_CODES)[number];

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
  error_code: SnapshotErrorCode | null;
  /* Zeitpunkt der Veröffentlichung laut öffentlichem Leser; der Worker übernimmt ihn, wenn er noch fehlt */
  published_at: string | null;
}

function readerCode(error: PublicMetricsErrorCode): SnapshotErrorCode {
  return error === "fehler" ? "plattform_fehler" : error;
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
  const viaOauth = async (fallback: { error: string; code: SnapshotErrorCode } | null): Promise<SnapshotResult> => {
    const r = await deps.viaConnection(window).catch((e: unknown) => ({ metrics: {}, error: e instanceof Error ? e.message : String(e) }));
    if (!r) return { metrics: emptyPublicMetrics(), source: "oauth", raw: null, error: fallback?.error ?? "Keine nutzbare Verbindung.", error_code: fallback?.code ?? "keine_verbindung", published_at: null };
    return { metrics: merge(r.metrics), source: "oauth", raw: null, error: r.error ?? null, error_code: r.error ? "plattform_fehler" : null, published_at: null };
  };

  if (pub.tracking === "off") return { metrics: emptyPublicMetrics(), source: "oauth", raw: null, error: "Messung ist abgeschaltet.", error_code: "abgeschaltet", published_at: null };
  if (pub.tracking !== "link") return viaOauth(null);

  const platform = linkPlatformOf(pub.platform);
  if (!platform || !pub.external_id) return { metrics: emptyPublicMetrics(), source: "public_api", raw: null, error: "Publikation ohne Plattform oder externe ID.", error_code: "ungueltig", published_at: null };
  const pr = await deps.readPublic(platform, pub.external_id);
  if (pr.ok) return { metrics: pr.metrics, source: pr.source, raw: pr.raw, error: null, error_code: null, published_at: pr.published_at };
  const text = pr.detail ? `${pr.message} ${pr.detail}` : pr.message;
  if (pub.connection_id && pr.error !== "nicht_gefunden") return viaOauth({ error: text, code: readerCode(pr.error) });
  return { metrics: emptyPublicMetrics(), source: "public_api", raw: null, error: text, error_code: readerCode(pr.error), published_at: null };
}
