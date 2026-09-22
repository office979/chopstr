import "server-only";
import { getSql, withAuthContext, withContext, type Tx } from "@/lib/db";
import { isDemoMode } from "@/lib/env";
import { currentSession } from "@/lib/session";
import { apiDemoRepo } from "@/lib/repo/api-demo";
import type {
  ApiKey,
  ApiKeyCreateInput,
  ApiKeyLookup,
  OutboxEvent,
  PlatformConnectionSummary,
  Publication,
  PublicationCreateInput,
  UploadCompletionPatch,
  WebhookDelivery,
  WebhookEndpoint,
  WebhookEndpointCreateInput,
} from "@/lib/repo/types-api";

/* Repository für Phase 5a: API-Schlüssel, Webhooks, Zustellungen, Outbox, Publikationen (nur Anlage und
 * Lesen; Status schreibt der Worker). Eigenständiges Modul neben lib/repo/postgres.ts, gleiche Muster:
 * sitzungsgebundene Methoden laufen in withContext (RLS), die Schlüsselauflösung ohne Sitzung in
 * withAuthContext (Rolle chopstr_auth). Demo-Modus: lib/repo/api-demo.ts (In-Memory). */

export interface ApiRepo {
  readonly kind: "postgres" | "demo";
  /* Schlüssel (Sitzung, api.manage) */
  listApiKeys(): Promise<ApiKey[]>;
  createApiKey(input: ApiKeyCreateInput): Promise<ApiKey>;
  revokeApiKey(id: string): Promise<ApiKey | null>;
  /* Schlüssel (ohne Sitzung): Auflösung per Hash, Nutzungszeit */
  findApiKeyByHash(hash: string): Promise<ApiKeyLookup | null>;
  touchApiKey(id: string): Promise<void>;
  /* Webhooks (Sitzung) */
  listWebhookEndpoints(): Promise<WebhookEndpoint[]>;
  getWebhookEndpoint(id: string): Promise<(WebhookEndpoint & { secret: string }) | null>;
  createWebhookEndpoint(input: WebhookEndpointCreateInput): Promise<WebhookEndpoint>;
  updateWebhookEndpoint(id: string, patch: { active?: boolean; events?: string[]; url?: string }): Promise<WebhookEndpoint | null>;
  deleteWebhookEndpoint(id: string): Promise<boolean>;
  listWebhookDeliveries(limit?: number): Promise<WebhookDelivery[]>;
  /* Outbox (ohne Sitzung, Web-seitige Ereignisse) */
  insertOutboxEvent(input: { workspace_id: string; event: string; entity: string | null; entity_id: string | null; payload: Record<string, unknown>; processed_at?: string | null }): Promise<OutboxEvent>;
  hasOutboxEvent(workspaceId: string, event: string, match: Record<string, string>): Promise<boolean>;
  /* Direkte Zustellung an einen Endpunkt (Ping), ohne den Outbox-Dispatcher */
  createWebhookDelivery(input: { endpoint_id: string; outbox_id: number | null; event: string; payload: Record<string, unknown> }): Promise<WebhookDelivery>;
  /* Publishing (Sitzung) */
  getPlatformConnection(id: string): Promise<PlatformConnectionSummary | null>;
  createPublication(input: PublicationCreateInput): Promise<Publication>;
  getPublication(id: string): Promise<Publication | null>;
  setPublicationWorkflow(id: string, workflowId: string | null): Promise<void>;
  /* Upload per API: Quelle war `uploading`, tusd-Hook ergänzt die Datei */
  completeUploadingSource(id: string, patch: UploadCompletionPatch): Promise<boolean>;
}

type Row = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "string" ? Number(v) : (v as number);
  return Number.isFinite(n) ? n : null;
}

function isoOrNull(v: unknown): string | null {
  if (v == null) return null;
  return v instanceof Date ? v.toISOString() : String(v);
}

function jsonValue<T>(v: unknown, fallback: T): T {
  if (v == null) return fallback;
  if (typeof v === "string") {
    try {
      return JSON.parse(v) as T;
    } catch {
      return fallback;
    }
  }
  return v as T;
}

function toApiKey(r: Row): ApiKey {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    name: r.name as string,
    key_prefix: r.key_prefix as string,
    scopes: ((r.scopes as string[]) ?? []) as ApiKey["scopes"],
    created_by: (r.created_by as string | null) ?? null,
    created_by_label: (r.created_by_label as string | null) ?? null,
    last_used_at: isoOrNull(r.last_used_at),
    expires_at: isoOrNull(r.expires_at),
    revoked_at: isoOrNull(r.revoked_at),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toEndpoint(r: Row): WebhookEndpoint {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    url: r.url as string,
    events: (r.events as string[]) ?? [],
    active: Boolean(r.active),
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
    updated_at: isoOrNull(r.updated_at) ?? "",
  };
}

function toDelivery(r: Row): WebhookDelivery {
  return {
    id: r.id as string,
    endpoint_id: r.endpoint_id as string,
    outbox_id: num(r.outbox_id),
    event: r.event as string,
    payload: jsonValue<Record<string, unknown>>(r.payload, {}),
    attempt: num(r.attempt) ?? 0,
    status: r.status as WebhookDelivery["status"],
    response_code: num(r.response_code),
    error: (r.error as string | null) ?? null,
    next_attempt_at: isoOrNull(r.next_attempt_at) ?? "",
    delivered_at: isoOrNull(r.delivered_at),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toOutbox(r: Row): OutboxEvent {
  return {
    id: num(r.id) ?? 0,
    workspace_id: r.workspace_id as string,
    event: r.event as string,
    entity: (r.entity as string | null) ?? null,
    entity_id: (r.entity_id as string | null) ?? null,
    payload: jsonValue<Record<string, unknown>>(r.payload, {}),
    created_at: isoOrNull(r.created_at) ?? "",
    processed_at: isoOrNull(r.processed_at),
  };
}

function toPublication(r: Row): Publication {
  return {
    id: r.id as string,
    workspace_id: (r.workspace_id as string | null) ?? null,
    clip_id: r.clip_id as string,
    connection_id: (r.connection_id as string | null) ?? null,
    platform: r.platform as string,
    status: (r.status as Publication["status"]) ?? "manual",
    scheduled_for: isoOrNull(r.scheduled_for),
    caption: (r.caption as string | null) ?? null,
    title: (r.title as string | null) ?? null,
    external_id: (r.external_id as string | null) ?? null,
    external_url: (r.external_url as string | null) ?? null,
    error: (r.error as string | null) ?? null,
    published_at: isoOrNull(r.published_at),
    metrics: jsonValue<Record<string, unknown> | null>(r.metrics, null),
    metrics_fetched_at: isoOrNull(r.metrics_fetched_at),
    temporal_workflow_id: (r.temporal_workflow_id as string | null) ?? null,
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toConnection(r: Row): PlatformConnectionSummary {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    platform: r.platform as PlatformConnectionSummary["platform"],
    account_label: r.account_label as string,
    status: r.status as PlatformConnectionSummary["status"],
    capabilities: jsonValue<Record<string, unknown>>(r.capabilities, {}),
  };
}

const KEY_SELECT = `
  select k.*, coalesce(u.display_name, u.email) as created_by_label
  from api_keys k left join users u on u.id = k.created_by`;

async function publicationByClipAccess(tx: Tx, workspaceId: string, id: string): Promise<Row | null> {
  /* Publikationen aus Migration 0001 haben kein workspace_id; über den Clip absichern */
  const rows = await tx`
    select p.* from publications p
    join clips c on c.id = p.clip_id join sources s on s.id = c.source_id
    where p.id = ${id} and coalesce(p.workspace_id, s.workspace_id) = ${workspaceId}`;
  return rows.length ? (rows[0] as Row) : null;
}

export const apiPostgresRepo: ApiRepo = {
  kind: "postgres",

  async listApiKeys() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx.unsafe(`${KEY_SELECT} where k.workspace_id = $1 order by k.created_at desc`, [session.workspaceId]);
      return rows.map((r) => toApiKey(r as Row));
    });
  },

  async createApiKey(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into api_keys (workspace_id, name, key_prefix, key_hash, scopes, created_by, expires_at)
        values (${session.workspaceId}, ${input.name}, ${input.key_prefix}, ${input.key_hash}, ${input.scopes}, ${session.userId}, ${input.expires_at})
        returning *`;
      return { ...toApiKey(rows[0] as Row), created_by_label: session.displayName };
    });
  },

  async revokeApiKey(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update api_keys set revoked_at = now() where id = ${id} and workspace_id = ${session.workspaceId} and revoked_at is null returning *`;
      return rows.length ? toApiKey(rows[0] as Row) : null;
    });
  },

  async findApiKeyByHash(hash) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        select k.*, w.name as workspace_name, w.slug as workspace_slug, w.plan as workspace_plan,
               u.email as created_by_email, coalesce(u.display_name, u.email) as created_by_name
        from api_keys k join workspaces w on w.id = k.workspace_id left join users u on u.id = k.created_by
        where k.key_hash = ${hash}`;
      if (!rows.length) return null;
      const r = rows[0] as Row;
      return {
        ...toApiKey(r),
        workspace_name: r.workspace_name as string,
        workspace_slug: r.workspace_slug as string,
        workspace_plan: r.workspace_plan as string,
        created_by_email: (r.created_by_email as string | null) ?? null,
        created_by_name: (r.created_by_name as string | null) ?? null,
      };
    });
  },

  async touchApiKey(id) {
    await withAuthContext(async (tx) => {
      await tx`update api_keys set last_used_at = now() where id = ${id}`;
    });
  },

  async listWebhookEndpoints() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from webhook_endpoints where workspace_id = ${session.workspaceId} order by created_at desc`;
      return rows.map((r) => toEndpoint(r as Row));
    });
  },

  async getWebhookEndpoint(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from webhook_endpoints where id = ${id} and workspace_id = ${session.workspaceId}`;
      if (!rows.length) return null;
      const r = rows[0] as Row;
      return { ...toEndpoint(r), secret: r.secret as string };
    });
  },

  async createWebhookEndpoint(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into webhook_endpoints (workspace_id, url, secret, events, active, created_by)
        values (${session.workspaceId}, ${input.url}, ${input.secret}, ${input.events}, ${input.active ?? true}, ${session.userId})
        returning *`;
      return toEndpoint(rows[0] as Row);
    });
  },

  async updateWebhookEndpoint(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      if (patch.active !== undefined) data.active = patch.active;
      if (patch.events !== undefined) data.events = patch.events;
      if (patch.url !== undefined) data.url = patch.url;
      if (Object.keys(data).length === 0) {
        const rows = await tx`select * from webhook_endpoints where id = ${id} and workspace_id = ${session.workspaceId}`;
        return rows.length ? toEndpoint(rows[0] as Row) : null;
      }
      const rows = await tx`update webhook_endpoints set ${tx(data)} where id = ${id} and workspace_id = ${session.workspaceId} returning *`;
      return rows.length ? toEndpoint(rows[0] as Row) : null;
    });
  },

  async deleteWebhookEndpoint(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`delete from webhook_endpoints where id = ${id} and workspace_id = ${session.workspaceId} returning id`;
      return rows.length > 0;
    });
  },

  async listWebhookDeliveries(limit = 100) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select d.* from webhook_deliveries d join webhook_endpoints e on e.id = d.endpoint_id
        where e.workspace_id = ${session.workspaceId} order by d.created_at desc limit ${limit}`;
      return rows.map((r) => toDelivery(r as Row));
    });
  },

  async insertOutboxEvent(input) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        insert into outbox_events (workspace_id, event, entity, entity_id, payload, processed_at)
        values (${input.workspace_id}, ${input.event}, ${input.entity}, ${input.entity_id}, ${tx.json(input.payload as never)}, ${input.processed_at ?? null})
        returning *`;
      return toOutbox(rows[0] as Row);
    });
  },

  async hasOutboxEvent(workspaceId, event, match) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        select 1 from outbox_events where workspace_id = ${workspaceId} and event = ${event} and payload @> ${tx.json(match as never)} limit 1`;
      return rows.length > 0;
    });
  },

  async createWebhookDelivery(input) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        insert into webhook_deliveries (endpoint_id, outbox_id, event, payload, attempt, status, next_attempt_at)
        values (${input.endpoint_id}, ${input.outbox_id}, ${input.event}, ${tx.json(input.payload as never)}, 0, 'pending', now())
        returning *`;
      return toDelivery(rows[0] as Row);
    });
  },

  async getPlatformConnection(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from platform_connections where id = ${id} and workspace_id = ${session.workspaceId}`;
      return rows.length ? toConnection(rows[0] as Row) : null;
    });
  },

  async createPublication(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into publications (workspace_id, clip_id, connection_id, platform, status, scheduled_for, caption, title, created_by)
        values (${session.workspaceId}, ${input.clip_id}, ${input.connection_id}, ${input.platform}, 'scheduled', ${input.scheduled_for}, ${input.caption}, ${input.title}, ${session.userId})
        returning *`;
      return toPublication(rows[0] as Row);
    });
  },

  async getPublication(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const row = await publicationByClipAccess(tx, session.workspaceId, id);
      return row ? toPublication(row) : null;
    });
  },

  async setPublicationWorkflow(id, workflowId) {
    const session = await currentSession();
    await withContext(session, async (tx) => {
      await tx`update publications set temporal_workflow_id = ${workflowId} where id = ${id} and workspace_id = ${session.workspaceId}`;
    });
  },

  async completeUploadingSource(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update sources set storage_key = ${patch.storage_key}, original_filename = ${patch.original_filename}, mime_type = ${patch.mime_type},
          size_bytes = ${patch.size_bytes}, status = 'uploaded', status_message = null
        where id = ${id} and workspace_id = ${session.workspaceId} and status = 'uploading' returning id`;
      return rows.length > 0;
    });
  },
};

export function getApiRepo(): ApiRepo {
  return isDemoMode() ? apiDemoRepo : apiPostgresRepo;
}

/* Nur für Skripte und Tests: rohe SQL-Verbindung (nicht in Routen verwenden) */
export function rawSql() {
  return getSql();
}
