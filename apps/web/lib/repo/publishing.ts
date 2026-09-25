import "server-only";
import { withAuthContext, withContext, type Tx } from "@/lib/db";
import { isDemoMode } from "@/lib/env";
import { currentSession } from "@/lib/session";
import { decryptCredentials, encryptCredentials } from "@/lib/publishing/crypto";
import { normalizeCapabilities } from "@/lib/publishing/capabilities";
import { PATTERN_ORDER } from "@/lib/clips/labels";
import type { Clip, HookPattern } from "@/lib/repo/types";
import type {
  CaptionPresetRow,
  ClipExtras,
  ClipWithExtras,
  Credentials,
  DecisionRow,
  Experiment,
  PerformanceFeedback,
  PlatformConnection,
  Publication,
  PublishingRepo,
  Series,
  WeeklyReport,
} from "@/lib/repo/types-publishing";
import { publishingDemoRepo } from "@/lib/repo/publishing-demo";

/* Publishing-Repository (Phase 5b): Verbindungen, Publikationen, Performance-Feedback, Decision Log, Experimente,
 * Serien, Wochenreports. Gleiche Muster wie lib/repo/postgres.ts (withContext mit RLS, explizite workspace_id-Filter).
 * Zusätzlich sitzungslose Lader für die interne Schnittstelle (Worker → /api/internal/*), siehe unten. */

type Row = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "string" ? Number(v) : (v as number);
  return Number.isFinite(n) ? n : null;
}

function iso(v: unknown): string | null {
  if (v == null) return null;
  return v instanceof Date ? v.toISOString() : String(v);
}

function json<T>(v: unknown, fallback: T): T {
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

export function toConnection(r: Row): PlatformConnection {
  const platform = r.platform as PlatformConnection["platform"];
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    brand_profile_name: (r.brand_profile_name as string | null) ?? null,
    platform,
    account_label: r.account_label as string,
    external_account_id: (r.external_account_id as string | null) ?? null,
    has_credentials: Boolean(r.credentials),
    capabilities: normalizeCapabilities(json(r.capabilities, {}), platform),
    status: r.status as PlatformConnection["status"],
    connected_by: (r.connected_by as string | null) ?? null,
    expires_at: iso(r.expires_at),
    created_at: iso(r.created_at) ?? "",
    updated_at: iso(r.updated_at) ?? "",
  };
}

export function toPublication(r: Row): Publication {
  return {
    id: r.id as string,
    workspace_id: (r.workspace_id as string | null) ?? null,
    clip_id: r.clip_id as string,
    connection_id: (r.connection_id as string | null) ?? null,
    platform: r.platform as string,
    status: r.status as Publication["status"],
    scheduled_for: iso(r.scheduled_for),
    caption: (r.caption as string | null) ?? null,
    title: (r.title as string | null) ?? null,
    external_id: (r.external_id as string | null) ?? null,
    external_url: (r.external_url as string | null) ?? null,
    error: (r.error as string | null) ?? null,
    published_at: iso(r.published_at),
    metrics: json<Publication["metrics"]>(r.metrics, {}) ?? {},
    metrics_fetched_at: iso(r.metrics_fetched_at),
    temporal_workflow_id: (r.temporal_workflow_id as string | null) ?? null,
    created_by: (r.created_by as string | null) ?? null,
    created_at: iso(r.created_at) ?? "",
  };
}

function toFeedback(r: Row): PerformanceFeedback {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    clip_id: (r.clip_id as string | null) ?? null,
    publication_id: (r.publication_id as string | null) ?? null,
    platform: r.platform as string,
    metric_window: r.metric_window as PerformanceFeedback["metric_window"],
    views: num(r.views),
    likes: num(r.likes),
    comments: num(r.comments),
    shares: num(r.shares),
    saves: num(r.saves),
    follows: num(r.follows),
    avg_watch_time_s: num(r.avg_watch_time_s),
    retention_curve: json<number[] | null>(r.retention_curve, null),
    follows_per_1k: num(r.follows_per_1k),
    saves_per_1k: num(r.saves_per_1k),
    account_median_views: num(r.account_median_views),
    outlier_score: num(r.outlier_score),
    reward: num(r.reward),
    fetched_at: iso(r.fetched_at) ?? "",
  };
}

function toDecision(r: Row): DecisionRow {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    source_id: (r.source_id as string | null) ?? null,
    candidate_id: (r.candidate_id as string | null) ?? null,
    clip_id: (r.clip_id as string | null) ?? null,
    decision_type: r.decision_type as DecisionRow["decision_type"],
    features: json<Record<string, unknown>>(r.features, {}),
    alternatives: json<unknown[]>(r.alternatives, []),
    chosen: json<Record<string, unknown>>(r.chosen, {}),
    actor_type: r.actor_type as DecisionRow["actor_type"],
    actor_id: (r.actor_id as string | null) ?? null,
    model_id: (r.model_id as string | null) ?? null,
    prompt_version: (r.prompt_version as string | null) ?? null,
    created_at: iso(r.created_at) ?? "",
  };
}

function toExperiment(r: Row): Experiment {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    candidate_id: (r.candidate_id as string | null) ?? null,
    hypothesis: (r.hypothesis as string | null) ?? null,
    status: r.status as Experiment["status"],
    winner_clip_id: (r.winner_clip_id as string | null) ?? null,
    min_exposure: num(r.min_exposure) ?? 1000,
    confidence: num(r.confidence),
    decided_at: iso(r.decided_at),
    created_by: (r.created_by as string | null) ?? null,
    created_at: iso(r.created_at) ?? "",
  };
}

function toSeries(r: Row): Series {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    brand_profile_name: (r.brand_profile_name as string | null) ?? null,
    name: r.name as string,
    description: (r.description as string | null) ?? null,
    cadence: r.cadence as Series["cadence"],
    rules: json<Series["rules"]>(r.rules, {}),
    active: Boolean(r.active),
    created_by: (r.created_by as string | null) ?? null,
    created_at: iso(r.created_at) ?? "",
    updated_at: iso(r.updated_at) ?? "",
    clip_count: num(r.clip_count) ?? undefined,
  };
}

function toReport(r: Row): WeeklyReport {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    week_start: iso(r.week_start)?.slice(0, 10) ?? "",
    report: json<WeeklyReport["report"]>(r.report, {}),
    sent_at: iso(r.sent_at),
    created_at: iso(r.created_at) ?? "",
  };
}

function toExtras(r: Row): ClipExtras {
  return {
    id: r.id as string,
    experiment_id: (r.experiment_id as string | null) ?? null,
    variant: (r.variant as ClipExtras["variant"]) ?? null,
    series_id: (r.series_id as string | null) ?? null,
    series_index: num(r.series_index),
    reframe_override: (r.reframe_override as ClipExtras["reframe_override"]) ?? null,
    caption_style: (r.caption_style as Record<string, unknown> | null) ?? {},
    zeitmarken: (r.zeitmarken as ClipExtras["zeitmarken"] | null) ?? [],
    /* Hier bleibt null stehen: der Unterschied zu einer leeren Liste ist der Punkt. */
    effekte: (r.effekte as ClipExtras["effekte"]) ?? null,
    musik: (r.musik as ClipExtras["musik"]) ?? null,
  };
}

function toCaptionPreset(r: Row): CaptionPresetRow {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    name: r.name as string,
    style: (r.style as Record<string, unknown> | null) ?? {},
    created_at: iso(r.created_at) ?? "",
    updated_at: iso(r.updated_at) ?? "",
  };
}

/* Clip-Zeile inklusive Zusatzspalten. Spiegel von toClip in lib/repo/postgres.ts (dort nicht exportiert). */
export function toClipWithExtras(r: Row): ClipWithExtras {
  const clip: Clip = {
    id: r.id as string,
    source_id: r.source_id as string,
    candidate_id: (r.candidate_id as string | null) ?? null,
    version: num(r.version) ?? 1,
    platform: r.platform as Clip["platform"],
    destination: (r.destination as Clip["destination"]) ?? null,
    aspect: r.aspect as Clip["aspect"],
    review: ((r.review as string | null) ?? "offen") as Clip["review"],
    composition: json<Clip["composition"]>(r.composition, []),
    kept_ranges: json<unknown>(r.kept_ranges, null),
    fidelity_warnings: json<unknown[]>(r.fidelity_warnings, []),
    speaker_positions: json<Clip["speaker_positions"]>(r.speaker_positions, null),
    render_plan: json<Clip["render_plan"]>(r.render_plan, null),
    title_card: (r.title_card as string | null) ?? null,
    ad_label: (r.ad_label as string | null) ?? null,
    ai_features: (r.ai_features as string[]) ?? [],
    guest_approval_required: Boolean(r.guest_approval_required),
    status: r.status as Clip["status"],
    file_key: (r.file_key as string | null) ?? null,
    srt_key: (r.srt_key as string | null) ?? null,
    vtt_key: (r.vtt_key as string | null) ?? null,
    poster_key: (r.poster_key as string | null) ?? null,
    filmstrip_key: (r.filmstrip_key as string | null) ?? null,
    filmstrip_meta: json<Clip["filmstrip_meta"]>(r.filmstrip_meta, null),
    zeitmarken: json<Clip["zeitmarken"]>(r.zeitmarken, []),
    cps_warnings: json<string[]>(r.cps_warnings, []),
    duration_s: num(r.duration_s),
    width: num(r.width),
    height: num(r.height),
    fps: num(r.fps),
    loudness: json<Clip["loudness"]>(r.loudness, null),
    provenance: json<Clip["provenance"]>(r.provenance, {}),
    render_error: (r.render_error as string | null) ?? null,
    rendered_at: iso(r.rendered_at),
    export_checks: json<Clip["export_checks"]>(r.export_checks, null),
    /* Eigene Löschfrist des Clips (Migration 0006): Renderings überleben ihre Quelle. */
    delete_after: iso(r.delete_after),
    deleted_at: iso(r.deleted_at),
    created_by: (r.created_by as string | null) ?? null,
    created_at: iso(r.created_at) ?? "",
    updated_at: iso(r.updated_at) ?? "",
  };
  return { ...clip, ...toExtras(r) };
}

function per1k(value: number | null, views: number | null): number | null {
  if (value == null || views == null || views <= 0) return null;
  return (value / views) * 1000;
}

const CONNECTION_SELECT = `select c.*, b.name as brand_profile_name from platform_connections c left join brand_profiles b on b.id = c.brand_profile_id`;

async function clipsByIds(tx: Tx, workspaceId: string, ids: string[]): Promise<ClipWithExtras[]> {
  if (ids.length === 0) return [];
  const rows = await tx`
    select c.* from clips c join sources s on s.id = c.source_id
    where c.id in ${tx(ids)} and s.workspace_id = ${workspaceId} and c.status <> 'deleted' order by c.created_at asc`;
  return rows.map((r) => toClipWithExtras(r as Row));
}

const postgresPublishingRepo: PublishingRepo = {
  kind: "postgres",

  async listConnections() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx.unsafe(`${CONNECTION_SELECT} where c.workspace_id = $1 order by c.created_at asc`, [session.workspaceId]);
      return rows.map((r) => toConnection(r as Row));
    });
  },

  async getConnection(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx.unsafe(`${CONNECTION_SELECT} where c.id = $1 and c.workspace_id = $2`, [id, session.workspaceId]);
      return rows.length ? toConnection(rows[0] as Row) : null;
    });
  },

  async createConnection(input) {
    const session = await currentSession();
    const stored = input.credentials ? encryptCredentials(input.credentials) : null;
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into platform_connections (workspace_id, brand_profile_id, platform, account_label, external_account_id, credentials, capabilities, status, connected_by, expires_at)
        values (${session.workspaceId}, ${input.brand_profile_id}, ${input.platform}, ${input.account_label}, ${input.external_account_id}, ${stored},
                ${tx.json(input.capabilities as never)}, 'connected', ${session.userId}, ${input.expires_at})
        returning *`;
      return toConnection(rows[0] as Row);
    });
  },

  async updateConnection(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      if ("brand_profile_id" in patch) data.brand_profile_id = patch.brand_profile_id ?? null;
      if (patch.status) data.status = patch.status;
      if (patch.account_label) data.account_label = patch.account_label;
      if (patch.status === "revoked") data.credentials = null;
      if (Object.keys(data).length === 0) return this.getConnection(id);
      const rows = await tx`update platform_connections set ${tx(data)} where id = ${id} and workspace_id = ${session.workspaceId} returning id`;
      if (!rows.length) return null;
      const out = await tx.unsafe(`${CONNECTION_SELECT} where c.id = $1`, [id]);
      return out.length ? toConnection(out[0] as Row) : null;
    });
  },

  async createPublication(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into publications (workspace_id, clip_id, connection_id, platform, status, scheduled_for, caption, title, external_url, published_at, created_by)
        values (${session.workspaceId}, ${input.clip_id}, ${input.connection_id}, ${input.platform}, ${input.status}, ${input.scheduled_for},
                ${input.caption}, ${input.title}, ${input.external_url ?? null}, ${input.published_at ?? null}, ${session.userId})
        returning *`;
      return toPublication(rows[0] as Row);
    });
  },

  async getPublication(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select p.* from publications p join clips c on c.id = p.clip_id join sources s on s.id = c.source_id
        where p.id = ${id} and s.workspace_id = ${session.workspaceId}`;
      return rows.length ? toPublication(rows[0] as Row) : null;
    });
  },

  async listPublicationsForClips(clipIds) {
    if (clipIds.length === 0) return [];
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select p.* from publications p join clips c on c.id = p.clip_id join sources s on s.id = c.source_id
        where p.clip_id in ${tx(clipIds)} and s.workspace_id = ${session.workspaceId} order by p.created_at desc`;
      return rows.map((r) => toPublication(r as Row));
    });
  },

  async updatePublication(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      for (const key of ["status", "scheduled_for", "external_url", "error", "temporal_workflow_id", "published_at"] as const) {
        if (key in patch) data[key] = patch[key] ?? null;
      }
      if (Object.keys(data).length === 0) return this.getPublication(id);
      const rows = await tx`
        update publications p set ${tx(data)} from clips c join sources s on s.id = c.source_id
        where p.id = ${id} and c.id = p.clip_id and s.workspace_id = ${session.workspaceId} returning p.*`;
      return rows.length ? toPublication(rows[0] as Row) : null;
    });
  },

  async listFeedbackForClips(clipIds) {
    if (clipIds.length === 0) return [];
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select * from performance_feedback where workspace_id = ${session.workspaceId} and clip_id in ${tx(clipIds)} order by fetched_at desc`;
      return rows.map((r) => toFeedback(r as Row));
    });
  },

  async upsertManualFeedback(publication, input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into performance_feedback (workspace_id, clip_id, publication_id, platform, metric_window, views, likes, comments, shares, saves, follows,
                                          avg_watch_time_s, follows_per_1k, saves_per_1k, fetched_at)
        values (${session.workspaceId}, ${publication.clip_id}, ${publication.id}, ${publication.platform}, 'manual', ${input.views}, ${input.likes},
                ${input.comments}, ${input.shares}, ${input.saves}, ${input.follows}, ${input.avg_watch_time_s},
                ${per1k(input.follows, input.views)}, ${per1k(input.saves, input.views)}, now())
        on conflict (publication_id, metric_window) do update set
          views = excluded.views, likes = excluded.likes, comments = excluded.comments, shares = excluded.shares, saves = excluded.saves,
          follows = excluded.follows, avg_watch_time_s = excluded.avg_watch_time_s, follows_per_1k = excluded.follows_per_1k,
          saves_per_1k = excluded.saves_per_1k, fetched_at = now()
        returning *`;
      await tx`update publications set metrics_fetched_at = now() where id = ${publication.id}`;
      return toFeedback(rows[0] as Row);
    });
  },

  async recordDecision(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into decision_log (workspace_id, brand_profile_id, source_id, candidate_id, clip_id, decision_type, features, alternatives, chosen,
                                  actor_type, actor_id, model_id, prompt_version)
        values (${session.workspaceId}, ${input.brand_profile_id ?? null}, ${input.source_id ?? null}, ${input.candidate_id ?? null}, ${input.clip_id ?? null},
                ${input.decision_type}, ${tx.json(input.features as never)}, ${tx.json((input.alternatives ?? []) as never)}, ${tx.json(input.chosen as never)},
                ${input.actor_type}, ${input.actor_type === "user" ? session.userId : null}, ${input.model_id ?? null}, ${input.prompt_version ?? null})
        returning *`;
      return toDecision(rows[0] as Row);
    });
  },

  async listHookPatternStats(brandProfileId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select h.* from hook_pattern_stats h join brand_profiles b on b.id = h.brand_profile_id
        where h.brand_profile_id = ${brandProfileId} and b.workspace_id = ${session.workspaceId}`;
      return rows
        .map((r) => r as Row)
        .filter((r) => (PATTERN_ORDER as string[]).includes(String(r.pattern)))
        .map((r) => ({
          pattern: r.pattern as HookPattern,
          shown: num(r.shown) ?? 0,
          chosen: num(r.chosen) ?? 0,
          reward_sum: num(r.reward_sum) ?? 0,
          reward_n: num(r.reward_n) ?? 0,
        }));
    });
  },

  async getClipExtras(clipIds) {
    if (clipIds.length === 0) return [];
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select c.id, c.experiment_id, c.variant, c.series_id, c.series_index, c.reframe_override, c.caption_style, c.zeitmarken, c.effekte, c.musik
        from clips c join sources s on s.id = c.source_id where c.id in ${tx(clipIds)} and s.workspace_id = ${session.workspaceId}`;
      return rows.map((r) => toExtras(r as Row));
    });
  },

  async updateClipExtras(clipId, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      for (const key of ["experiment_id", "variant", "series_id", "series_index", "reframe_override"] as const) {
        if (key in patch) data[key] = patch[key] ?? null;
      }
      /* jsonb braucht die ausdrueckliche Umwandlung, und null ist hier das leere Objekt: die Spalte
       * ist not null, und „nichts eingestellt" heisst {}, nicht fehlend. */
      if ("caption_style" in patch) data.caption_style = tx.json((patch.caption_style ?? {}) as never);
      /* Eine leere Liste ist eine Aussage: „ich will keine Effekte". Sie muss geschrieben werden,
       * sonst legt der naechste Renderlauf wieder automatische an. */
      if ("effekte" in patch) data.effekte = tx.json((patch.effekte ?? []) as never);
      if ("zeitmarken" in patch) data.zeitmarken = tx.json((patch.zeitmarken ?? []) as never);
      /* null heisst hier wirklich „keine Musik" und wird auch so geschrieben - anders als bei den
       * Effekten, wo null „noch nie gesetzt" bedeutet. */
      if ("musik" in patch) data.musik = patch.musik == null ? null : tx.json(patch.musik as never);
      if (Object.keys(data).length === 0) return (await this.getClipExtras([clipId]))[0] ?? null;
      const rows = await tx`
        update clips c set ${tx(data)} from sources s where c.id = ${clipId} and s.id = c.source_id and s.workspace_id = ${session.workspaceId}
        returning c.id, c.experiment_id, c.variant, c.series_id, c.series_index, c.reframe_override, c.caption_style, c.zeitmarken, c.effekte, c.musik`;
      return rows.length ? toExtras(rows[0] as Row) : null;
    });
  },

  async listCaptionPresets() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select id, workspace_id, name, style, created_at, updated_at from caption_presets
        where workspace_id = ${session.workspaceId} order by lower(name) asc`;
      return rows.map((r) => toCaptionPreset(r as Row));
    });
  },

  /* Gleicher Name heisst ueberschreiben, nicht ablehnen. Wer eine Vorlage nachschaerft, will sie
   * aktualisieren; zwei Eintraege „Podcast fett" waeren in der Auswahl nicht zu unterscheiden. */
  async saveCaptionPreset(name, style) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into caption_presets (workspace_id, name, style, created_by)
        values (${session.workspaceId}, ${name}, ${tx.json(style as never)}, ${session.userId})
        on conflict (workspace_id, lower(btrim(name)))
        do update set style = excluded.style, name = excluded.name
        returning id, workspace_id, name, style, created_at, updated_at`;
      return toCaptionPreset(rows[0] as Row);
    });
  },

  async deleteCaptionPreset(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`delete from caption_presets where id = ${id} and workspace_id = ${session.workspaceId} returning id`;
      return rows.length > 0;
    });
  },

  async createExperiment(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into experiments (workspace_id, candidate_id, hypothesis, status, created_by)
        values (${session.workspaceId}, ${input.candidate_id}, ${input.hypothesis}, 'draft', ${session.userId}) returning *`;
      return toExperiment(rows[0] as Row);
    });
  },

  async listExperiments() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from experiments where workspace_id = ${session.workspaceId} order by created_at desc`;
      return rows.map((r) => toExperiment(r as Row));
    });
  },

  async getExperiment(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from experiments where id = ${id} and workspace_id = ${session.workspaceId}`;
      return rows.length ? toExperiment(rows[0] as Row) : null;
    });
  },

  async updateExperiment(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      for (const key of ["status", "winner_clip_id", "confidence", "decided_at", "hypothesis"] as const) {
        if (key in patch) data[key] = patch[key] ?? null;
      }
      if (Object.keys(data).length === 0) return this.getExperiment(id);
      const rows = await tx`update experiments set ${tx(data)} where id = ${id} and workspace_id = ${session.workspaceId} returning *`;
      return rows.length ? toExperiment(rows[0] as Row) : null;
    });
  },

  async cloneClipForVariant(clipId, experimentId, hook) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const src = await clipsByIds(tx, session.workspaceId, [clipId]);
      const original = src[0];
      if (!original) throw new Error("Clip nicht gefunden");
      const rows = await tx`
        insert into clips (source_id, candidate_id, platform, destination, aspect, composition, title_card, ad_label, ai_features,
                           guest_approval_required, status, created_by, experiment_id, variant)
        values (${original.source_id}, ${original.candidate_id}, ${original.platform}, ${original.destination}, ${original.aspect},
                ${tx.json(original.composition as never)}, ${original.title_card}, ${original.ad_label}, ${original.ai_features},
                ${original.guest_approval_required}, 'draft', ${session.userId}, ${experimentId}, 'B')
        returning *`;
      const clone = toClipWithExtras(rows[0] as Row);
      await tx`update clips set experiment_id = ${experimentId}, variant = 'A' where id = ${clipId}`;
      /* Hook-Version 1 für B aus der gewählten Variante; Post-Captions und Varianten der aktuellen Version übernehmen */
      const prev = await tx`select * from hook_versions where clip_id = ${clipId} order by version desc limit 1`;
      const p = (prev[0] ?? {}) as Row;
      await tx`
        insert into hook_versions (clip_id, version, spoken_hook, onscreen_hook, pattern, variants, post_captions, cta, lint_notes, claim_issues, origin, created_by)
        values (${clone.id}, 1, ${hook.spoken}, ${hook.onscreen}, ${hook.pattern}, ${tx.json(json(p.variants, []) as never)},
                ${tx.json(json(p.post_captions, {}) as never)}, ${(p.cta as string | null) ?? null}, '[]'::jsonb, '[]'::jsonb, 'manual', ${session.userId})`;
      return clone;
    });
  },

  async listClipsByIds(clipIds) {
    const session = await currentSession();
    return withContext(session, async (tx) => clipsByIds(tx, session.workspaceId, clipIds));
  },

  async listClipsForExperiment(experimentId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select c.* from clips c join sources s on s.id = c.source_id
        where c.experiment_id = ${experimentId} and s.workspace_id = ${session.workspaceId} and c.status <> 'deleted' order by c.variant asc nulls last`;
      return rows.map((r) => toClipWithExtras(r as Row));
    });
  },

  async listSeries() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select s.*, b.name as brand_profile_name, (select count(*) from clips c where c.series_id = s.id and c.status <> 'deleted')::int as clip_count
        from series s left join brand_profiles b on b.id = s.brand_profile_id where s.workspace_id = ${session.workspaceId} order by s.created_at desc`;
      return rows.map((r) => toSeries(r as Row));
    });
  },

  async getSeries(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select s.*, b.name as brand_profile_name, (select count(*) from clips c where c.series_id = s.id and c.status <> 'deleted')::int as clip_count
        from series s left join brand_profiles b on b.id = s.brand_profile_id where s.id = ${id} and s.workspace_id = ${session.workspaceId}`;
      return rows.length ? toSeries(rows[0] as Row) : null;
    });
  },

  async createSeries(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into series (workspace_id, brand_profile_id, name, description, cadence, rules, created_by)
        values (${session.workspaceId}, ${input.brand_profile_id}, ${input.name}, ${input.description}, ${input.cadence}, ${tx.json(input.rules as never)}, ${session.userId})
        returning *`;
      return toSeries(rows[0] as Row);
    });
  },

  async updateSeries(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      if (patch.name) data.name = patch.name;
      if ("description" in patch) data.description = patch.description ?? null;
      if ("brand_profile_id" in patch) data.brand_profile_id = patch.brand_profile_id ?? null;
      if (patch.cadence) data.cadence = patch.cadence;
      if (patch.rules) data.rules = tx.json(patch.rules as never);
      if (typeof patch.active === "boolean") data.active = patch.active;
      if (Object.keys(data).length === 0) return this.getSeries(id);
      const rows = await tx`update series set ${tx(data)} where id = ${id} and workspace_id = ${session.workspaceId} returning id`;
      if (!rows.length) return null;
      return this.getSeries(id);
    });
  },

  async listSeriesClips(seriesId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select c.* from clips c join sources s on s.id = c.source_id join series se on se.id = c.series_id
        where c.series_id = ${seriesId} and se.workspace_id = ${session.workspaceId} and c.status <> 'deleted'
        order by c.series_index asc nulls last, c.updated_at asc`;
      return rows.map((r) => toClipWithExtras(r as Row));
    });
  },

  async listZuordenbareClips(seriesId, limit = 50) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select c.* from clips c
        join sources s on s.id = c.source_id
        join series se on se.id = ${seriesId}
        where s.workspace_id = ${session.workspaceId}
          and c.status in ('rendered', 'exported')
          and c.review <> 'verworfen'
          and (c.series_id is null or c.series_id <> ${seriesId})
          and (se.brand_profile_id is null or s.brand_profile_id = se.brand_profile_id)
        order by c.updated_at desc
        limit ${limit}`;
      return rows.map((r) => toClipWithExtras(r as Row));
    });
  },

  async listWeeklyReports() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from weekly_reports where workspace_id = ${session.workspaceId} order by week_start desc limit 26`;
      return rows.map((r) => toReport(r as Row));
    });
  },

  async setWeeklyReportEnabled(enabled) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`update workspaces set weekly_report_enabled = ${enabled} where id = ${session.workspaceId} returning weekly_report_enabled`;
      return rows.length ? Boolean((rows[0] as Row).weekly_report_enabled) : enabled;
    });
  },

  async getWeeklyReportEnabled() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select weekly_report_enabled from workspaces where id = ${session.workspaceId}`;
      return rows.length ? Boolean((rows[0] as Row).weekly_report_enabled) : true;
    });
  },
};

export function getPublishingRepo(): PublishingRepo {
  return isDemoMode() ? publishingDemoRepo : postgresPublishingRepo;
}

/* ------------------------------------------------------------------------------------------------
 * Sitzungslose Lader für die interne Schnittstelle (Worker → /api/internal/publish und /metrics).
 * Laufen über die Auth-Verbindung (BYPASSRLS), weil kein Nutzer beteiligt ist. Zugangsdaten werden hier entschlüsselt
 * und nie geloggt.
 * ---------------------------------------------------------------------------------------------- */

export interface InternalPublicationContext {
  publication: Publication;
  connection: PlatformConnection | null;
  credentials: Credentials | null;
  clip: ClipWithExtras;
  brand_profile_id: string | null;
}

export async function loadPublicationInternal(publicationId: string): Promise<InternalPublicationContext | null> {
  if (isDemoMode()) return publishingDemoRepo.loadInternal(publicationId);
  return withAuthContext(async (tx) => {
    const pubRows = await tx`select * from publications where id = ${publicationId}`;
    if (!pubRows.length) return null;
    const publication = toPublication(pubRows[0] as Row);
    const clipRows = await tx`select * from clips where id = ${publication.clip_id}`;
    if (!clipRows.length) return null;
    const clip = toClipWithExtras(clipRows[0] as Row);
    const srcRows = await tx`select brand_profile_id from sources where id = ${clip.source_id}`;
    const brandId = srcRows.length ? ((srcRows[0] as Row).brand_profile_id as string | null) : null;
    let connection: PlatformConnection | null = null;
    let credentials: Credentials | null = null;
    if (publication.connection_id) {
      const connRows = await tx.unsafe(`${CONNECTION_SELECT} where c.id = $1`, [publication.connection_id]);
      if (connRows.length) {
        connection = toConnection(connRows[0] as Row);
        credentials = decryptCredentials((connRows[0] as Row).credentials as string | null);
      }
    }
    return { publication, connection, credentials, clip, brand_profile_id: brandId };
  });
}

/* Nach einem Token-Refresh: neue Zugangsdaten verschlüsselt speichern (sitzungslos) */
export async function storeCredentialsInternal(connectionId: string, creds: Credentials, expiresAt: string | null, status: "connected" | "expired" = "connected"): Promise<void> {
  if (isDemoMode()) return publishingDemoRepo.storeCredentialsInternal(connectionId, creds, expiresAt, status);
  const stored = encryptCredentials(creds);
  await withAuthContext(async (tx) => {
    await tx`update platform_connections set credentials = ${stored}, expires_at = ${expiresAt}, status = ${status} where id = ${connectionId}`;
  });
}

export async function markConnectionStatusInternal(connectionId: string, status: "connected" | "expired" | "revoked"): Promise<void> {
  if (isDemoMode()) return publishingDemoRepo.storeCredentialsInternal(connectionId, null, null, status);
  await withAuthContext(async (tx) => {
    await tx`update platform_connections set status = ${status} where id = ${connectionId}`;
  });
}
