import type { Capabilities, ConnectionPlatform, Credentials, MetricSet, MetricWindow } from "@/lib/repo/types-publishing";

/* Provider-Vertrag (PHASE5.md, 5b): OAuth, Publish, Metriken je Plattform. Alle Aufrufe mit fetch, keine SDKs.
 * Jeder Endpunkt ist im Provider mit `TODO verify against current docs` markiert (Entscheidungsregister CON-007). */

export interface ExchangeResult {
  credentials: Credentials;
  account_label: string;
  external_account_id: string | null;
  expires_at: string | null;
}

export interface PublishInput {
  title: string;
  caption: string;
  /* Öffentliche URL des MP4 (NEXT_PUBLIC_MEDIA_BASE_URL), wenn vorhanden */
  video_url: string | null;
  /* Bytes des MP4 aus dem derived-Bucket, für Upload-Flows */
  loadVideo: () => Promise<Uint8Array | null>;
  duration_s: number | null;
  scheduled_for: string | null;
}

export interface PublishResult {
  status: "published" | "failed";
  external_id: string | null;
  external_url: string | null;
  error: string | null;
}

export interface Provider {
  readonly platform: ConnectionPlatform;
  readonly label: string;
  /* App-Zugangsdaten aus Env vorhanden */
  configured(): boolean;
  capabilities(): Capabilities;
  authorizeUrl(state: string, redirectUri: string): string;
  exchangeCode(code: string, redirectUri: string): Promise<ExchangeResult>;
  refresh(creds: Credentials): Promise<Credentials>;
  publish(creds: Credentials, input: PublishInput): Promise<PublishResult>;
  fetchMetrics(creds: Credentials, externalId: string, window: MetricWindow): Promise<Partial<MetricSet>>;
}

export class ProviderError extends Error {
  readonly status: number | null;
  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ProviderError";
    this.status = status;
  }
}

export class NotConfiguredError extends ProviderError {
  constructor(label: string) {
    super(`${label} ist nicht konfiguriert (App-Zugangsdaten fehlen in der Umgebung).`);
    this.name = "NotConfiguredError";
  }
}
