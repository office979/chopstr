import { randomUUID } from "node:crypto";
import { currentSession } from "@/lib/session";
import { demoRepo } from "@/lib/repo/demo";
import type { Clip } from "@/lib/repo/types";
import type {
  CaptionPresetRow,
  ClipExtras,
  ClipWithExtras,
  ConnectionStatus,
  Credentials,
  DecisionRow,
  Experiment,
  HookPatternStat,
  PerformanceFeedback,
  PlatformConnection,
  Publication,
  PublishingRepo,
  Series,
  WeeklyReport,
} from "@/lib/repo/types-publishing";

/* In-Memory-Publishing für den Demo-Modus (ohne DATABASE_URL). Überlebt Hot Reloads über globalThis.
 * Clips kommen aus lib/repo/demo.ts; die Zusatzspalten aus Migration 0005 liegen hier in `extras`. */

interface DemoPublishingState {
  connections: (PlatformConnection & { credentials: Credentials | null })[];
  publications: Publication[];
  feedback: PerformanceFeedback[];
  decisions: DecisionRow[];
  experiments: Experiment[];
  series: Series[];
  extras: Map<string, ClipExtras>;
  captionPresets: CaptionPresetRow[];
  clones: Clip[];
  reports: WeeklyReport[];
  weeklyReportEnabled: boolean;
}

declare global {
  var __chopstrDemoPublishing: DemoPublishingState | undefined;
}

function state(): DemoPublishingState {
  if (!globalThis.__chopstrDemoPublishing) {
    globalThis.__chopstrDemoPublishing = {
      connections: [],
      publications: [],
      feedback: [],
      decisions: [],
      experiments: [],
      series: [],
      extras: new Map(),
      captionPresets: [],
      clones: [],
      reports: [],
      weeklyReportEnabled: true,
    };
  }
  return globalThis.__chopstrDemoPublishing;
}

function now(): string {
  return new Date().toISOString();
}

function extrasOf(id: string): ClipExtras {
  const s = state();
  const found = s.extras.get(id);
  if (found) return found;
  const fresh: ClipExtras = { id, experiment_id: null, variant: null, series_id: null, series_index: null, reframe_override: null, caption_style: {}, zeitmarken: [] };
  s.extras.set(id, fresh);
  return fresh;
}

async function clipById(id: string): Promise<ClipWithExtras | null> {
  const clone = state().clones.find((c) => c.id === id);
  const clip = clone ?? (await demoRepo.getClip(id));
  return clip ? { ...clip, ...extrasOf(id) } : null;
}

function per1k(value: number | null, views: number | null): number | null {
  if (value == null || views == null || views <= 0) return null;
  return (value / views) * 1000;
}

function strip(c: PlatformConnection & { credentials: Credentials | null }): PlatformConnection {
  const { credentials, ...rest } = c;
  return { ...rest, has_credentials: credentials != null };
}

export const publishingDemoRepo: PublishingRepo & {
  loadInternal(publicationId: string): Promise<import("@/lib/repo/publishing").InternalPublicationContext | null>;
  storeCredentialsInternal(connectionId: string, creds: Credentials | null, expiresAt: string | null, status: ConnectionStatus): Promise<void>;
} = {
  kind: "demo",

  async listConnections() {
    return state().connections.map(strip);
  },
  async getConnection(id) {
    const c = state().connections.find((x) => x.id === id);
    return c ? strip(c) : null;
  },
  async createConnection(input) {
    const session = await currentSession();
    const brand = input.brand_profile_id ? await demoRepo.getBrandProfile(input.brand_profile_id) : null;
    const row = {
      id: randomUUID(),
      workspace_id: session.workspaceId,
      brand_profile_id: input.brand_profile_id,
      brand_profile_name: brand?.name ?? null,
      platform: input.platform,
      account_label: input.account_label,
      external_account_id: input.external_account_id,
      has_credentials: input.credentials != null,
      credentials: input.credentials,
      capabilities: input.capabilities,
      status: "connected" as const,
      connected_by: session.userId,
      expires_at: input.expires_at,
      created_at: now(),
      updated_at: now(),
    };
    state().connections.push(row);
    return strip(row);
  },
  async updateConnection(id, patch) {
    const c = state().connections.find((x) => x.id === id);
    if (!c) return null;
    if ("brand_profile_id" in patch) {
      c.brand_profile_id = patch.brand_profile_id ?? null;
      c.brand_profile_name = c.brand_profile_id ? ((await demoRepo.getBrandProfile(c.brand_profile_id))?.name ?? null) : null;
    }
    if (patch.status) c.status = patch.status;
    if (patch.status === "revoked") c.credentials = null;
    if (patch.account_label) c.account_label = patch.account_label;
    c.updated_at = now();
    return strip(c);
  },

  async createPublication(input) {
    const session = await currentSession();
    const row: Publication = {
      id: randomUUID(),
      workspace_id: session.workspaceId,
      clip_id: input.clip_id,
      connection_id: input.connection_id,
      platform: input.platform,
      status: input.status,
      scheduled_for: input.scheduled_for,
      caption: input.caption,
      title: input.title,
      external_id: null,
      external_url: input.external_url ?? null,
      error: null,
      published_at: input.published_at ?? null,
      metrics: {},
      metrics_fetched_at: null,
      temporal_workflow_id: null,
      created_by: session.userId,
      created_at: now(),
    };
    state().publications.unshift(row);
    return row;
  },
  async getPublication(id) {
    return state().publications.find((p) => p.id === id) ?? null;
  },
  async listPublicationsForClips(clipIds) {
    return state().publications.filter((p) => clipIds.includes(p.clip_id));
  },
  async updatePublication(id, patch) {
    const p = state().publications.find((x) => x.id === id);
    if (!p) return null;
    Object.assign(p, patch);
    return p;
  },
  async listFeedbackForClips(clipIds) {
    return state().feedback.filter((f) => f.clip_id && clipIds.includes(f.clip_id));
  },
  async upsertManualFeedback(publication, input) {
    const session = await currentSession();
    const s = state();
    const existing = s.feedback.find((f) => f.publication_id === publication.id && f.metric_window === "manual");
    const row: PerformanceFeedback = {
      id: existing?.id ?? randomUUID(),
      workspace_id: session.workspaceId,
      clip_id: publication.clip_id,
      publication_id: publication.id,
      platform: publication.platform,
      metric_window: "manual",
      ...input,
      retention_curve: null,
      follows_per_1k: per1k(input.follows, input.views),
      saves_per_1k: per1k(input.saves, input.views),
      account_median_views: null,
      outlier_score: null,
      reward: null,
      fetched_at: now(),
    };
    if (existing) Object.assign(existing, row);
    else s.feedback.push(row);
    publication.metrics_fetched_at = now();
    return row;
  },

  async recordDecision(input) {
    const session = await currentSession();
    const row: DecisionRow = {
      id: randomUUID(),
      workspace_id: session.workspaceId,
      actor_id: input.actor_type === "user" ? session.userId : null,
      created_at: now(),
      ...input,
      alternatives: input.alternatives ?? [],
    };
    state().decisions.push(row);
    return row;
  },
  async listHookPatternStats(): Promise<HookPatternStat[]> {
    return [];
  },

  async getClipExtras(clipIds) {
    return clipIds.map(extrasOf);
  },
  async updateClipExtras(clipId, patch) {
    const e = extrasOf(clipId);
    Object.assign(e, patch);
    return e;
  },

  async listCaptionPresets() {
    return [...state().captionPresets].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  },
  async saveCaptionPreset(name, style) {
    const vorhanden = state().captionPresets.find((p) => p.name.trim().toLowerCase() === name.trim().toLowerCase());
    if (vorhanden) {
      vorhanden.style = style;
      vorhanden.name = name;
      vorhanden.updated_at = now();
      return vorhanden;
    }
    const row: CaptionPresetRow = {
      id: randomUUID(),
      workspace_id: (await currentSession()).workspaceId,
      name,
      style,
      created_at: now(),
      updated_at: now(),
    };
    state().captionPresets.unshift(row);
    return row;
  },
  async deleteCaptionPreset(id) {
    const i = state().captionPresets.findIndex((p) => p.id === id);
    if (i < 0) return false;
    state().captionPresets.splice(i, 1);
    return true;
  },

  async createExperiment(input) {
    const session = await currentSession();
    const row: Experiment = {
      id: randomUUID(),
      workspace_id: session.workspaceId,
      candidate_id: input.candidate_id,
      hypothesis: input.hypothesis,
      status: "draft",
      winner_clip_id: null,
      min_exposure: 1000,
      confidence: null,
      decided_at: null,
      created_by: session.userId,
      created_at: now(),
    };
    state().experiments.unshift(row);
    return row;
  },
  async listExperiments() {
    return state().experiments;
  },
  async getExperiment(id) {
    return state().experiments.find((e) => e.id === id) ?? null;
  },
  async updateExperiment(id, patch) {
    const e = state().experiments.find((x) => x.id === id);
    if (!e) return null;
    Object.assign(e, patch);
    return e;
  },
  async cloneClipForVariant(clipId, experimentId) {
    const session = await currentSession();
    const original = await clipById(clipId);
    if (!original) throw new Error("Clip nicht gefunden");
    const clone: Clip = {
      ...original,
      id: randomUUID(),
      version: 1,
      status: "draft",
      file_key: null,
      srt_key: null,
      vtt_key: null,
      poster_key: null,
      render_plan: null,
      rendered_at: null,
      render_error: null,
      created_by: session.userId,
      created_at: now(),
      updated_at: now(),
    };
    state().clones.push(clone);
    extrasOf(clipId).experiment_id = experimentId;
    extrasOf(clipId).variant = "A";
    const e = extrasOf(clone.id);
    e.experiment_id = experimentId;
    e.variant = "B";
    return { ...clone, ...e };
  },
  async listClipsByIds(clipIds) {
    const out: ClipWithExtras[] = [];
    for (const id of clipIds) {
      const c = await clipById(id);
      if (c) out.push(c);
    }
    return out;
  },
  async listClipsForExperiment(experimentId) {
    const ids = [...state().extras.values()].filter((e) => e.experiment_id === experimentId).map((e) => e.id);
    const list = await this.listClipsByIds(ids);
    return list.sort((a, b) => (a.variant ?? "Z").localeCompare(b.variant ?? "Z"));
  },

  async listSeries() {
    const s = state();
    return s.series.map((x) => ({ ...x, clip_count: [...s.extras.values()].filter((e) => e.series_id === x.id).length }));
  },
  async getSeries(id) {
    return (await this.listSeries()).find((x) => x.id === id) ?? null;
  },
  async createSeries(input) {
    const session = await currentSession();
    const brand = input.brand_profile_id ? await demoRepo.getBrandProfile(input.brand_profile_id) : null;
    const row: Series = {
      id: randomUUID(),
      workspace_id: session.workspaceId,
      brand_profile_id: input.brand_profile_id,
      brand_profile_name: brand?.name ?? null,
      name: input.name,
      description: input.description,
      cadence: input.cadence,
      rules: input.rules,
      active: true,
      created_by: session.userId,
      created_at: now(),
      updated_at: now(),
      clip_count: 0,
    };
    state().series.unshift(row);
    return row;
  },
  async updateSeries(id, patch) {
    const s = state().series.find((x) => x.id === id);
    if (!s) return null;
    Object.assign(s, patch, { updated_at: now() });
    return this.getSeries(id);
  },
  async listSeriesClips(seriesId) {
    const ids = [...state().extras.values()]
      .filter((e) => e.series_id === seriesId)
      .sort((a, b) => (a.series_index ?? 0) - (b.series_index ?? 0))
      .map((e) => e.id);
    return this.listClipsByIds(ids);
  },

  async listWeeklyReports() {
    return state().reports;
  },
  async setWeeklyReportEnabled(enabled) {
    state().weeklyReportEnabled = enabled;
    return enabled;
  },
  async getWeeklyReportEnabled() {
    return state().weeklyReportEnabled;
  },

  async loadInternal(publicationId) {
    const publication = state().publications.find((p) => p.id === publicationId);
    if (!publication) return null;
    const clip = await clipById(publication.clip_id);
    if (!clip) return null;
    const conn = publication.connection_id ? state().connections.find((c) => c.id === publication.connection_id) : null;
    const source = await demoRepo.getSource(clip.source_id);
    return { publication, connection: conn ? strip(conn) : null, credentials: conn?.credentials ?? null, clip, brand_profile_id: source?.brand_profile_id ?? null };
  },
  async storeCredentialsInternal(connectionId, creds, expiresAt, status) {
    const c = state().connections.find((x) => x.id === connectionId);
    if (!c) return;
    if (creds) c.credentials = creds;
    if (expiresAt !== null || creds) c.expires_at = expiresAt;
    c.status = status;
  },
};
