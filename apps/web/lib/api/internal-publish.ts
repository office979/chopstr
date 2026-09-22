import "server-only";

/* Dünne Schnittstelle zum Publishing-Modul aus Welle 5b (lib/publishing/registry). Das Modul entsteht parallel;
 * fehlt es, antwortet der interne Endpunkt mit status failed und einem klaren Hinweis, statt zu werfen.
 * Vereinbarte Signatur:
 *   registry.publish(publicationId) → { status: "published" | "failed", external_id, external_url, error }
 *   registry.metrics(publicationId, window) → { metrics: { views, likes, comments, shares, saves, follows, avg_watch_time_s, retention_curve } } */

export interface PublishResult {
  status: "published" | "failed";
  external_id: string | null;
  external_url: string | null;
  error: string | null;
}

export const METRIC_KEYS = ["views", "likes", "comments", "shares", "saves", "follows", "avg_watch_time_s", "retention_curve"] as const;
export type MetricWindow = "6h" | "48h" | "7d";
export type Metrics = Record<(typeof METRIC_KEYS)[number], unknown>;

interface Registry {
  publish?: (publicationId: string) => Promise<Partial<PublishResult> | null | undefined>;
  metrics?: (publicationId: string, window: MetricWindow) => Promise<{ metrics?: Partial<Metrics> | null } | null | undefined>;
}

export const PROVIDER_UNAVAILABLE = "Publishing-Provider nicht verfügbar";

async function loadRegistry(): Promise<Registry | null> {
  /* Dynamisch geladen: Fehler beim Laden (fehlendes Modul, Konfigurationsfehler) führen zu status failed statt 500 */
  try {
    const mod = (await import("@/lib/publishing/registry")) as unknown as Registry & { default?: Registry; registry?: Registry };
    return mod.registry ?? mod.default ?? mod;
  } catch (error) {
    console.warn("[internal] lib/publishing/registry nicht ladbar:", error instanceof Error ? error.message : error);
    return null;
  }
}

export function emptyMetrics(): Metrics {
  return Object.fromEntries(METRIC_KEYS.map((k) => [k, null])) as Metrics;
}

export async function publishViaRegistry(publicationId: string): Promise<PublishResult> {
  const registry = await loadRegistry();
  if (!registry?.publish) return { status: "failed", external_id: null, external_url: null, error: PROVIDER_UNAVAILABLE };
  try {
    const r = (await registry.publish(publicationId)) ?? {};
    return {
      status: r.status === "published" ? "published" : "failed",
      external_id: r.external_id ?? null,
      external_url: r.external_url ?? null,
      error: r.status === "published" ? null : (r.error ?? "Veröffentlichung fehlgeschlagen"),
    };
  } catch (error) {
    return { status: "failed", external_id: null, external_url: null, error: error instanceof Error ? error.message : "Veröffentlichung fehlgeschlagen" };
  }
}

export async function metricsViaRegistry(publicationId: string, window: MetricWindow): Promise<{ metrics: Metrics; available: boolean; error: string | null }> {
  const registry = await loadRegistry();
  if (!registry?.metrics) return { metrics: emptyMetrics(), available: false, error: PROVIDER_UNAVAILABLE };
  try {
    const r = (await registry.metrics(publicationId, window)) ?? {};
    const raw = r.metrics ?? {};
    const metrics = emptyMetrics();
    for (const k of METRIC_KEYS) metrics[k] = raw[k] ?? null;
    return { metrics, available: true, error: null };
  } catch (error) {
    return { metrics: emptyMetrics(), available: false, error: error instanceof Error ? error.message : "Metriken nicht abrufbar" };
  }
}
