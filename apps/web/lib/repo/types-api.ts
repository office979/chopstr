import type { CaptionStyle, Platform, TranscriptStats, TranscriptWord } from "@/lib/repo/types";

/* Datentypen für Phase 5a (API-Schlüssel, Webhooks, Outbox, Publikationen): Spiegel von
 * packages/schema/migrations/0005_phase5.sql. Eigenständiges Modul, damit lib/repo/types.ts unberührt bleibt. */

export const API_SCOPES = ["read", "write", "publish", "admin"] as const;
export type ApiScope = (typeof API_SCOPES)[number];

export const SCOPE_LABELS: Record<ApiScope, string> = {
  read: "Lesen",
  write: "Schreiben",
  publish: "Veröffentlichen",
  admin: "Verwaltung",
};

export const SCOPE_DESCRIPTIONS: Record<ApiScope, string> = {
  read: "Quellen, Transkripte, Kandidaten, Clips und Kontingent lesen.",
  write: "Quellen anlegen, Kandidaten beurteilen, Hooks speichern, Renders und Gast-Freigaben anstoßen.",
  publish: "Clips über verbundene Plattformen veröffentlichen.",
  admin: "Webhooks verwalten. Für den MCP-Server nie nötig.",
};

export interface ApiKey {
  id: string;
  workspace_id: string;
  name: string;
  key_prefix: string;
  scopes: ApiScope[];
  created_by: string | null;
  created_by_label?: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/* Abgelaufen (expires_at in der Vergangenheit); Widerruf ist getrennt (revoked_at) */
export function isApiKeyExpired(key: Pick<ApiKey, "expires_at">, now: number = Date.now()): boolean {
  return Boolean(key.expires_at && Date.parse(key.expires_at) <= now);
}

export interface ApiKeyCreateInput {
  name: string;
  scopes: ApiScope[];
  expires_at: string | null;
  key_prefix: string;
  key_hash: string;
}

/* Treffer bei der Auflösung eines Bearer-Tokens (ohne Sitzung, Auth-Rolle) */
export interface ApiKeyLookup extends ApiKey {
  workspace_name: string;
  workspace_slug: string;
  workspace_plan: string;
  created_by_email: string | null;
  created_by_name: string | null;
}

export const WEBHOOK_EVENTS = [
  "source.ready",
  "source.failed",
  "candidates.ready",
  "clip.rendered",
  "clip.failed",
  "guest_approval.decided",
  "publication.published",
  "publication.failed",
  "usage.threshold",
] as const;
export type WebhookEvent = (typeof WEBHOOK_EVENTS)[number];

/* Testzustellung aus der Webhook-Verwaltung; nicht abonnierbar, geht direkt an einen Endpunkt */
export const WEBHOOK_PING_EVENT = "webhook.ping";

export const WEBHOOK_EVENT_LABELS: Record<WebhookEvent, string> = {
  "source.ready": "Quelle bereit (Transkript und Kandidaten liegen vor)",
  "source.failed": "Quelle fehlgeschlagen",
  "candidates.ready": "Kandidaten bereit",
  "clip.rendered": "Clip gerendert",
  "clip.failed": "Render fehlgeschlagen",
  "guest_approval.decided": "Gast hat entschieden",
  "publication.published": "Veröffentlicht",
  "publication.failed": "Veröffentlichung fehlgeschlagen",
  "usage.threshold": "Kontingent bei 80 % oder 100 %",
};

export interface WebhookEndpoint {
  id: string;
  workspace_id: string;
  url: string;
  events: string[];
  active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebhookEndpointCreateInput {
  url: string;
  events: string[];
  secret: string;
  active?: boolean;
}

export type WebhookDeliveryStatus = "pending" | "delivered" | "failed";

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  outbox_id: number | null;
  event: string;
  payload: Record<string, unknown>;
  attempt: number;
  status: WebhookDeliveryStatus;
  response_code: number | null;
  error: string | null;
  next_attempt_at: string;
  delivered_at: string | null;
  created_at: string;
}

export interface OutboxEvent {
  id: number;
  workspace_id: string;
  event: string;
  entity: string | null;
  entity_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  processed_at: string | null;
}

export type PublicationStatus = "scheduled" | "publishing" | "published" | "failed" | "manual";

export interface Publication {
  id: string;
  workspace_id: string | null;
  clip_id: string;
  connection_id: string | null;
  platform: string;
  status: PublicationStatus;
  scheduled_for: string | null;
  caption: string | null;
  title: string | null;
  external_id: string | null;
  external_url: string | null;
  error: string | null;
  published_at: string | null;
  metrics: Record<string, unknown> | null;
  metrics_fetched_at: string | null;
  temporal_workflow_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface PublicationCreateInput {
  clip_id: string;
  connection_id: string;
  platform: string;
  scheduled_for: string | null;
  caption: string | null;
  title: string | null;
}

/* Nur die Felder, die die API-Schicht zum Gate braucht; Verwaltung liegt in Welle 5b */
export interface PlatformConnectionSummary {
  id: string;
  workspace_id: string;
  brand_profile_id: string | null;
  platform: "tiktok" | "instagram" | "youtube" | "linkedin" | "manual";
  account_label: string;
  status: "connected" | "expired" | "revoked";
  capabilities: Record<string, unknown>;
}

/* Upload per API (upload: "tus"): die Quelle existiert schon als `uploading`, der tusd-Hook ergänzt die Datei */
export interface UploadCompletionPatch {
  storage_key: string;
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
}

/* 5c: Caption-Textfeld im Markenprofil (caption_style.caption_text_field), Erweiterung ohne Änderung an types.ts */
export type CaptionTextField = "text" | "text_norm";
export interface CaptionStyleExt extends CaptionStyle {
  caption_text_field?: CaptionTextField;
}

/* 5c: Dialekterkennung aus transcript_versions.stats.dialect (Worker: activities/nlp.py) */
export interface DialectStats {
  variant: "de" | "de-AT" | "de-CH";
  confidence: number;
  markers: string[];
}
export interface TranscriptStatsExt extends TranscriptStats {
  dialect?: DialectStats;
  text_norm_count?: number;
}
export interface TranscriptWordExt extends TranscriptWord {
  text_norm?: string | null;
}

export type { Platform };
