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
export type CaptionPreset =
  | "tiktok_bold"
  | "reels_clean"
  | "shorts_clean"
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
  created_at: string;
  updated_at: string;
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

export interface AuditEntry {
  action: string;
  entity: string;
  entity_id: string | null;
  payload?: Record<string, unknown>;
  actor_type?: "user" | "system" | "guest";
}

/* Das Repository kapselt Datenzugriff; Postgres in Produktion, In-Memory im Demo-Modus. */
export interface Repo {
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
  audit(entry: AuditEntry): Promise<void>;
}
