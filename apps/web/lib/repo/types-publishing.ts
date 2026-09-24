import type { HookPattern, Platform, CaptionPreset, CandidateStructure, Clip } from "@/lib/repo/types";

/* Datentypen Phase 5b: Spiegel von packages/schema/migrations/0005_phase5.sql (Publishing, Decision Log,
 * Performance-Feedback, Experimente, Serien, Wochenreports). lib/repo/types.ts bleibt unverändert. */

export type ConnectionPlatform = "tiktok" | "instagram" | "youtube" | "linkedin" | "manual";
export type ConnectionStatus = "connected" | "expired" | "revoked";
export type CapabilityValue = true | false | "conditional" | "unknown";
export type CapabilityKey =
  | "views"
  | "likes"
  | "comments"
  | "shares"
  | "saves"
  | "avg_watch_time"
  | "retention_curve"
  | "follow_attribution"
  | "publish"
  | "schedule";
export type Capabilities = Record<CapabilityKey, CapabilityValue>;

export interface PlatformConnection {
  id: string;
  workspace_id: string;
  brand_profile_id: string | null;
  brand_profile_name?: string | null;
  platform: ConnectionPlatform;
  account_label: string;
  external_account_id: string | null;
  /* nie im Klartext an den Client: nur Flag, ob Zugangsdaten hinterlegt sind */
  has_credentials: boolean;
  capabilities: Capabilities;
  status: ConnectionStatus;
  connected_by: string | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

/* Zugangsdaten je Provider (verschlüsselt in platform_connections.credentials) */
export interface Credentials {
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_at?: string | null;
  scope?: string;
  open_id?: string;
  ig_user_id?: string;
  page_id?: string;
  channel_id?: string;
  person_urn?: string;
  [key: string]: unknown;
}

export interface ConnectionInput {
  platform: ConnectionPlatform;
  account_label: string;
  external_account_id: string | null;
  credentials: Credentials | null;
  capabilities: Capabilities;
  brand_profile_id: string | null;
  expires_at: string | null;
}

export type PublicationStatus = "scheduled" | "publishing" | "published" | "failed" | "manual";
export type MetricWindow = "6h" | "48h" | "7d" | "manual";

export interface MetricSet {
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  follows: number | null;
  avg_watch_time_s: number | null;
  retention_curve: number[] | null;
}

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
  metrics: Partial<Record<"at_6h" | "at_48h" | "at_7d", MetricSet | null>>;
  metrics_fetched_at: string | null;
  temporal_workflow_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface PublicationInput {
  clip_id: string;
  connection_id: string | null;
  platform: string;
  status: PublicationStatus;
  scheduled_for: string | null;
  caption: string | null;
  title: string | null;
  external_url?: string | null;
  published_at?: string | null;
}

export interface PerformanceFeedback {
  id: string;
  workspace_id: string;
  clip_id: string | null;
  publication_id: string | null;
  platform: string;
  metric_window: MetricWindow;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  follows: number | null;
  avg_watch_time_s: number | null;
  retention_curve: number[] | null;
  follows_per_1k: number | null;
  saves_per_1k: number | null;
  account_median_views: number | null;
  outlier_score: number | null;
  reward: number | null;
  fetched_at: string;
}

export interface ManualMetricsInput {
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  follows: number | null;
  avg_watch_time_s: number | null;
}

export type DecisionType =
  | "candidate_proposed"
  | "candidate_scored"
  | "candidate_verdict"
  | "hook_selected"
  | "hook_variant_shown"
  | "caption_preset"
  | "reframe_strategy"
  | "publish";

export interface DecisionInput {
  decision_type: DecisionType;
  features: Record<string, unknown>;
  alternatives?: unknown[];
  chosen: Record<string, unknown>;
  actor_type: "ai" | "user" | "system";
  brand_profile_id?: string | null;
  source_id?: string | null;
  candidate_id?: string | null;
  clip_id?: string | null;
  model_id?: string | null;
  prompt_version?: string | null;
}

export interface DecisionRow extends DecisionInput {
  id: string;
  workspace_id: string;
  actor_id: string | null;
  created_at: string;
}

export interface HookPatternStat {
  pattern: HookPattern;
  shown: number;
  chosen: number;
  reward_sum: number;
  reward_n: number;
}

export type ExperimentStatus = "draft" | "running" | "decided";

export interface Experiment {
  id: string;
  workspace_id: string;
  candidate_id: string | null;
  hypothesis: string | null;
  status: ExperimentStatus;
  winner_clip_id: string | null;
  min_exposure: number;
  confidence: number | null;
  decided_at: string | null;
  created_by: string | null;
  created_at: string;
}

export type SeriesCadence = "weekly" | "biweekly" | "monthly" | "none";

export interface SeriesRules {
  structure?: CandidateStructure | null;
  platforms?: Platform[];
  caption_preset?: CaptionPreset | null;
  hook_patterns?: HookPattern[];
  cover_template?: string | null;
}

export interface Series {
  id: string;
  workspace_id: string;
  brand_profile_id: string | null;
  brand_profile_name?: string | null;
  name: string;
  description: string | null;
  cadence: SeriesCadence;
  rules: SeriesRules;
  active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  clip_count?: number;
}

export interface SeriesInput {
  name: string;
  description: string | null;
  brand_profile_id: string | null;
  cadence: SeriesCadence;
  rules: SeriesRules;
}

/* Zusätzliche Clip-Spalten aus Migration 0005 (types.ts kennt sie nicht) */
export type ReframeOverride = "talking_head" | "two_speakers" | "neutral" | "slide_pip";

export interface ClipExtras {
  id: string;
  experiment_id: string | null;
  variant: "A" | "B" | null;
  series_id: string | null;
  series_index: number | null;
  reframe_override: ReframeOverride | null;
  /* Untertitel-Stil dieses Clips (Migration 0008). Leeres Objekt heisst: nichts eingestellt, es
   * gilt das Markenprofil und was das Format vorgibt. Form siehe lib/clips/caption-style.ts. */
  caption_style: Record<string, unknown>;
  /* Entscheidungen aus der Zeitleiste (Migration 0009). */
  zeitmarken: { ab_s: number; x?: number; zoom?: number; layout?: "einzel" | "geteilt" }[];
}

/* Gespeicherte Untertitel-Vorlage. Gehoert dem Workspace, nicht der Person: in einer Agentur stellt
 * einer den Stil ein und alle arbeiten damit weiter. */
export interface CaptionPresetRow {
  id: string;
  workspace_id: string;
  name: string;
  style: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type ClipWithExtras = Clip & ClipExtras;

/* Wochenreport (WeeklyReportWorkflow im Worker), Inhalt nach PHASE5.md */
export interface WeeklyReportClipEntry {
  clip_id: string;
  title?: string | null;
  platform?: string | null;
  follows_per_1k?: number | null;
  views?: number | null;
  cause?: string | null;
  change?: string | null;
}

export interface WeeklyReportBody {
  best?: WeeklyReportClipEntry[];
  worst?: WeeklyReportClipEntry[];
  publications?: number;
  summary?: string | null;
  [key: string]: unknown;
}

export interface WeeklyReport {
  id: string;
  workspace_id: string;
  week_start: string;
  report: WeeklyReportBody;
  sent_at: string | null;
  created_at: string;
}

/* Publishing-Repository (lib/repo/publishing.ts, Demo: lib/repo/publishing-demo.ts) */
export interface PublishingRepo {
  readonly kind: "postgres" | "demo";
  /* Verbindungen */
  listConnections(): Promise<PlatformConnection[]>;
  getConnection(id: string): Promise<PlatformConnection | null>;
  createConnection(input: ConnectionInput): Promise<PlatformConnection>;
  updateConnection(id: string, patch: { brand_profile_id?: string | null; status?: ConnectionStatus; account_label?: string }): Promise<PlatformConnection | null>;
  /* Publikationen */
  createPublication(input: PublicationInput): Promise<Publication>;
  getPublication(id: string): Promise<Publication | null>;
  listPublicationsForClips(clipIds: string[]): Promise<Publication[]>;
  updatePublication(id: string, patch: Partial<Pick<Publication, "status" | "scheduled_for" | "external_url" | "error" | "temporal_workflow_id" | "published_at">>): Promise<Publication | null>;
  listFeedbackForClips(clipIds: string[]): Promise<PerformanceFeedback[]>;
  upsertManualFeedback(publication: Publication, input: ManualMetricsInput): Promise<PerformanceFeedback>;
  /* Decision Log und Lernschleife */
  recordDecision(input: DecisionInput): Promise<DecisionRow>;
  listHookPatternStats(brandProfileId: string): Promise<HookPatternStat[]>;
  /* Clip-Zusatzspalten */
  getClipExtras(clipIds: string[]): Promise<ClipExtras[]>;
  updateClipExtras(clipId: string, patch: Partial<Omit<ClipExtras, "id">>): Promise<ClipExtras | null>;
  /* Untertitel-Vorlagen des Workspace */
  listCaptionPresets(): Promise<CaptionPresetRow[]>;
  saveCaptionPreset(name: string, style: Record<string, unknown>): Promise<CaptionPresetRow>;
  deleteCaptionPreset(id: string): Promise<boolean>;
  /* Experimente */
  createExperiment(input: { candidate_id: string | null; hypothesis: string | null }): Promise<Experiment>;
  listExperiments(): Promise<Experiment[]>;
  getExperiment(id: string): Promise<Experiment | null>;
  updateExperiment(id: string, patch: Partial<Pick<Experiment, "status" | "winner_clip_id" | "confidence" | "decided_at" | "hypothesis">>): Promise<Experiment | null>;
  /* Klon des Clips für Variante B: gleiche Komposition, Plattform, Aspekt, Kandidat; status draft */
  cloneClipForVariant(clipId: string, experimentId: string, hook: { spoken: string; onscreen: string; pattern: HookPattern | null }): Promise<ClipWithExtras>;
  listClipsByIds(clipIds: string[]): Promise<ClipWithExtras[]>;
  listClipsForExperiment(experimentId: string): Promise<ClipWithExtras[]>;
  /* Serien */
  listSeries(): Promise<Series[]>;
  getSeries(id: string): Promise<Series | null>;
  createSeries(input: SeriesInput): Promise<Series>;
  updateSeries(id: string, patch: Partial<SeriesInput> & { active?: boolean }): Promise<Series | null>;
  listSeriesClips(seriesId: string): Promise<ClipWithExtras[]>;
  /* Gebaute Clips, die dieser Serie noch nicht zugeordnet sind. Für das Zuordnen aus der
   * Serienansicht heraus; ohne das ginge es nur über die Clip-Karte, also nur, wenn man weiss,
   * in welchem Projekt der Clip liegt. Gehört die Serie zu einer Marke, kommen auch nur deren
   * Clips infrage: sonst landete ein Kundenclip in der Serie eines anderen Kunden. */
  listZuordenbareClips(seriesId: string, limit?: number): Promise<ClipWithExtras[]>;
  /* Berichte */
  listWeeklyReports(): Promise<WeeklyReport[]>;
  setWeeklyReportEnabled(enabled: boolean): Promise<boolean>;
  getWeeklyReportEnabled(): Promise<boolean>;
}
