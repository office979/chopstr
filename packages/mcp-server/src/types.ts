/* Datenformen der öffentlichen API, abgeleitet aus packages/schema (CANDIDATES.md, CLIPS.md, PHASE4.md, PHASE5.md).
 * Alle Felder optional gehalten, weil der Server gegen den Vertrag und nicht gegen eine fertige Implementierung arbeitet. */

export type Platform = "tiktok" | "reels" | "shorts" | "linkedin";
export const PLATFORMS: Platform[] = ["tiktok", "reels", "shorts", "linkedin"];

export interface Segment {
  start: number;
  end: number;
  role?: string;
}

export interface Source {
  id: string;
  title?: string;
  status?: string;
  status_message?: string | null;
  duration_s?: number | null;
  brand_profile_id?: string | null;
  rights_status?: string;
  source_owner?: string | null;
  source_url?: string | null;
  source_title?: string | null;
  expected_speakers?: number | null;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface TranscriptWord {
  text: string;
  start: number;
  end: number;
  prob?: number;
  speaker?: string;
  filler?: string | null;
  negation?: boolean;
  sentence_idx?: number;
  text_norm?: string | null;
}

export interface Transcript {
  id?: string;
  source_id?: string;
  version?: number;
  origin?: string;
  language?: string;
  asr_variant?: string | null;
  words: TranscriptWord[];
  stats?: { word_count?: number; speakers?: number; speaker_names?: Record<string, string>; [key: string]: unknown };
  speaker_names?: Record<string, string>;
  [key: string]: unknown;
}

export interface RubricScore {
  value?: number;
  weight?: number;
  evidence?: string;
}

export interface Candidate {
  id: string;
  source_id?: string;
  version?: number;
  segments?: Segment[];
  start_s?: number;
  end_s?: number;
  first_sent?: number;
  last_sent?: number;
  structure?: string;
  rubric?: {
    text?: string;
    speakers?: string[];
    duration_s?: number;
    scores?: Record<string, RubricScore>;
    unresolved_references?: string[];
    needs_earlier_context?: boolean;
    ends_before_answer?: boolean;
    is_humor?: boolean;
    sensitive_topic?: boolean;
    suggested_title_card?: string;
    proposal_why?: string;
    parent_id?: string | null;
    scores_stale?: boolean;
    [key: string]: unknown;
  };
  gates?: Record<string, { passed?: boolean; detail?: string; available?: boolean }>;
  story_graph_flags?: Array<{ marker?: string; text?: string; confirmed?: boolean | null; reason?: string; repair?: string; suggestion?: string; [key: string]: unknown }>;
  risk_flags?: string[];
  total?: number;
  gate_passed?: boolean;
  why?: string;
  human_verdict?: "accepted" | "rejected" | "edited" | null;
  verdict_reason?: string | null;
  [key: string]: unknown;
}

export interface HookVariant {
  pattern?: string;
  spoken?: string;
  onscreen?: string;
  lint_notes?: string[];
  claim_issues?: string[];
}

export interface HookVersion {
  id?: string;
  clip_id?: string;
  version?: number;
  spoken_hook?: string | null;
  onscreen_hook?: string | null;
  pattern?: string | null;
  variants?: HookVariant[];
  post_captions?: Partial<Record<Platform, string>>;
  cta?: string | null;
  lint_notes?: string[];
  claim_issues?: string[];
  origin?: "llm" | "manual";
  [key: string]: unknown;
}

export interface Clip {
  id: string;
  source_id?: string;
  candidate_id?: string | null;
  platform?: Platform;
  aspect?: string;
  status?: string;
  title_card?: string | null;
  ad_label?: string | null;
  guest_approval_required?: boolean;
  duration_s?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  loudness?: { integrated_lufs?: number; true_peak_dbtp?: number; preset?: string } | null;
  provenance?: { c2pa?: string; reason?: string; ai_label_required?: boolean; ai_features?: string[]; source_credit?: string | null; ad_label?: string | null } | null;
  render_plan?: RenderPlan | null;
  render_error?: string | null;
  cps_warnings?: string[];
  fidelity_warnings?: unknown[];
  rendered_at?: string | null;
  hook?: HookVersion | null;
  captions?: unknown;
  media?: Record<string, string | null> | null;
  file_url?: string | null;
  poster_url?: string | null;
  srt_url?: string | null;
  vtt_url?: string | null;
  guest_approval?: { decision?: string | null; expires_at?: string | null; [key: string]: unknown } | null;
  [key: string]: unknown;
}

export interface RenderPlan {
  contract?: string;
  platform?: string;
  aspect?: string;
  output?: { width?: number; height?: number; fps?: number };
  segments?: Segment[];
  reframe?: { strategy?: string; detector?: string; faces_detected?: boolean; [key: string]: unknown };
  shots?: unknown[];
  captions?: { preset?: string; cards?: number; [key: string]: unknown };
  title_card?: { text?: string; seconds?: number } | null;
  hook_overlay?: { text?: string; seconds?: number } | null;
  audio?: { preset?: string; lufs?: number; true_peak?: number; [key: string]: unknown };
  [key: string]: unknown;
}

export interface Usage {
  period_start?: string;
  period_end?: string;
  included_minutes?: number;
  used_source_minutes?: number;
  render_count?: number;
  overage_minutes?: number;
  overage_eur?: number;
  plan?: string | { name?: string; [key: string]: unknown };
  [key: string]: unknown;
}

export interface Publication {
  id?: string;
  clip_id?: string;
  connection_id?: string;
  status?: string;
  scheduled_for?: string | null;
  external_url?: string | null;
  error?: string | null;
  [key: string]: unknown;
}
