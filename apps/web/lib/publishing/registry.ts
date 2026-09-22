import "server-only";
import { getStore } from "@/lib/storage";
import { mediaUrl } from "@/lib/clips/labels";
import { EMPTY_METRICS, maskMetrics } from "@/lib/publishing/capabilities";
import { loadPublicationInternal, storeCredentialsInternal, markConnectionStatusInternal } from "@/lib/repo/publishing";
import type { ConnectionPlatform, Credentials, MetricSet, MetricWindow } from "@/lib/repo/types-publishing";
import { manualProvider } from "./providers/manual";
import { tiktokProvider } from "./providers/tiktok";
import { instagramProvider } from "./providers/instagram";
import { youtubeProvider } from "./providers/youtube";
import { linkedinProvider } from "./providers/linkedin";
import { ProviderError, type Provider, type PublishResult } from "./providers/types";

/* Provider-Registry (PHASE5.md 5b und „Interne Schnittstelle“). `publish(publicationId)` und `metrics(publicationId, window)`
 * werden von /api/internal/publish und /api/internal/metrics (Welle 5a) dynamisch importiert: der Worker besitzt
 * Zeitplanung und schreibt publications.status und performance_feedback; hier passiert nur der Plattform-Aufruf.
 * Zugangsdaten werden entschlüsselt, bei Ablauf erneuert und nie geloggt. */

export const providers: Record<ConnectionPlatform, Provider> = {
  manual: manualProvider,
  tiktok: tiktokProvider,
  instagram: instagramProvider,
  youtube: youtubeProvider,
  linkedin: linkedinProvider,
};

export const PLATFORM_ORDER: ConnectionPlatform[] = ["manual", "tiktok", "instagram", "youtube", "linkedin"];

export function isConnectionPlatform(v: unknown): v is ConnectionPlatform {
  return typeof v === "string" && v in providers;
}

export function providerStatus(): { platform: ConnectionPlatform; label: string; configured: boolean }[] {
  return PLATFORM_ORDER.map((p) => ({ platform: p, label: providers[p].label, configured: providers[p].configured() }));
}

/* Redirect-URI für OAuth-Callbacks: PUBLISH_REDIRECT_BASE (= APP_BASE_URL), sonst die aufrufende Basis */
export function redirectUriFor(platform: ConnectionPlatform, fallbackBase: string): string {
  const base = (process.env.PUBLISH_REDIRECT_BASE ?? process.env.APP_BASE_URL ?? fallbackBase).replace(/\/+$/, "");
  return `${base}/api/publishing/oauth/${platform}/callback`;
}

function tokenExpired(creds: Credentials | null): boolean {
  if (!creds?.expires_at) return false;
  const t = Date.parse(creds.expires_at);
  return Number.isFinite(t) && t - Date.now() < 5 * 60 * 1000;
}

/* Zugangsdaten frisch halten: bei Ablauf refresh() und verschlüsselt speichern; bei Fehler Verbindung `expired` */
async function freshCredentials(connectionId: string, platform: ConnectionPlatform, creds: Credentials | null): Promise<Credentials> {
  if (!creds) throw new ProviderError("Verbindung ohne Zugangsdaten (getrennt oder nie verbunden).");
  if (!tokenExpired(creds)) return creds;
  try {
    const next = await providers[platform].refresh(creds);
    await storeCredentialsInternal(connectionId, next, next.expires_at ?? null, "connected");
    return next;
  } catch (error) {
    await markConnectionStatusInternal(connectionId, "expired");
    throw error;
  }
}

export interface InternalPublishResult extends PublishResult {
  publication_id: string;
  platform: string;
}

/* Von /api/internal/publish: `{ status: "published" | "failed", external_id, external_url, error }` */
export async function publish(publicationId: string): Promise<InternalPublishResult> {
  const ctx = await loadPublicationInternal(publicationId);
  if (!ctx) return { publication_id: publicationId, platform: "unknown", status: "failed", external_id: null, external_url: null, error: "Publikation nicht gefunden." };
  const { publication, connection, credentials, clip } = ctx;
  const base = { publication_id: publicationId, platform: publication.platform };
  if (!connection) return { ...base, status: "failed", external_id: null, external_url: null, error: "Publikation ohne Verbindung." };
  if (connection.status !== "connected") return { ...base, status: "failed", external_id: null, external_url: null, error: `Verbindung ist ${connection.status === "revoked" ? "getrennt" : "abgelaufen"}.` };
  if (connection.platform === "manual") return { ...base, status: "failed", external_id: null, external_url: null, error: "Manuelle Verbindung: der Nutzer postet selbst." };
  const provider = providers[connection.platform];
  if (!provider.configured()) return { ...base, status: "failed", external_id: null, external_url: null, error: `${provider.label} ist nicht konfiguriert.` };
  if (!clip.file_key) return { ...base, status: "failed", external_id: null, external_url: null, error: "Clip hat keine Videodatei." };
  try {
    const creds = await freshCredentials(connection.id, connection.platform, credentials);
    const fileKey = clip.file_key;
    const result = await provider.publish(creds, {
      title: publication.title ?? clip.title_card ?? "",
      caption: publication.caption ?? "",
      video_url: mediaUrl(process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null, fileKey),
      loadVideo: async () => (await getStore().get("derived", fileKey))?.body ?? null,
      duration_s: clip.duration_s,
      scheduled_for: publication.scheduled_for,
    });
    return { ...base, ...result };
  } catch (error) {
    return { ...base, status: "failed", external_id: null, external_url: null, error: error instanceof Error ? error.message : "Unbekannter Fehler beim Veröffentlichen." };
  }
}

export interface InternalMetricsResult {
  publication_id: string;
  window: MetricWindow;
  metrics: MetricSet;
  error?: string;
}

/* Von /api/internal/metrics: `{ metrics: { views, likes, ... } }` mit null für nicht garantierte Felder (Capability Flags) */
export async function metrics(publicationId: string, window: MetricWindow): Promise<InternalMetricsResult> {
  const ctx = await loadPublicationInternal(publicationId);
  if (!ctx) return { publication_id: publicationId, window, metrics: { ...EMPTY_METRICS }, error: "Publikation nicht gefunden." };
  const { publication, connection, credentials } = ctx;
  if (!connection || connection.platform === "manual" || !publication.external_id) {
    return { publication_id: publicationId, window, metrics: { ...EMPTY_METRICS }, error: connection ? "Keine externe ID oder manuelle Verbindung." : "Publikation ohne Verbindung." };
  }
  const provider = providers[connection.platform];
  try {
    const creds = await freshCredentials(connection.id, connection.platform, credentials);
    const raw = await provider.fetchMetrics(creds, publication.external_id, window);
    return { publication_id: publicationId, window, metrics: maskMetrics(raw, connection.capabilities) };
  } catch (error) {
    return { publication_id: publicationId, window, metrics: { ...EMPTY_METRICS }, error: error instanceof Error ? error.message : "Metrik-Abruf fehlgeschlagen." };
  }
}
