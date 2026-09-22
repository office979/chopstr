import type { Role } from "@/lib/auth/permissions";
export type { Role };

/* Datentypen: Spiegel der Tabellen aus packages/schema/migrations/0001_init.sql */

export type SourceStatus =
  | "uploading"
  | "uploaded"
  | "ingesting"
  | "transcribing"
  | "analyzing"
  | "scoring"
  | "ready"
  | "failed"
  | "deleted";

export type RightsStatus = "own" | "licensed" | "third_party";
export type Platform = "tiktok" | "reels" | "shorts" | "linkedin";
export type Address = "du" | "sie";
export type Country = "DE" | "AT" | "CH";
export type GenderMode = "neutral" | "paarform" | "doppelpunkt" | "stern" | "keine";
export type AsrVariant = "de" | "de-CH";
/* Die *_words-Presets zeigen ein Wort je Einblendung (Karaoke-Stil) und sind der Standard der
 * Kurzformate. Spiegel von PRESETS in workers/chopstr_worker/pipeline/captions_de.py. */
export type CaptionPreset =
  | "tiktok_bold"
  | "reels_clean"
  | "shorts_clean"
  | "tiktok_words"
  | "reels_words"
  | "shorts_words"
  | "linkedin_static"
  | "corporate_third";

export type PipelineStep =
  | "probe_and_extract"
  | "transcribe_de"
  | "diarize"
  | "heatmap"
  | "fuse_and_nlp"
  | "detect_candidates"
  | "render";

export type PipelineEventStatus = "started" | "progress" | "finished" | "failed" | "skipped";

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  plan: string;
  tier: "standard" | "sovereign";
  data_region: string;
  retention_days: number;
  render_retention_days: number;
  allow_us_subprocessors: boolean;
  training_opt_in: boolean;
  dpa_signed_at: string | null;
  /* Workspace-Löschung (Phase 4, Block B): Anfrage und Ausführung nach 30 Tagen Karenz */
  deletion_requested_at: string | null;
  deletion_scheduled_for: string | null;
  created_at: string;
}

export interface BrandProfile {
  id: string;
  workspace_id: string;
  name: string;
  version: number;
  address: Address;
  country: Country;
  gender_mode: GenderMode;
  asr_variant: AsrVariant;
  brand_vocab: string[];
  protected_terms: string[];
  banned_phrases: string[];
  tone_adjectives: string[];
  default_platform: Platform;
  caption_preset: CaptionPreset;
  /* CI (jsonb): Farben, Fonts, Logo, Bauchbinde */
  ci: BrandCI;
  /* Caption-Stil (jsonb): Highlight-Farbe, Hook-Overlay je Plattform */
  caption_style: CaptionStyle;
  created_at: string;
  updated_at: string;
}

/* CI (PHASE4.md, Abschnitt 8): Fonts, Logo und Wasserzeichen verweisen auf brand_assets.id; der Worker liest
 * fonts.primary_asset_id, secondary_asset_id, logo_asset_id und watermark.enabled. */
export interface BrandCI {
  colors?: { primary?: string; secondary?: string; accent?: string };
  fonts?: {
    primary_asset_id?: string | null;
    secondary_asset_id?: string | null;
    fallback?: string;
    /* Phase 3 (veraltet, bleibt lesbar) */
    primary_key?: string | null;
    secondary_key?: string | null;
  };
  logo_asset_id?: string | null;
  /* Phase 3 (veraltet) */
  logo_key?: string | null;
  watermark?: { enabled?: boolean };
  lower_third?: { enabled?: boolean; name?: string; role?: string; position?: string };
  hook_overlay?: Partial<Record<Platform, boolean>>;
}

export interface CaptionStyle {
  highlight_color?: string;
  hook_overlay?: Partial<Record<Platform, boolean>>;
}

export type BrandProfileInput = Omit<
  BrandProfile,
  "id" | "workspace_id" | "version" | "created_at" | "updated_at"
> & { id?: string };

export interface Brief {
  audience?: string;
  wanted?: string;
  exclude?: string;
  platform?: Platform;
  /* Bezahlte Partnerschaft oder Markennennung: Clips bekommen ein Werbelabel (DE „Anzeige“, AT/CH „Werbung“) */
  is_ad?: boolean;
}

export interface Source {
  id: string;
  workspace_id: string;
  brand_profile_id: string | null;
  title: string;
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  storage_key: string;
  proxy_key: string | null;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  rights_status: RightsStatus;
  rights_confirmed_at: string | null;
  rights_confirmed_by: string | null;
  source_owner: string | null;
  source_title: string | null;
  source_url: string | null;
  expected_speakers: number | null;
  brief: Brief;
  status: SourceStatus;
  status_message: string | null;
  temporal_workflow_id: string | null;
  delete_after: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceInput {
  id?: string;
  brand_profile_id: string | null;
  title: string;
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  storage_key: string;
  storage_bucket?: string | null;
  sha256?: string | null;
  rights_status: RightsStatus;
  rights_confirmed_by: string | null;
  source_owner?: string | null;
  source_title?: string | null;
  source_url?: string | null;
  expected_speakers: number | null;
  brief: Brief;
  status?: SourceStatus;
}

export interface PipelineEvent {
  id: number;
  source_id: string;
  step: PipelineStep;
  status: PipelineEventStatus;
  progress: number | null;
  message: string | null;
  payload: Record<string, unknown> | null;
  at: string;
}

export type FillerKind = "hard" | "soft" | null;

export interface TranscriptWord {
  text: string;
  start: number;
  end: number;
  prob: number;
  speaker: string;
  filler: FillerKind;
  negation: boolean;
  sentence_idx: number;
}

export interface TranscriptStats {
  word_count?: number;
  speakers?: number;
  mean_prob?: number;
  low_conf_ratio?: number;
  speaker_names?: Record<string, string>;
}

export interface TranscriptVersion {
  id: string;
  source_id: string;
  version: number;
  origin: "asr" | "manual" | "vocab_correction" | "merge";
  asr_model_id: string | null;
  asr_variant: string | null;
  diarizer_id: string | null;
  language: string;
  words: TranscriptWord[];
  stats: TranscriptStats;
  created_by: string | null;
  created_at: string;
}

export interface CorrectionInput {
  word_index: number;
  old_text: string;
  new_text: string;
  add_to_vocab: boolean;
}

export interface SaveTranscriptInput {
  words: TranscriptWord[];
  corrections: CorrectionInput[];
  speaker_names: Record<string, string>;
}

/* Kandidaten (Phase 2): Spiegel von packages/schema/CANDIDATES.md, Vertragsversion candidates_v1 */
export type CandidateStructure =
  | "payoff_first"
  | "tension_first"
  | "hook_build_payoff"
  | "decision_story"
  | "how_to_list"
  | "loop";

export type RiskFlag = "humor" | "sensitive_topic" | "claim" | "ad" | "heuristic_only";
export type HumanVerdict = "accepted" | "rejected" | "edited";
export type RubricKey = "hook" | "payoff" | "specificity" | "tension" | "audience_fit";
export type GateKey = "standalone" | "fidelity" | "sentence_boundaries" | "verb_bracket" | "no_open_loop";

export interface CandidateSegment {
  start: number;
  end: number;
  role: "body" | "teaser";
}

export interface RubricScore {
  value: number;
  weight: number;
  evidence: string;
}

export interface CandidateRubric {
  contract: "candidates_v1";
  text: string;
  speakers: string[];
  duration_s: number;
  scores: Record<RubricKey, RubricScore>;
  unresolved_references: string[];
  needs_earlier_context: boolean;
  ends_before_answer: boolean;
  is_humor: boolean;
  sensitive_topic: boolean;
  suggested_title_card: string;
  repair: { rounds: number; expanded_front: number; expanded_back: number; failed: boolean };
  proposal_why: string;
  parent_id: string | null;
  /* Nach Verlängern/Kürzen im Review: Scores stammen vom ursprünglichen Ausschnitt */
  scores_stale?: boolean;
}

export interface GateResult {
  passed: boolean;
  detail: string;
  /* nur verb_bracket: false, wenn spaCy fehlt (dann passed = true mit Hinweis) */
  available?: boolean;
}

export type CandidateGates = Record<GateKey, GateResult>;

export interface StoryGraphFlag {
  sentence_idx: number;
  seconds_after: number;
  marker: string;
  text: string;
  overlap: number;
  /* true nur nach LLM-Bestätigung, null = Heuristik-Treffer (Mensch prüft) */
  confirmed: boolean | null;
  reason: string;
  repair: "extend" | "overlay";
  suggestion: string;
}

export interface Candidate {
  id: string;
  source_id: string;
  version: number;
  segments: CandidateSegment[];
  start_s: number;
  end_s: number;
  first_sent: number | null;
  last_sent: number | null;
  structure: CandidateStructure | null;
  rubric: CandidateRubric;
  gates: CandidateGates;
  story_graph_flags: StoryGraphFlag[];
  risk_flags: RiskFlag[];
  total: number | null;
  gate_passed: boolean;
  why: string | null;
  model_id: string | null;
  prompt_version: string | null;
  human_verdict: HumanVerdict | null;
  verdict_reason: string | null;
  verdict_by: string | null;
  verdict_at: string | null;
  created_at: string;
}

export interface ReviseCandidateInput {
  first_sent: number;
  last_sent: number;
  title_card?: string;
}

export interface CandidateCount {
  total: number;
  gate_passed: number;
  accepted: number;
  rejected: number;
}


/* Clips, Hook-Versionen, Caption-Versionen (Phase 3): Spiegel von packages/schema/CLIPS.md, Vertrag clips_v1 / render_plan_v1 */
export type ClipStatus = "draft" | "approved" | "rendering" | "rendered" | "exported" | "failed" | "deleted";
export type Aspect = "9:16" | "4:5" | "1:1" | "16:9";
export type HookPattern = "identity_call" | "contrarian" | "open_loop" | "results_first" | "mistake_warning";
export type ReframeStrategy = "talking_head" | "two_speakers" | "neutral";
export type RenderStage = "copy" | "reframe" | "captions" | "encode" | "provenance";

export interface Loudness {
  integrated_lufs: number;
  true_peak_dbtp: number;
  preset: "master" | "legacy_social";
}

export interface Provenance {
  c2pa?: "signed" | "skipped" | "failed";
  reason?: string | null;
  ai_label_required?: boolean;
  ai_features?: string[];
  source_credit?: string | null;
  ad_label?: string | null;
}

export interface RenderShot {
  start: number;
  end: number;
  crop_x: number;
  crop_y: number;
  crop_w: number;
  crop_h: number;
  layout: "single" | "split";
}

export interface RenderPlan {
  contract: "render_plan_v1";
  platform: Platform;
  aspect: Aspect;
  output: { width: number; height: number; fps: number };
  segments: CandidateSegment[];
  filler_cuts: boolean;
  reframe: {
    strategy: ReframeStrategy;
    detector: "yunet" | "none";
    faces_detected: boolean;
    positions: number[];
    min_shot_s: number;
  };
  shots: RenderShot[];
  captions: {
    preset: CaptionPreset;
    font: string;
    font_px: number;
    max_chars: number;
    baseline_y: number;
    safe_zone: { top: number; bottom: number; left: number; right: number };
    cards: number;
    highlight: boolean;
  };
  title_card: { text: string; seconds: number } | null;
  hook_overlay: { text: string; seconds: number } | null;
  audio: { preset: "master" | "legacy_social"; lufs: number; true_peak: number; micro_fade_ms: number };
  sources: { storage_key: string; transcript_version: number; hook_version: number; candidate_id: string };
  versions: { captions_de: string; render: string; reframe: string };
}

export interface Clip {
  id: string;
  source_id: string;
  candidate_id: string | null;
  version: number;
  platform: Platform;
  destination: Platform | null;
  aspect: Aspect;
  composition: CandidateSegment[];
  kept_ranges: unknown | null;
  fidelity_warnings: unknown[];
  speaker_positions: Record<string, number> | null;
  render_plan: RenderPlan | null;
  title_card: string | null;
  ad_label: string | null;
  ai_features: string[];
  guest_approval_required: boolean;
  status: ClipStatus;
  file_key: string | null;
  srt_key: string | null;
  vtt_key: string | null;
  poster_key: string | null;
  cps_warnings: string[];
  duration_s: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  loudness: Loudness | null;
  provenance: Provenance;
  render_error: string | null;
  rendered_at: string | null;
  deleted_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface HookVariant {
  pattern: HookPattern;
  spoken: string;
  onscreen: string;
  lint_notes: string[];
  claim_issues: string[];
}

export type PostCaptions = Partial<Record<Platform, string>>;

export interface HookVersion {
  id: string;
  clip_id: string;
  version: number;
  spoken_hook: string | null;
  onscreen_hook: string | null;
  pattern: HookPattern | null;
  variants: HookVariant[];
  post_captions: PostCaptions;
  cta: string | null;
  lint_notes: string[];
  claim_issues: string[];
  origin: "llm" | "manual";
  model_id: string | null;
  prompt_version: string | null;
  created_by: string | null;
  created_at: string;
}

export interface SaveHookInput {
  spoken_hook: string;
  onscreen_hook: string;
  pattern: HookPattern | null;
  post_captions: PostCaptions;
  cta: string;
}

export interface CaptionCard {
  start: number;
  end: number;
  lines: string[];
  /* Wort mit Gewichtswechsel (linkedin_static) oder Highlight (tiktok_bold) */
  keyword?: string;
}

export interface CaptionVersion {
  id: string;
  clip_id: string;
  version: number;
  preset: CaptionPreset;
  cards: CaptionCard[];
  ass_key: string | null;
  srt_key: string | null;
  cps_warnings: string[];
  origin: "auto" | "manual";
  created_by: string | null;
  created_at: string;
}

export interface ClipCount {
  total: number;
  rendered: number;
  rendering: number;
  failed: number;
}

export interface AuditEntry {
  action: string;
  entity: string;
  entity_id: string | null;
  payload?: Record<string, unknown>;
  actor_type?: "user" | "system" | "guest";
}

/* Das Repository kapselt Datenzugriff; Postgres in Produktion, In-Memory im Demo-Modus. */
export interface Repo extends AuthRepo, WorkspaceAdminRepo, BlockBRepo {
  readonly kind: "postgres" | "demo";
  getWorkspace(): Promise<Workspace>;
  listBrandProfiles(): Promise<BrandProfile[]>;
  getBrandProfile(id: string): Promise<BrandProfile | null>;
  saveBrandProfile(input: BrandProfileInput): Promise<BrandProfile>;
  addBrandVocab(profileId: string, words: string[]): Promise<void>;
  listSources(): Promise<Source[]>;
  getSource(id: string): Promise<Source | null>;
  createSource(input: SourceInput): Promise<Source>;
  updateSource(id: string, patch: Partial<Source>): Promise<Source | null>;
  listPipelineEvents(sourceId: string, afterId?: number): Promise<PipelineEvent[]>;
  getCurrentTranscript(sourceId: string): Promise<TranscriptVersion | null>;
  saveTranscript(sourceId: string, input: SaveTranscriptInput): Promise<TranscriptVersion>;
  /* Kandidaten: nur aktuelle Versionen (ohne human_verdict = 'edited'), Pflichtkriterien erfüllt zuerst, dann total absteigend */
  listCandidates(sourceId: string): Promise<Candidate[]>;
  getCandidate(id: string): Promise<Candidate | null>;
  setCandidateVerdict(id: string, verdict: "accepted" | "rejected", reason?: string): Promise<Candidate | null>;
  /* Neue Zeile version + 1 mit neu berechneten Grenzen und Gates; alte Zeile bekommt human_verdict = 'edited' */
  reviseCandidate(id: string, input: ReviseCandidateInput): Promise<Candidate | null>;
  countCandidates(sourceId: string): Promise<CandidateCount>;
  /* Clips (Phase 3): eine Zeile je Zielplattform; bestehende Zeilen (candidate_id, platform) werden wiederverwendet.
   * opts.keepSourceAspect: Hochformat-Schalter aus, der Clip behält das Format der Quelle. */
  createClips(candidateId: string, platforms: Platform[], opts?: { keepSourceAspect?: boolean }): Promise<Clip[]>;
  listClips(sourceId: string): Promise<Clip[]>;
  getClip(id: string): Promise<Clip | null>;
  updateClip(id: string, patch: Partial<Clip>): Promise<Clip | null>;
  /* Demo: startet die Render-Simulation erneut; Postgres: keine Änderung, der Worker übernimmt nach dem Signal */
  /* signaled = false: kein Temporal-Signal, der Clip geht als `draft` in die Warteschlange des lokalen Workers */
  requestClipRender(id: string, signaled?: boolean): Promise<Clip | null>;
  /* Lokaler Testmodus: zu welchem Bucket gehört ein Medien-Key des Workspace (proxy, audio, original, Clip-Dateien)? null = unbekannt */
  resolveMediaBucket(key: string): Promise<"sources" | "derived" | null>;
  countClips(sourceId: string): Promise<ClipCount>;
  getCurrentHook(clipId: string): Promise<HookVersion | null>;
  listHookVersions(clipId: string): Promise<HookVersion[]>;
  /* Neue manuelle Version mit Lint-Hinweisen (lib/copy/lint.ts) und Claim-Issues (lib/copy/claims.ts) */
  saveHook(clipId: string, input: SaveHookInput): Promise<HookVersion>;
  getCurrentCaptions(clipId: string): Promise<CaptionVersion | null>;
  audit(entry: AuditEntry): Promise<void>;
}

/* ------------------------------------------------------------------------------------------------
 * Phase 4, Block A: Nutzer, Sitzungen, Mitgliedschaften, Einladungen, Audit-Abfragen, Abrechnung (lesend)
 * Spiegel von packages/schema/migrations/0003_auth_billing.sql
 * ---------------------------------------------------------------------------------------------- */

export interface User {
  id: string;
  email: string;
  email_verified_at: string | null;
  /* Argon2id (PHC-String); null = nur Magic-Link oder Einladung */
  password_hash: string | null;
  display_name: string | null;
  locale: string;
  last_login_at: string | null;
  created_at: string;
}

export interface UserPatch {
  email?: string;
  email_verified_at?: string | null;
  password_hash?: string | null;
  display_name?: string | null;
  locale?: string;
  last_login_at?: string | null;
}

export interface SessionRow {
  id: string;
  user_id: string;
  workspace_id: string | null;
  expires_at: string;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
}

export type LoginTokenPurpose = "magic_link" | "password_reset" | "verify_email";

export interface LoginToken {
  token: string;
  user_id: string;
  purpose: LoginTokenPurpose;
  expires_at: string;
  used_at: string | null;
}

/* Mitgliedschaft eines Nutzers (für /workspaces und den Sitzungsaufbau) */
export interface Membership {
  workspace_id: string;
  workspace_name: string;
  workspace_slug: string;
  role: Role;
  brand_profile_id: string | null;
  accepted_at: string | null;
}

/* Mitglied eines Workspaces (für /einstellungen/mitglieder) */
export interface WorkspaceMember {
  user_id: string;
  email: string;
  display_name: string | null;
  role: Role;
  brand_profile_id: string | null;
  brand_profile_name: string | null;
  invited_by: string | null;
  accepted_at: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface WorkspaceInvite {
  token: string;
  workspace_id: string;
  workspace_name: string;
  email: string;
  role: Exclude<Role, "owner">;
  brand_profile_id: string | null;
  brand_profile_name: string | null;
  invited_by: string | null;
  invited_by_name: string | null;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

export interface WorkspacePatch {
  name?: string;
  data_region?: string;
  retention_days?: number;
  render_retention_days?: number;
}

export interface AuditRow {
  id: number;
  workspace_id: string | null;
  actor_id: string | null;
  actor_type: "user" | "system" | "guest";
  actor_label: string | null;
  action: string;
  entity: string | null;
  entity_id: string | null;
  payload: Record<string, unknown> | null;
  at: string;
}

export interface AuditFilter {
  action?: string;
  actor_id?: string;
  from?: string; // ISO-Datum inklusive
  to?: string; // ISO-Datum inklusive
  limit: number;
  offset: number;
}

export interface AuditPage {
  rows: AuditRow[];
  total: number;
}

export interface Plan {
  code: string;
  name: string;
  monthly_eur: number;
  included_hours: number;
  overage_eur_per_hour: number;
  max_brand_profiles: number | null;
  max_members: number | null;
  features: Record<string, unknown>;
}

export type SubscriptionStatus = "trialing" | "active" | "past_due" | "canceled" | "paused";

export interface BillingAddress {
  company?: string;
  street?: string;
  zip?: string;
  city?: string;
  country?: string;
  vat_id?: string;
}

export interface Subscription {
  id: string;
  workspace_id: string;
  plan_code: string;
  provider: "manual" | "stripe" | "mollie";
  provider_customer_id: string | null;
  provider_subscription_id: string | null;
  status: SubscriptionStatus;
  current_period_start: string | null;
  current_period_end: string | null;
  trial_ends_at: string | null;
  cancel_at_period_end: boolean;
  billing_email: string | null;
  billing_address: BillingAddress | null;
  updated_at: string | null;
}

export interface SubscriptionPatch {
  plan_code?: string;
  provider?: Subscription["provider"];
  provider_customer_id?: string | null;
  provider_subscription_id?: string | null;
  status?: SubscriptionStatus;
  current_period_start?: string | null;
  current_period_end?: string | null;
  trial_ends_at?: string | null;
  cancel_at_period_end?: boolean;
  billing_email?: string | null;
  billing_address?: BillingAddress | null;
}

export interface UsagePeriod {
  id: string;
  workspace_id: string;
  period_start: string;
  period_end: string;
  included_minutes: number;
  used_source_minutes: number;
  render_count: number;
  overage_minutes: number;
  overage_eur: number;
  closed_at?: string | null;
}

export interface RegisterWorkspaceInput {
  user_id: string;
  email: string;
  display_name: string;
  company: string;
}

/* Auth-Methoden laufen ohne Sitzung (lib/db.ts withAuthContext, Rolle chopstr_auth). Sitzungsgebundene
 * Methoden (Mitglieder, Einladungen, Audit, Abrechnung) laufen im Workspace-Kontext wie die Fachtabellen. */
export interface AuthRepo {
  /* Audit ohne Sitzung (Anmeldung, Magic-Link, Registrierung): Kontext explizit */
  auditAs(ctx: { workspace_id: string | null; actor_id: string | null }, entry: AuditEntry): Promise<void>;
  findUserByEmail(email: string): Promise<User | null>;
  getUser(id: string): Promise<User | null>;
  createUser(input: { email: string; password_hash: string | null; display_name: string | null; locale?: string }): Promise<User>;
  updateUser(id: string, patch: UserPatch): Promise<User | null>;
  createSession(row: Omit<SessionRow, "created_at">): Promise<void>;
  getSessionRow(id: string): Promise<SessionRow | null>;
  touchSession(id: string, expiresAt: string): Promise<void>;
  setSessionWorkspace(id: string, workspaceId: string): Promise<void>;
  deleteSession(id: string): Promise<void>;
  /* Alle Sitzungen eines Nutzers löschen, optional eine behalten */
  deleteUserSessions(userId: string, exceptId?: string): Promise<number>;
  listUserSessions(userId: string): Promise<SessionRow[]>;
  createLoginToken(row: Omit<LoginToken, "used_at">): Promise<void>;
  /* Markiert das Token als benutzt und liefert es, wenn es gültig, unbenutzt und für diesen Zweck war */
  consumeLoginToken(token: string, purpose: LoginTokenPurpose): Promise<LoginToken | null>;
  listMemberships(userId: string): Promise<Membership[]>;
  getMembership(userId: string, workspaceId: string): Promise<Membership | null>;
  /* Registrierung: Workspace, owner-Mitgliedschaft, Standard-Markenprofil, Starter-Test (14 Tage), Nutzungsperiode */
  createWorkspaceWithOwner(input: RegisterWorkspaceInput): Promise<Workspace>;
  /* Einladung per Token lesen (ohne Sitzung, für /einladung/[token]) */
  getInvite(token: string): Promise<WorkspaceInvite | null>;
  /* Einladung annehmen: Mitgliedschaft mit Rolle und Marke, accepted_at. Liefert false, wenn abgelaufen oder benutzt. */
  acceptInvite(token: string, userId: string): Promise<boolean>;
}

export interface WorkspaceAdminRepo {
  updateWorkspace(patch: WorkspacePatch): Promise<Workspace>;
  listMembers(): Promise<WorkspaceMember[]>;
  updateMember(userId: string, patch: { role?: Role; brand_profile_id?: string | null }): Promise<WorkspaceMember | null>;
  removeMember(userId: string): Promise<boolean>;
  listInvites(): Promise<WorkspaceInvite[]>;
  createInvite(input: { email: string; role: Exclude<Role, "owner">; brand_profile_id: string | null; expires_at: string }): Promise<WorkspaceInvite>;
  revokeInvite(token: string): Promise<boolean>;
  listAudit(filter: AuditFilter): Promise<AuditPage>;
  listAuditActions(): Promise<string[]>;
  listAuditActors(): Promise<{ id: string; label: string }[]>;
  getSubscription(): Promise<Subscription | null>;
  getPlan(code: string): Promise<Plan | null>;
  /* Nutzungsperiode des laufenden Monats; wird angelegt, wenn sie fehlt */
  getCurrentUsage(): Promise<UsagePeriod | null>;
}

/* ------------------------------------------------------------------------------------------------
 * Phase 4, Block B: Gast-Freigabe, Abrechnung (schreibend), AVV, Löschung, Export, CI-Assets, Historie
 * ---------------------------------------------------------------------------------------------- */

export type GuestDecision = "approved" | "rejected" | "changes";

export interface GuestApproval {
  id: string;
  clip_id: string;
  guest_name: string | null;
  guest_email: string | null;
  token: string;
  message: string | null;
  requested_by: string | null;
  expires_at: string | null;
  decision: GuestDecision | null;
  comment: string | null;
  decided_at: string | null;
  viewed_at: string | null;
  created_at: string;
}

export interface GuestApprovalInput {
  guest_name: string;
  guest_email: string | null;
  message: string;
  token: string;
  expires_at: string;
}

/* Was die öffentliche Freigabeseite sieht: Freigabe plus Clip-Daten, ohne Workspace-Interna */
export interface GuestApprovalView {
  approval: GuestApproval;
  workspace_id: string;
  workspace_name: string;
  source_title: string;
  clip: {
    id: string;
    platform: Platform;
    aspect: Aspect;
    title_card: string | null;
    duration_s: number | null;
    file_key: string | null;
    poster_key: string | null;
    status: ClipStatus;
  };
  onscreen_hook: string | null;
  spoken_hook: string | null;
  post_caption: string | null;
}

export interface BillingEventInput {
  provider: string;
  provider_event_id: string | null;
  type: string;
  payload: Record<string, unknown> | null;
  workspace_id: string | null;
}

export interface DpaAcceptance {
  id: string;
  workspace_id: string;
  dpa_version: string;
  accepted_by: string | null;
  accepted_by_label?: string | null;
  accepted_at: string;
  ip: string | null;
  company: string | null;
  representative: string | null;
}

export type DeletionEntity = "source" | "clip" | "brand_profile" | "workspace";
export type DeletionReason = "user_request" | "retention" | "workspace_deleted" | "gdpr_request";
export type DeletionStatus = "queued" | "running" | "done" | "failed";

export interface DeletionJob {
  id: string;
  workspace_id: string;
  entity: DeletionEntity;
  entity_id: string;
  /* Titel der Quelle oder Plattform des Clips zum Zeitpunkt der Anfrage (nur Anzeige) */
  entity_label: string | null;
  reason: DeletionReason;
  requested_by: string | null;
  requested_by_label?: string | null;
  status: DeletionStatus;
  keys_deleted: { bucket?: string; key: string; deleted_at?: string; existed?: boolean }[];
  rows_deleted: Record<string, number>;
  error: string | null;
  requested_at: string;
  finished_at: string | null;
}

export type BrandAssetKind = "font" | "logo" | "lower_third_bg" | "watermark";

export interface BrandAsset {
  id: string;
  workspace_id: string;
  brand_profile_id: string;
  kind: BrandAssetKind;
  name: string;
  storage_key: string;
  mime_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  font_family: string | null;
  font_weight: number | null;
  license_note: string | null;
  uploaded_by: string | null;
  created_at: string;
}

export type BrandAssetInput = Omit<BrandAsset, "id" | "workspace_id" | "uploaded_by" | "created_at">;

export interface BrandProfileVersion {
  id: string;
  brand_profile_id: string;
  version: number;
  snapshot: BrandProfile;
  changed_by: string | null;
  changed_by_label?: string | null;
  changed_at: string;
}

/* Datenexport (Art. 15/20): JSON je Tabelle des Workspace plus Medien-Keys */
export interface WorkspaceExport {
  workspace: Workspace;
  brand_profiles: BrandProfile[];
  brand_assets: BrandAsset[];
  brand_profile_versions: BrandProfileVersion[];
  sources: Source[];
  transcript_versions: TranscriptVersion[];
  candidates: Candidate[];
  clips: Clip[];
  hook_versions: HookVersion[];
  caption_versions: CaptionVersion[];
  guest_approvals: GuestApproval[];
  audit_log: AuditRow[];
  job_costs: Record<string, unknown>[];
  usage_periods: UsagePeriod[];
  subscription: Omit<Subscription, "provider_customer_id" | "provider_subscription_id"> | null;
  dpa_acceptances: DpaAcceptance[];
  deletion_jobs: DeletionJob[];
  media_keys: { bucket: "sources" | "derived"; key: string; entity: string; entity_id: string }[];
}

export interface BlockBRepo {
  /* Gast-Freigabe */
  createGuestApproval(clipId: string, input: GuestApprovalInput): Promise<GuestApproval>;
  /* Alle Freigaben der Clips einer Quelle, neueste zuerst (Clip-Karte zeigt die jüngste je Clip) */
  listGuestApprovals(sourceId: string): Promise<GuestApproval[]>;
  /* Öffentlich, ohne Sitzung: Freigabe samt Clip-Daten per Token */
  getGuestApprovalByToken(token: string): Promise<GuestApprovalView | null>;
  markGuestApprovalViewed(token: string): Promise<void>;
  /* Entscheidung des Gastes (ohne Sitzung); null wenn Token unbekannt, abgelaufen oder schon entschieden */
  decideGuestApproval(token: string, decision: GuestDecision, comment: string | null, ip: string | null): Promise<GuestApproval | null>;

  /* Abrechnung */
  listPlans(): Promise<Plan[]>;
  updateSubscription(patch: SubscriptionPatch): Promise<Subscription>;
  /* Vergangene Monate, neueste zuerst */
  listUsageHistory(): Promise<UsagePeriod[]>;
  /* Webhook (ohne Sitzung): true wenn das Ereignis neu war, false bei Duplikat (provider_event_id) */
  recordBillingEvent(input: BillingEventInput): Promise<boolean>;
  findWorkspaceIdByProvider(ref: { customer_id?: string | null; subscription_id?: string | null }): Promise<string | null>;
  updateSubscriptionForWorkspace(workspaceId: string, patch: SubscriptionPatch): Promise<Subscription | null>;

  /* AVV */
  acceptDpa(input: { version: string; company: string; representative: string; ip: string | null }): Promise<DpaAcceptance>;
  getDpaAcceptance(): Promise<DpaAcceptance | null>;

  /* Löschung und Export */
  requestSourceDeletion(sourceId: string): Promise<DeletionJob | null>;
  requestClipDeletion(clipId: string): Promise<DeletionJob | null>;
  listDeletionJobs(): Promise<DeletionJob[]>;
  requestWorkspaceDeletion(scheduledFor: string): Promise<Workspace>;
  cancelWorkspaceDeletion(): Promise<Workspace>;
  exportWorkspace(): Promise<WorkspaceExport>;

  /* CI-Assets und Historie */
  listBrandAssets(profileId: string): Promise<BrandAsset[]>;
  getBrandAsset(id: string): Promise<BrandAsset | null>;
  createBrandAsset(input: BrandAssetInput): Promise<BrandAsset>;
  deleteBrandAsset(id: string): Promise<BrandAsset | null>;
  listBrandProfileVersions(profileId: string): Promise<BrandProfileVersion[]>;
  /* Schreibt vorher einen Snapshot des aktuellen Stands, dann die Felder aus der Version */
  restoreBrandProfileVersion(profileId: string, version: number): Promise<BrandProfile | null>;
}
