import type { ApiRepo } from "@/lib/repo/api";
import { currentSession } from "@/lib/session";
import type { ApiKey, ApiKeyLookup, OutboxEvent, Publication, WebhookDelivery, WebhookEndpoint } from "@/lib/repo/types-api";

/* In-Memory-Variante des Phase-5a-Repositories für den Demo-Modus (ohne DATABASE_URL). Überlebt Hot Reloads. */

interface DemoApiState {
  keys: (ApiKey & { key_hash: string })[];
  endpoints: (WebhookEndpoint & { secret: string })[];
  deliveries: WebhookDelivery[];
  outbox: OutboxEvent[];
  publications: Publication[];
  nextOutboxId: number;
}

declare global {
  var __chopstrApiDemo: DemoApiState | undefined;
}

function state(): DemoApiState {
  if (!globalThis.__chopstrApiDemo) {
    globalThis.__chopstrApiDemo = { keys: [], endpoints: [], deliveries: [], outbox: [], publications: [], nextOutboxId: 1 };
  }
  return globalThis.__chopstrApiDemo;
}

function visibleKey(key: ApiKey & { key_hash: string }): ApiKey {
  const copy: ApiKey & { key_hash?: string } = { ...key };
  delete copy.key_hash;
  return copy;
}

function visibleEndpoint(endpoint: WebhookEndpoint & { secret: string }): WebhookEndpoint {
  const copy: WebhookEndpoint & { secret?: string } = { ...endpoint };
  delete copy.secret;
  return copy;
}

function uuid(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

export const apiDemoRepo: ApiRepo = {
  kind: "demo",

  async listApiKeys() {
    const session = await currentSession();
    return state()
      .keys.filter((k) => k.workspace_id === session.workspaceId)
      .map(visibleKey)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  async createApiKey(input) {
    const session = await currentSession();
    const key: ApiKey & { key_hash: string } = {
      id: uuid(),
      workspace_id: session.workspaceId,
      name: input.name,
      key_prefix: input.key_prefix,
      key_hash: input.key_hash,
      scopes: input.scopes,
      created_by: session.userId,
      created_by_label: session.displayName,
      last_used_at: null,
      expires_at: input.expires_at,
      revoked_at: null,
      created_at: now(),
    };
    state().keys.unshift(key);
    return visibleKey(key);
  },

  async revokeApiKey(id) {
    const session = await currentSession();
    const key = state().keys.find((k) => k.id === id && k.workspace_id === session.workspaceId && !k.revoked_at);
    if (!key) return null;
    key.revoked_at = now();
    return visibleKey(key);
  },

  async findApiKeyByHash(hash) {
    const key = state().keys.find((k) => k.key_hash === hash);
    if (!key) return null;
    const lookup: ApiKeyLookup = {
      ...visibleKey(key),
      workspace_name: "PLACEMedia",
      workspace_slug: "placemedia",
      workspace_plan: "agency",
      created_by_email: "demo@chopstr.local",
      created_by_name: "Demo",
    };
    return lookup;
  },

  async touchApiKey(id) {
    const key = state().keys.find((k) => k.id === id);
    if (key) key.last_used_at = now();
  },

  async listWebhookEndpoints() {
    const session = await currentSession();
    return state()
      .endpoints.filter((e) => e.workspace_id === session.workspaceId)
      .map(visibleEndpoint);
  },

  async getWebhookEndpoint(id) {
    const session = await currentSession();
    return state().endpoints.find((e) => e.id === id && e.workspace_id === session.workspaceId) ?? null;
  },

  async createWebhookEndpoint(input) {
    const session = await currentSession();
    const endpoint = {
      id: uuid(),
      workspace_id: session.workspaceId,
      url: input.url,
      secret: input.secret,
      events: input.events,
      active: input.active ?? true,
      created_by: session.userId,
      created_at: now(),
      updated_at: now(),
    };
    state().endpoints.unshift(endpoint);
    return visibleEndpoint(endpoint);
  },

  async updateWebhookEndpoint(id, patch) {
    const session = await currentSession();
    const endpoint = state().endpoints.find((e) => e.id === id && e.workspace_id === session.workspaceId);
    if (!endpoint) return null;
    if (patch.active !== undefined) endpoint.active = patch.active;
    if (patch.events !== undefined) endpoint.events = patch.events;
    if (patch.url !== undefined) endpoint.url = patch.url;
    endpoint.updated_at = now();
    return visibleEndpoint(endpoint);
  },

  async deleteWebhookEndpoint(id) {
    const session = await currentSession();
    const s = state();
    const before = s.endpoints.length;
    s.endpoints = s.endpoints.filter((e) => !(e.id === id && e.workspace_id === session.workspaceId));
    s.deliveries = s.deliveries.filter((d) => d.endpoint_id !== id);
    return s.endpoints.length < before;
  },

  async listWebhookDeliveries(limit = 100) {
    const session = await currentSession();
    const ids = new Set(state().endpoints.filter((e) => e.workspace_id === session.workspaceId).map((e) => e.id));
    return state()
      .deliveries.filter((d) => ids.has(d.endpoint_id))
      .slice(0, limit);
  },

  async insertOutboxEvent(input) {
    const s = state();
    const event: OutboxEvent = {
      id: s.nextOutboxId++,
      workspace_id: input.workspace_id,
      event: input.event,
      entity: input.entity,
      entity_id: input.entity_id,
      payload: input.payload,
      created_at: now(),
      processed_at: input.processed_at ?? null,
    };
    s.outbox.push(event);
    return event;
  },

  async hasOutboxEvent(workspaceId, event, match) {
    return state().outbox.some(
      (e) => e.workspace_id === workspaceId && e.event === event && Object.entries(match).every(([k, v]) => String(e.payload[k]) === v),
    );
  },

  async createWebhookDelivery(input) {
    const delivery: WebhookDelivery = {
      id: uuid(),
      endpoint_id: input.endpoint_id,
      outbox_id: input.outbox_id,
      event: input.event,
      payload: input.payload,
      attempt: 0,
      status: "pending",
      response_code: null,
      error: null,
      next_attempt_at: now(),
      delivered_at: null,
      created_at: now(),
    };
    state().deliveries.unshift(delivery);
    return delivery;
  },

  async getPlatformConnection(id) {
    /* Demo: eine manuelle Verbindung, damit publish_clip durchspielbar ist */
    const session = await currentSession();
    if (id !== "77777777-7777-4777-8777-777777777701") return null;
    return { id, workspace_id: session.workspaceId, brand_profile_id: null, platform: "manual", account_label: "Manuell (Demo)", status: "connected", capabilities: { publish: false } };
  },

  async createPublication(input) {
    const session = await currentSession();
    const publication: Publication = {
      id: uuid(),
      workspace_id: session.workspaceId,
      clip_id: input.clip_id,
      connection_id: input.connection_id,
      platform: input.platform,
      status: "scheduled",
      scheduled_for: input.scheduled_for,
      caption: input.caption,
      title: input.title,
      external_id: null,
      external_url: null,
      error: null,
      published_at: null,
      metrics: null,
      metrics_fetched_at: null,
      temporal_workflow_id: null,
      created_by: session.userId,
      created_at: now(),
    };
    state().publications.unshift(publication);
    return publication;
  },

  async getPublication(id) {
    const session = await currentSession();
    return state().publications.find((p) => p.id === id && p.workspace_id === session.workspaceId) ?? null;
  },

  async setPublicationWorkflow(id, workflowId) {
    const p = state().publications.find((x) => x.id === id);
    if (p) p.temporal_workflow_id = workflowId;
  },

  async completeUploadingSource() {
    return false;
  },
};
