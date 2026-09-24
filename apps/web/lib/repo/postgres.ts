import { withAuthContext, withContext, type Tx } from "@/lib/db";
import { currentSession } from "@/lib/session";
import type {
  AuditRow,
  BrandAsset,
  BrandProfile,
  BrandProfileVersion,
  Candidate,
  CaptionVersion,
  Clip,
  ClipStatus,
  DeletionJob,
  DpaAcceptance,
  GuestApproval,
  GuestApprovalView,
  HookVersion,
  LoginToken,
  Membership,
  PipelineEvent,
  Plan,
  Repo,
  SessionRow,
  Source,
  Subscription,
  SubscriptionPatch,
  TranscriptVersion,
  UsagePeriod,
  User,
  Workspace,
  WorkspaceExport,
  WorkspaceInvite,
  WorkspaceMember,
  Zeitmarke,
} from "@/lib/repo/types";
import { sentencesFromWords } from "@/lib/transcript/sentences";
import { buildRevision, isRevisionError } from "@/lib/candidates/revise";
import { aspectFor } from "@/lib/clips/presets";
import { adLabelFor, lintProfileFrom } from "@/lib/clips/render-demo";
import { prepareManualHook } from "@/lib/copy/hooks";

/* Postgres-Repository. Alle Zugriffe laufen in einer Transaktion mit RLS-Kontext (lib/db.ts).
 * Zusätzlich filtern die Abfragen explizit nach workspace_id (und brand_profile_id für client): in der Entwicklung ist die
 * Verbindung Tabellen-Owner, dort greift RLS nicht. Untergeordnete Tabellen (candidates, clips, hooks) werden in den
 * Routen immer über die zuvor geladene Quelle geprüft (source_id-Vergleich). */

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

function toSource(r: Row): Source {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    title: r.title as string,
    original_filename: (r.original_filename as string | null) ?? null,
    mime_type: (r.mime_type as string | null) ?? null,
    size_bytes: num(r.size_bytes),
    sha256: (r.sha256 as string | null) ?? null,
    storage_key: r.storage_key as string,
    proxy_key: (r.proxy_key as string | null) ?? null,
    waveform_key: (r.waveform_key as string | null) ?? null,
    duration_s: num(r.duration_s),
    width: num(r.width),
    height: num(r.height),
    fps: num(r.fps),
    rights_status: r.rights_status as Source["rights_status"],
    rights_confirmed_at: isoOrNull(r.rights_confirmed_at),
    rights_confirmed_by: (r.rights_confirmed_by as string | null) ?? null,
    source_owner: (r.source_owner as string | null) ?? null,
    source_title: (r.source_title as string | null) ?? null,
    source_url: (r.source_url as string | null) ?? null,
    expected_speakers: num(r.expected_speakers),
    brief: jsonValue<Source["brief"]>(r.brief, {}),
    status: r.status as Source["status"],
    status_message: (r.status_message as string | null) ?? null,
    temporal_workflow_id: (r.temporal_workflow_id as string | null) ?? null,
    delete_after: isoOrNull(r.delete_after),
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
    updated_at: isoOrNull(r.updated_at) ?? "",
  };
}

function toBrand(r: Row): BrandProfile {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    name: r.name as string,
    version: num(r.version) ?? 1,
    address: r.address as BrandProfile["address"],
    country: r.country as BrandProfile["country"],
    gender_mode: r.gender_mode as BrandProfile["gender_mode"],
    asr_variant: r.asr_variant as BrandProfile["asr_variant"],
    brand_vocab: (r.brand_vocab as string[]) ?? [],
    protected_terms: (r.protected_terms as string[]) ?? [],
    banned_phrases: (r.banned_phrases as string[]) ?? [],
    tone_adjectives: (r.tone_adjectives as string[]) ?? [],
    default_platform: r.default_platform as BrandProfile["default_platform"],
    /* NULL bleibt NULL: keine ausdrückliche Wahl, das Format entscheidet (Migration 0007) */
    caption_preset: (r.caption_preset as BrandProfile["caption_preset"]) ?? null,
    ci: jsonValue<BrandProfile["ci"]>(r.ci, {}),
    caption_style: jsonValue<BrandProfile["caption_style"]>(r.caption_style, {}),
    created_at: isoOrNull(r.created_at) ?? "",
    updated_at: isoOrNull(r.updated_at) ?? "",
  };
}

function toEvent(r: Row): PipelineEvent {
  return {
    id: num(r.id) ?? 0,
    source_id: r.source_id as string,
    step: r.step as PipelineEvent["step"],
    status: r.status as PipelineEvent["status"],
    progress: num(r.progress),
    message: (r.message as string | null) ?? null,
    payload: jsonValue<Record<string, unknown> | null>(r.payload, null),
    at: isoOrNull(r.at) ?? "",
  };
}

/* jsonb-Spalten kommen als Objekt; ältere Zeilen könnten doppelt kodiert sein (String) */
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

function toTranscript(r: Row): TranscriptVersion {
  return {
    id: r.id as string,
    source_id: r.source_id as string,
    version: num(r.version) ?? 1,
    origin: r.origin as TranscriptVersion["origin"],
    asr_model_id: (r.asr_model_id as string | null) ?? null,
    asr_variant: (r.asr_variant as string | null) ?? null,
    diarizer_id: (r.diarizer_id as string | null) ?? null,
    language: (r.language as string) ?? "de",
    words: jsonValue<TranscriptVersion["words"]>(r.words, []),
    stats: jsonValue<TranscriptVersion["stats"]>(r.stats, {} as TranscriptVersion["stats"]),
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toCandidate(r: Row): Candidate {
  return {
    id: r.id as string,
    source_id: r.source_id as string,
    version: num(r.version) ?? 1,
    segments: jsonValue<Candidate["segments"]>(r.segments, []),
    start_s: num(r.start_s) ?? 0,
    end_s: num(r.end_s) ?? 0,
    first_sent: num(r.first_sent),
    last_sent: num(r.last_sent),
    structure: (r.structure as Candidate["structure"]) ?? null,
    rubric: jsonValue<Candidate["rubric"]>(r.rubric, {} as Candidate["rubric"]),
    gates: jsonValue<Candidate["gates"]>(r.gates, {} as Candidate["gates"]),
    story_graph_flags: jsonValue<Candidate["story_graph_flags"]>(r.story_graph_flags, []),
    risk_flags: jsonValue<Candidate["risk_flags"]>(r.risk_flags, []),
    total: num(r.total),
    gate_passed: Boolean(r.gate_passed),
    why: (r.why as string | null) ?? null,
    model_id: (r.model_id as string | null) ?? null,
    prompt_version: (r.prompt_version as string | null) ?? null,
    human_verdict: (r.human_verdict as Candidate["human_verdict"]) ?? null,
    verdict_reason: (r.verdict_reason as string | null) ?? null,
    verdict_by: (r.verdict_by as string | null) ?? null,
    verdict_at: isoOrNull(r.verdict_at),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toClip(r: Row): Clip {
  return {
    id: r.id as string,
    source_id: r.source_id as string,
    candidate_id: (r.candidate_id as string | null) ?? null,
    version: num(r.version) ?? 1,
    platform: r.platform as Clip["platform"],
    destination: (r.destination as Clip["destination"]) ?? null,
    aspect: r.aspect as Clip["aspect"],
    review: ((r.review as string | null) ?? "offen") as Clip["review"],
    composition: jsonValue<Clip["composition"]>(r.composition, []),
    kept_ranges: jsonValue<unknown>(r.kept_ranges, null),
    fidelity_warnings: jsonValue<unknown[]>(r.fidelity_warnings, []),
    speaker_positions: jsonValue<Clip["speaker_positions"]>(r.speaker_positions, null),
    render_plan: jsonValue<Clip["render_plan"]>(r.render_plan, null),
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
    filmstrip_meta: jsonValue<Clip["filmstrip_meta"]>(r.filmstrip_meta, null),
    zeitmarken: jsonValue<Clip["zeitmarken"]>(r.zeitmarken, []),
    cps_warnings: jsonValue<string[]>(r.cps_warnings, []),
    duration_s: num(r.duration_s),
    width: num(r.width),
    height: num(r.height),
    fps: num(r.fps),
    loudness: jsonValue<Clip["loudness"]>(r.loudness, null),
    provenance: jsonValue<Clip["provenance"]>(r.provenance, {}),
    render_error: (r.render_error as string | null) ?? null,
    rendered_at: isoOrNull(r.rendered_at),
    delete_after: isoOrNull(r.delete_after),
    deleted_at: isoOrNull(r.deleted_at),
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
    updated_at: isoOrNull(r.updated_at) ?? "",
  };
}

function toHook(r: Row): HookVersion {
  return {
    id: r.id as string,
    clip_id: r.clip_id as string,
    version: num(r.version) ?? 1,
    spoken_hook: (r.spoken_hook as string | null) ?? null,
    onscreen_hook: (r.onscreen_hook as string | null) ?? null,
    pattern: (r.pattern as HookVersion["pattern"]) ?? null,
    variants: jsonValue<HookVersion["variants"]>(r.variants, []),
    post_captions: jsonValue<HookVersion["post_captions"]>(r.post_captions, {}),
    cta: (r.cta as string | null) ?? null,
    lint_notes: jsonValue<string[]>(r.lint_notes, []),
    claim_issues: jsonValue<string[]>(r.claim_issues, []),
    origin: r.origin as HookVersion["origin"],
    model_id: (r.model_id as string | null) ?? null,
    prompt_version: (r.prompt_version as string | null) ?? null,
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toCaptions(r: Row): CaptionVersion {
  return {
    id: r.id as string,
    clip_id: r.clip_id as string,
    version: num(r.version) ?? 1,
    preset: r.preset as CaptionVersion["preset"],
    cards: jsonValue<CaptionVersion["cards"]>(r.cards, []),
    ass_key: (r.ass_key as string | null) ?? null,
    srt_key: (r.srt_key as string | null) ?? null,
    cps_warnings: jsonValue<string[]>(r.cps_warnings, []),
    origin: r.origin as CaptionVersion["origin"],
    created_by: (r.created_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

async function currentHookRow(tx: Tx, clipId: string): Promise<HookVersion | null> {
  const rows = await tx`select * from hook_versions where clip_id = ${clipId} order by version desc limit 1`;
  return rows.length ? toHook(rows[0] as Row) : null;
}

function toWorkspace(r: Row): Workspace {
  return {
    id: r.id as string,
    name: r.name as string,
    slug: r.slug as string,
    plan: r.plan as string,
    tier: r.tier as Workspace["tier"],
    data_region: r.data_region as string,
    retention_days: num(r.retention_days) ?? 30,
    render_retention_days: num(r.render_retention_days) ?? 90,
    allow_us_subprocessors: Boolean(r.allow_us_subprocessors),
    training_opt_in: Boolean(r.training_opt_in),
    dpa_signed_at: isoOrNull(r.dpa_signed_at),
    deletion_requested_at: isoOrNull(r.deletion_requested_at),
    deletion_scheduled_for: isoOrNull(r.deletion_scheduled_for),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toUser(r: Row): User {
  return {
    id: r.id as string,
    email: r.email as string,
    email_verified_at: isoOrNull(r.email_verified_at),
    password_hash: (r.password_hash as string | null) ?? null,
    display_name: (r.display_name as string | null) ?? null,
    locale: (r.locale as string) ?? "de-AT",
    last_login_at: isoOrNull(r.last_login_at),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toSessionRow(r: Row): SessionRow {
  return {
    id: r.id as string,
    user_id: r.user_id as string,
    workspace_id: (r.workspace_id as string | null) ?? null,
    expires_at: isoOrNull(r.expires_at) ?? "",
    ip: r.ip == null ? null : String(r.ip),
    user_agent: (r.user_agent as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toMembership(r: Row): Membership {
  return {
    workspace_id: r.workspace_id as string,
    workspace_name: r.workspace_name as string,
    workspace_slug: r.workspace_slug as string,
    role: r.role as Membership["role"],
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    accepted_at: isoOrNull(r.accepted_at),
  };
}

function toMember(r: Row): WorkspaceMember {
  return {
    user_id: r.user_id as string,
    email: (r.email as string) ?? "",
    display_name: (r.display_name as string | null) ?? null,
    role: r.role as WorkspaceMember["role"],
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    brand_profile_name: (r.brand_profile_name as string | null) ?? null,
    invited_by: (r.invited_by as string | null) ?? null,
    accepted_at: isoOrNull(r.accepted_at),
    created_at: isoOrNull(r.created_at) ?? "",
    last_login_at: isoOrNull(r.last_login_at),
  };
}

function toInvite(r: Row): WorkspaceInvite {
  return {
    token: r.token as string,
    workspace_id: r.workspace_id as string,
    workspace_name: (r.workspace_name as string) ?? "",
    email: r.email as string,
    role: r.role as WorkspaceInvite["role"],
    brand_profile_id: (r.brand_profile_id as string | null) ?? null,
    brand_profile_name: (r.brand_profile_name as string | null) ?? null,
    invited_by: (r.invited_by as string | null) ?? null,
    invited_by_name: (r.invited_by_name as string | null) ?? null,
    expires_at: isoOrNull(r.expires_at) ?? "",
    accepted_at: isoOrNull(r.accepted_at),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toAudit(r: Row): AuditRow {
  return {
    id: num(r.id) ?? 0,
    workspace_id: (r.workspace_id as string | null) ?? null,
    actor_id: (r.actor_id as string | null) ?? null,
    actor_type: (r.actor_type as AuditRow["actor_type"]) ?? "user",
    actor_label: (r.actor_label as string | null) ?? null,
    action: r.action as string,
    entity: (r.entity as string | null) ?? null,
    entity_id: (r.entity_id as string | null) ?? null,
    payload: jsonValue<Record<string, unknown> | null>(r.payload, null),
    at: isoOrNull(r.at) ?? "",
  };
}

function toPlan(r: Row): Plan {
  return {
    code: r.code as string,
    name: r.name as string,
    monthly_eur: num(r.monthly_eur) ?? 0,
    included_hours: num(r.included_hours) ?? 0,
    overage_eur_per_hour: num(r.overage_eur_per_hour) ?? 0,
    max_brand_profiles: num(r.max_brand_profiles),
    max_members: num(r.max_members),
    features: jsonValue<Record<string, unknown>>(r.features, {}),
  };
}

function toSubscription(r: Row): Subscription {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    plan_code: r.plan_code as string,
    provider: r.provider as Subscription["provider"],
    provider_customer_id: (r.provider_customer_id as string | null) ?? null,
    provider_subscription_id: (r.provider_subscription_id as string | null) ?? null,
    status: r.status as Subscription["status"],
    current_period_start: isoOrNull(r.current_period_start),
    current_period_end: isoOrNull(r.current_period_end),
    trial_ends_at: isoOrNull(r.trial_ends_at),
    cancel_at_period_end: Boolean(r.cancel_at_period_end),
    billing_email: (r.billing_email as string | null) ?? null,
    billing_address: jsonValue<Subscription["billing_address"]>(r.billing_address, null),
    updated_at: isoOrNull(r.updated_at),
  };
}

function toUsage(r: Row): UsagePeriod {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    period_start: isoOrNull(r.period_start)?.slice(0, 10) ?? "",
    period_end: isoOrNull(r.period_end)?.slice(0, 10) ?? "",
    included_minutes: num(r.included_minutes) ?? 0,
    used_source_minutes: num(r.used_source_minutes) ?? 0,
    render_count: num(r.render_count) ?? 0,
    overage_minutes: num(r.overage_minutes) ?? 0,
    overage_eur: num(r.overage_eur) ?? 0,
    closed_at: isoOrNull(r.closed_at),
  };
}

function toGuestApproval(r: Row): GuestApproval {
  return {
    id: r.id as string,
    clip_id: r.clip_id as string,
    guest_name: (r.guest_name as string | null) ?? null,
    guest_email: (r.guest_email as string | null) ?? null,
    token: r.token as string,
    message: (r.message as string | null) ?? null,
    requested_by: (r.requested_by as string | null) ?? null,
    expires_at: isoOrNull(r.expires_at),
    decision: (r.decision as GuestApproval["decision"]) ?? null,
    comment: (r.comment as string | null) ?? null,
    comment_at_s: num(r.comment_at_s),
    decided_at: isoOrNull(r.decided_at),
    viewed_at: isoOrNull(r.viewed_at),
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toDpa(r: Row): DpaAcceptance {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    dpa_version: r.dpa_version as string,
    accepted_by: (r.accepted_by as string | null) ?? null,
    accepted_by_label: (r.accepted_by_label as string | null) ?? null,
    accepted_at: isoOrNull(r.accepted_at) ?? "",
    ip: r.ip == null ? null : String(r.ip),
    company: (r.company as string | null) ?? null,
    representative: (r.representative as string | null) ?? null,
  };
}

function toDeletionJob(r: Row): DeletionJob {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    entity: r.entity as DeletionJob["entity"],
    entity_id: r.entity_id as string,
    entity_label: (r.entity_label as string | null) ?? null,
    reason: r.reason as DeletionJob["reason"],
    requested_by: (r.requested_by as string | null) ?? null,
    requested_by_label: (r.requested_by_label as string | null) ?? null,
    status: r.status as DeletionJob["status"],
    keys_deleted: jsonValue<DeletionJob["keys_deleted"]>(r.keys_deleted, []),
    rows_deleted: jsonValue<DeletionJob["rows_deleted"]>(r.rows_deleted, {}),
    error: (r.error as string | null) ?? null,
    requested_at: isoOrNull(r.requested_at) ?? "",
    finished_at: isoOrNull(r.finished_at),
  };
}

function toBrandAsset(r: Row): BrandAsset {
  return {
    id: r.id as string,
    workspace_id: r.workspace_id as string,
    brand_profile_id: r.brand_profile_id as string,
    kind: r.kind as BrandAsset["kind"],
    name: r.name as string,
    storage_key: r.storage_key as string,
    mime_type: (r.mime_type as string | null) ?? null,
    size_bytes: num(r.size_bytes),
    sha256: (r.sha256 as string | null) ?? null,
    font_family: (r.font_family as string | null) ?? null,
    font_weight: num(r.font_weight),
    license_note: (r.license_note as string | null) ?? null,
    uploaded_by: (r.uploaded_by as string | null) ?? null,
    created_at: isoOrNull(r.created_at) ?? "",
  };
}

function toBrandVersion(r: Row): BrandProfileVersion {
  return {
    id: r.id as string,
    brand_profile_id: r.brand_profile_id as string,
    version: num(r.version) ?? 0,
    snapshot: toBrand(jsonValue<Row>(r.snapshot, {})),
    changed_by: (r.changed_by as string | null) ?? null,
    changed_by_label: (r.changed_by_label as string | null) ?? null,
    changed_at: isoOrNull(r.changed_at) ?? "",
  };
}

/* Snapshot des aktuellen Markenprofils nach brand_profile_versions (version = max + 1), vor jeder Änderung */
async function snapshotBrandProfile(tx: Tx, profileId: string, workspaceId: string, actorId: string): Promise<void> {
  await tx`
    insert into brand_profile_versions (brand_profile_id, version, snapshot, changed_by)
    select b.id,
           coalesce((select max(v.version) from brand_profile_versions v where v.brand_profile_id = b.id), 0) + 1,
           to_jsonb(b), ${actorId}
    from brand_profiles b
    where b.id = ${profileId} and b.workspace_id = ${workspaceId}`;
}

const GUEST_VIEW_SELECT = `
  select g.*, c.platform, c.aspect, c.title_card, c.duration_s, c.file_key, c.poster_key, c.status as clip_status,
         s.title as source_title, s.workspace_id, w.name as workspace_name
  from guest_approvals g
  join clips c on c.id = g.clip_id
  join sources s on s.id = c.source_id
  join workspaces w on w.id = s.workspace_id`;

const DELETION_SELECT = `
  select j.*, coalesce(s.title, c.platform) as entity_label, coalesce(u.display_name, u.email) as requested_by_label
  from deletion_jobs j
  left join sources s on j.entity = 'source' and s.id = j.entity_id
  left join clips c on j.entity = 'clip' and c.id = j.entity_id
  left join users u on u.id = j.requested_by`;

function toLoginToken(r: Row): LoginToken {
  return {
    token: r.token as string,
    user_id: r.user_id as string,
    purpose: r.purpose as LoginToken["purpose"],
    expires_at: isoOrNull(r.expires_at) ?? "",
    used_at: isoOrNull(r.used_at),
  };
}

/* Slug aus dem Firmennamen; bei Kollision Zufallssuffix */
function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return base || "workspace";
}

/* Laufender Kalendermonat als ISO-Datum (UTC) */
function currentPeriod(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0));
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

const MEMBER_SELECT = `
  select m.user_id, u.email, coalesce(m.display_name, u.display_name) as display_name, m.role, m.brand_profile_id,
         b.name as brand_profile_name, m.invited_by, m.accepted_at, m.created_at, u.last_login_at
  from workspace_members m
  join users u on u.id = m.user_id
  left join brand_profiles b on b.id = m.brand_profile_id`;

const INVITE_SELECT = `
  select i.*, w.name as workspace_name, b.name as brand_profile_name,
         coalesce(u.display_name, u.email) as invited_by_name
  from workspace_invites i
  join workspaces w on w.id = i.workspace_id
  left join brand_profiles b on b.id = i.brand_profile_id
  left join users u on u.id = i.invited_by`;

export const postgresRepo: Repo = {
  kind: "postgres",

  async getWorkspace() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from workspaces where id = ${session.workspaceId}`;
      if (!rows.length) throw new Error("Workspace nicht gefunden");
      return toWorkspace(rows[0] as Row);
    });
  },

  async listBrandProfiles() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from brand_profiles where workspace_id = ${session.workspaceId} order by created_at asc`;
      return rows.map((r) => toBrand(r as Row));
    });
  },

  async getBrandProfile(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from brand_profiles where id = ${id} and workspace_id = ${session.workspaceId}`;
      return rows.length ? toBrand(rows[0] as Row) : null;
    });
  },

  async saveBrandProfile(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      if (input.id) {
        await snapshotBrandProfile(tx, input.id, session.workspaceId, session.userId);
        const rows = await tx`
          update brand_profiles set
            name = ${input.name},
            address = ${input.address},
            country = ${input.country},
            gender_mode = ${input.gender_mode},
            asr_variant = ${input.asr_variant},
            brand_vocab = ${input.brand_vocab},
            protected_terms = ${input.protected_terms},
            banned_phrases = ${input.banned_phrases},
            tone_adjectives = ${input.tone_adjectives},
            default_platform = ${input.default_platform},
            caption_preset = ${input.caption_preset ?? null},
            ci = ${tx.json((input.ci ?? {}) as never)},
            caption_style = ${tx.json((input.caption_style ?? {}) as never)},
            version = version + 1
          where id = ${input.id} and workspace_id = ${session.workspaceId}
          returning *`;
        if (rows.length) return toBrand(rows[0] as Row);
      }
      const rows = await tx`
        insert into brand_profiles (
          workspace_id, name, address, country, gender_mode, asr_variant, brand_vocab,
          protected_terms, banned_phrases, tone_adjectives, default_platform, caption_preset, ci, caption_style
        ) values (
          ${session.workspaceId}, ${input.name}, ${input.address}, ${input.country}, ${input.gender_mode},
          ${input.asr_variant}, ${input.brand_vocab}, ${input.protected_terms}, ${input.banned_phrases},
          ${input.tone_adjectives}, ${input.default_platform}, ${input.caption_preset ?? null},
          ${tx.json((input.ci ?? {}) as never)}, ${tx.json((input.caption_style ?? {}) as never)}
        ) returning *`;
      return toBrand(rows[0] as Row);
    });
  },

  async addBrandVocab(profileId, words) {
    if (words.length === 0) return;
    const session = await currentSession();
    await withContext(session, async (tx) => {
      await tx`
        update brand_profiles
        set brand_vocab = (
          select array_agg(distinct w) from unnest(brand_vocab || ${words}::text[]) as w
        )
        where id = ${profileId} and workspace_id = ${session.workspaceId}`;
    });
  },

  /* client sieht nur Quellen seiner Marke: RLS über app.brand_scope und zusätzlich hier gefiltert.
   * `or ${deleted}` ist ein Boolescher Parameter: false lässt den Filter stehen, true hebt ihn auf. */
  async listSources(scope) {
    const session = await currentSession();
    const deleted = scope?.includeDeleted === true;
    return withContext(session, async (tx) => {
      const rows = session.brandScope
        ? await tx`select * from sources where workspace_id = ${session.workspaceId} and (status <> 'deleted' or ${deleted}) and brand_profile_id = ${session.brandScope} order by created_at desc`
        : await tx`select * from sources where workspace_id = ${session.workspaceId} and (status <> 'deleted' or ${deleted}) order by created_at desc`;
      return rows.map((r) => toSource(r as Row));
    });
  },

  async getSource(id, scope) {
    const session = await currentSession();
    const deleted = scope?.includeDeleted === true;
    return withContext(session, async (tx) => {
      const rows = session.brandScope
        ? await tx`select * from sources where id = ${id} and workspace_id = ${session.workspaceId} and (status <> 'deleted' or ${deleted}) and brand_profile_id = ${session.brandScope}`
        : await tx`select * from sources where id = ${id} and workspace_id = ${session.workspaceId} and (status <> 'deleted' or ${deleted})`;
      return rows.length ? toSource(rows[0] as Row) : null;
    });
  },

  async createSource(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const wsRows = await tx`select retention_days from workspaces where id = ${session.workspaceId}`;
      const retentionDays = num((wsRows[0] as Row | undefined)?.retention_days) ?? 30;
      const rows = await tx`
        insert into sources (
          id, workspace_id, brand_profile_id, title, original_filename, mime_type, size_bytes, sha256,
          storage_key, rights_status, rights_confirmed_at, rights_confirmed_by, source_owner,
          source_title, source_url, expected_speakers, brief, status, delete_after, created_by
        ) values (
          ${input.id ?? tx`gen_random_uuid()`}, ${session.workspaceId}, ${input.brand_profile_id},
          ${input.title}, ${input.original_filename}, ${input.mime_type}, ${input.size_bytes}, ${input.sha256 ?? null},
          ${input.storage_key}, ${input.rights_status}, now(), ${input.rights_confirmed_by ?? session.userId},
          ${input.source_owner ?? null}, ${input.source_title ?? null}, ${input.source_url ?? null},
          ${input.expected_speakers}, ${tx.json((input.brief ?? {}) as never)}, ${input.status ?? "uploaded"},
          now() + make_interval(days => ${retentionDays}), ${session.userId}
        ) returning *`;
      return toSource(rows[0] as Row);
    });
  },

  async updateSource(id, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const allowed: (keyof Source)[] = ["status", "status_message", "temporal_workflow_id", "title"];
      const data: Record<string, unknown> = {};
      for (const key of allowed) {
        if (key in patch) data[key] = patch[key];
      }
      if (Object.keys(data).length === 0) {
        const rows = await tx`select * from sources where id = ${id}`;
        return rows.length ? toSource(rows[0] as Row) : null;
      }
      const rows = await tx`update sources set ${tx(data)} where id = ${id} and workspace_id = ${session.workspaceId} returning *`;
      return rows.length ? toSource(rows[0] as Row) : null;
    });
  },

  async listPipelineEvents(sourceId, afterId = 0) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`
        select * from pipeline_events where source_id = ${sourceId} and id > ${afterId} order by id asc`;
      return rows.map((r) => toEvent(r as Row));
    });
  },

  async getCurrentTranscript(sourceId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from transcripts_current where source_id = ${sourceId}`;
      return rows.length ? toTranscript(rows[0] as Row) : null;
    });
  },

  async saveTranscript(sourceId, input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const current = await tx`select * from transcripts_current where source_id = ${sourceId}`;
      const prev = current.length ? toTranscript(current[0] as Row) : null;
      const words = input.words;
      const lowConf = words.filter((w) => w.prob < 0.9).length;
      const mean = words.length ? words.reduce((acc, w) => acc + w.prob, 0) / words.length : 0;
      const stats = {
        word_count: words.length,
        speakers: new Set(words.map((w) => w.speaker)).size,
        mean_prob: Number(mean.toFixed(3)),
        low_conf_ratio: words.length ? Number((lowConf / words.length).toFixed(3)) : 0,
        speaker_names: input.speaker_names,
      };
      const rows = await tx`
        insert into transcript_versions (
          source_id, version, origin, asr_model_id, asr_variant, diarizer_id, language, words, stats, created_by
        ) values (
          ${sourceId}, ${(prev?.version ?? 0) + 1}, 'manual', ${prev?.asr_model_id ?? null},
          ${prev?.asr_variant ?? null}, ${prev?.diarizer_id ?? null}, ${prev?.language ?? "de"},
          ${tx.json(words as never)}, ${tx.json(stats as never)}, ${session.userId}
        ) returning *`;
      for (const c of input.corrections) {
        await tx`
          insert into transcript_corrections (source_id, from_version, word_index, old_text, new_text, add_to_vocab, created_by)
          values (${sourceId}, ${prev?.version ?? 0}, ${c.word_index}, ${c.old_text}, ${c.new_text}, ${c.add_to_vocab}, ${session.userId})`;
      }
      return toTranscript(rows[0] as Row);
    });
  },

  async listCandidates(sourceId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`
        select * from candidates
        where source_id = ${sourceId} and human_verdict is distinct from 'edited'
        order by gate_passed desc, total desc nulls last, created_at asc`;
      return rows.map((r) => toCandidate(r as Row));
    });
  },

  async getCandidate(id) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from candidates where id = ${id}`;
      return rows.length ? toCandidate(rows[0] as Row) : null;
    });
  },

  async setCandidateVerdict(id, verdict, reason) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update candidates set
          human_verdict = ${verdict},
          verdict_reason = ${reason?.trim() || null},
          verdict_by = ${session.userId},
          verdict_at = now()
        where id = ${id}
        returning *`;
      return rows.length ? toCandidate(rows[0] as Row) : null;
    });
  },

  async reviseCandidate(id, input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const prevRows = await tx`select * from candidates where id = ${id}`;
      if (!prevRows.length) return null;
      const prev = toCandidate(prevRows[0] as Row);
      const tr = await tx`select words from transcripts_current where source_id = ${prev.source_id}`;
      if (!tr.length) throw new Error("Kein Transkript vorhanden");
      const words = jsonValue<TranscriptVersion["words"]>((tr[0] as Row).words, []);
      const revision = buildRevision(prev, sentencesFromWords(words), input);
      if (isRevisionError(revision)) throw new Error(revision.error);
      const rows = await tx`
        insert into candidates (
          source_id, version, segments, start_s, end_s, first_sent, last_sent, structure, rubric, gates,
          story_graph_flags, risk_flags, total, gate_passed, why, model_id, prompt_version
        ) values (
          ${revision.source_id}, ${revision.version}, ${tx.json(revision.segments as never)}, ${revision.start_s},
          ${revision.end_s}, ${revision.first_sent}, ${revision.last_sent}, ${revision.structure},
          ${tx.json(revision.rubric as never)}, ${tx.json(revision.gates as never)},
          ${tx.json(revision.story_graph_flags as never)}, ${tx.json(revision.risk_flags as never)},
          ${revision.total}, ${revision.gate_passed}, ${revision.why}, ${revision.model_id}, ${revision.prompt_version}
        ) returning *`;
      await tx`
        update candidates set human_verdict = 'edited', verdict_by = ${session.userId}, verdict_at = now()
        where id = ${id}`;
      return toCandidate(rows[0] as Row);
    });
  },

  async countCandidates(sourceId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`
        select
          count(*)::int as total,
          count(*) filter (where gate_passed)::int as gate_passed,
          count(*) filter (where human_verdict = 'accepted')::int as accepted,
          count(*) filter (where human_verdict = 'rejected')::int as rejected
        from candidates
        where source_id = ${sourceId} and human_verdict is distinct from 'edited'`;
      const r = (rows[0] ?? {}) as Row;
      return {
        total: num(r.total) ?? 0,
        gate_passed: num(r.gate_passed) ?? 0,
        accepted: num(r.accepted) ?? 0,
        rejected: num(r.rejected) ?? 0,
      };
    });
  },

  async createClips(candidateId, platforms, opts) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const candRows = await tx`select * from candidates where id = ${candidateId}`;
      if (!candRows.length) throw new Error("Kandidat nicht gefunden");
      const candidate = toCandidate(candRows[0] as Row);
      const srcRows = await tx`select * from sources where id = ${candidate.source_id}`;
      if (!srcRows.length) throw new Error("Projekt nicht gefunden");
      const source = toSource(srcRows[0] as Row);
      const brandRows = source.brand_profile_id ? await tx`select * from brand_profiles where id = ${source.brand_profile_id}` : [];
      const brand = brandRows.length ? toBrand(brandRows[0] as Row) : null;
      const out: Clip[] = [];
      for (const platform of platforms) {
        const existing = await tx`
          select * from clips where candidate_id = ${candidateId} and platform = ${platform} order by created_at desc limit 1`;
        if (existing.length) {
          out.push(toClip(existing[0] as Row));
          continue;
        }
        const rows = await tx`
          insert into clips (
            source_id, candidate_id, platform, destination, aspect, composition, title_card, ad_label, status, created_by
          ) values (
            ${source.id}, ${candidate.id}, ${platform}, ${platform}, ${aspectFor(platform, source, opts?.keepSourceAspect)},
            ${tx.json(candidate.segments as never)}, ${candidate.rubric.suggested_title_card?.trim() || null},
            ${adLabelFor(source, brand)}, 'draft', ${session.userId}
          ) returning *`;
        out.push(toClip(rows[0] as Row));
      }
      return out;
    });
  },

  async listClips(sourceId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from clips where source_id = ${sourceId} and status <> 'deleted' order by created_at asc`;
      return rows.map((r) => toClip(r as Row));
    });
  },

  async getClip(id) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from clips where id = ${id} and status <> 'deleted'`;
      return rows.length ? toClip(rows[0] as Row) : null;
    });
  },

  async updateClip(id, patch) {
    return withContext(await currentSession(), async (tx) => {
      const scalar: (keyof Clip)[] = ["status", "review", "title_card", "ad_label", "render_error", "destination"];
      const json: (keyof Clip)[] = ["speaker_positions", "composition"];
      const data: Record<string, unknown> = {};
      for (const key of scalar) {
        if (key in patch) data[key] = patch[key];
      }
      for (const key of json) {
        if (key in patch) data[key] = tx.json(patch[key] as never);
      }
      if (Object.keys(data).length === 0) {
        const rows = await tx`select * from clips where id = ${id}`;
        return rows.length ? toClip(rows[0] as Row) : null;
      }
      const rows = await tx`update clips set ${tx(data)} where id = ${id} returning *`;
      return rows.length ? toClip(rows[0] as Row) : null;
    });
  },

  /* Mit Temporal-Signal setzt der Worker status = 'rendering', hier wird nur der Fehlertext zurückgesetzt.
   * Ohne Signal (kein TEMPORAL_ADDRESS oder Signal fehlgeschlagen) geht der Clip als `draft` in die
   * Warteschlange, der lokale Worker (chopstr_worker.local_worker) holt ihn per Polling ab. */
  async requestClipRender(id, signaled = false) {
    return withContext(await currentSession(), async (tx) => {
      const rows = signaled
        ? await tx`update clips set render_error = null where id = ${id} returning *`
        : await tx`update clips set render_error = null, status = 'draft' where id = ${id} and status <> 'deleted' returning *`;
      return rows.length ? toClip(rows[0] as Row) : null;
    });
  },

  /* Lokaler Testmodus (GET /api/media): Key gehört zum Workspace, wenn er Original, Proxy oder Audio einer Quelle
   * oder MP4, Poster, SRT oder VTT eines Clips ist. client sieht nur Quellen seiner Marke. */
  async resolveMediaBucket(key) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const scope = session.brandScope ?? null;
      const rows = await tx`
        select bucket from (
          select 'sources' as bucket, 0 as prio from sources s
            where s.workspace_id = ${session.workspaceId} and s.status <> 'deleted' and s.storage_key = ${key}
              and (${scope}::uuid is null or s.brand_profile_id = ${scope}::uuid)
          union all
          select 'derived', 1 from sources s
            where s.workspace_id = ${session.workspaceId} and s.status <> 'deleted' and (s.proxy_key = ${key} or s.audio_key = ${key})
              and (${scope}::uuid is null or s.brand_profile_id = ${scope}::uuid)
          union all
          select 'derived', 2 from clips c join sources s on s.id = c.source_id
            where s.workspace_id = ${session.workspaceId} and c.status <> 'deleted'
              and (c.file_key = ${key} or c.poster_key = ${key} or c.srt_key = ${key} or c.vtt_key = ${key})
              and (${scope}::uuid is null or s.brand_profile_id = ${scope}::uuid)
        ) hits order by prio limit 1`;
      const bucket = rows.length ? ((rows[0] as Row).bucket as string) : null;
      return bucket === "sources" || bucket === "derived" ? bucket : null;
    });
  },

  /* Alle Clips des Arbeitsbereichs mit genau den Feldern, aus denen sich ihr Stand rechnen
   * lässt. Eine Abfrage statt einer je Video, und vom Renderplan nur die vier verglichenen Teile
   * statt des ganzen Plans. */
  async listClipStands() {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`
        select c.id, c.source_id, c.status, c.review,
               (c.file_key is not null) as hat_datei,
               c.composition, c.zeitmarken, c.cps_warnings, c.fidelity_warnings, c.render_error,
               c.render_plan->'captions'                 as plan_captions,
               c.render_plan->'segments'                 as plan_segments,
               c.render_plan->'zeitmarken'               as plan_zeitmarken,
               c.render_plan->'sources'->>'transcript_version' as plan_tv,
               c.render_plan->'output'->>'height'        as plan_h,
               c.render_plan->'brand'->>'profil_fassung' as marken_fassung,
               c.caption_style,
               (select max(t.version) from transcript_versions t where t.source_id = c.source_id) as tv
        from clips c
        where c.status <> 'deleted' and c.deleted_at is null`;
      return (rows as Row[]).map((r) => ({
        id: r.id as string,
        source_id: r.source_id as string,
        status: r.status as ClipStatus,
        review: ((r.review as string | null) ?? "offen") as Clip["review"],
        hat_datei: Boolean(r.hat_datei),
        composition: jsonValue<Clip["composition"]>(r.composition, []),
        zeitmarken: jsonValue<Zeitmarke[]>(r.zeitmarken, []),
        cps_warnings: jsonValue<string[]>(r.cps_warnings, []),
        fidelity_warnings: jsonValue<unknown[]>(r.fidelity_warnings, []),
        render_error: (r.render_error as string | null) ?? null,
        plan_captions: jsonValue<Record<string, unknown> | null>(r.plan_captions, null),
        plan_segments: jsonValue<Clip["composition"] | null>(r.plan_segments, null),
        plan_zeitmarken: jsonValue<Zeitmarke[] | null>(r.plan_zeitmarken, null),
        plan_transcript_version: num(r.plan_tv),
        plan_output_height: num(r.plan_h),
        caption_style: jsonValue<Record<string, unknown> | null>(r.caption_style, null),
        transkript_version: num(r.tv),
        marken_fassung: num(r.marken_fassung),
      }));
    });
  },

  async countClips(sourceId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`
        select
          count(*)::int as total,
          count(*) filter (where status in ('rendered', 'exported'))::int as rendered,
          count(*) filter (where status = 'rendering')::int as rendering,
          count(*) filter (where status = 'failed')::int as failed,
          count(*) filter (where status in ('rendered', 'exported') and review = 'offen')::int as offen,
          count(*) filter (where review = 'bereit')::int as bereit,
          count(*) filter (where review = 'verworfen')::int as verworfen
        from clips where source_id = ${sourceId} and status <> 'deleted'`;
      const r = (rows[0] ?? {}) as Row;
      return {
        total: num(r.total) ?? 0,
        rendered: num(r.rendered) ?? 0,
        rendering: num(r.rendering) ?? 0,
        failed: num(r.failed) ?? 0,
        offen: num(r.offen) ?? 0,
        bereit: num(r.bereit) ?? 0,
        verworfen: num(r.verworfen) ?? 0,
      };
    });
  },

  async getCurrentHook(clipId) {
    return withContext(await currentSession(), async (tx) => currentHookRow(tx, clipId));
  },

  async listHookVersions(clipId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from hook_versions where clip_id = ${clipId} order by version asc`;
      return rows.map((r) => toHook(r as Row));
    });
  },

  async saveHook(clipId, input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const clipRows = await tx`select * from clips where id = ${clipId}`;
      if (!clipRows.length) throw new Error("Clip nicht gefunden");
      const clip = toClip(clipRows[0] as Row);
      const candRows = clip.candidate_id ? await tx`select rubric from candidates where id = ${clip.candidate_id}` : [];
      const rubric = candRows.length ? jsonValue<Candidate["rubric"]>((candRows[0] as Row).rubric, {} as Candidate["rubric"]) : null;
      const srcRows = await tx`select brand_profile_id from sources where id = ${clip.source_id}`;
      const brandId = srcRows.length ? ((srcRows[0] as Row).brand_profile_id as string | null) : null;
      const brandRows = brandId ? await tx`select * from brand_profiles where id = ${brandId}` : [];
      const brand = brandRows.length ? toBrand(brandRows[0] as Row) : null;
      const prev = await currentHookRow(tx, clipId);
      const f = prepareManualHook(input, { clipText: rubric?.text ?? "", profile: lintProfileFrom(brand) }, prev);
      const rows = await tx`
        insert into hook_versions (
          clip_id, version, spoken_hook, onscreen_hook, pattern, variants, post_captions, cta, lint_notes,
          claim_issues, origin, model_id, prompt_version, created_by
        ) values (
          ${clipId}, ${(prev?.version ?? 0) + 1}, ${f.spoken_hook}, ${f.onscreen_hook}, ${f.pattern},
          ${tx.json(f.variants as never)}, ${tx.json(f.post_captions as never)}, ${f.cta},
          ${tx.json(f.lint_notes as never)}, ${tx.json(f.claim_issues as never)}, 'manual', ${f.model_id},
          ${f.prompt_version}, ${session.userId}
        ) returning *`;
      return toHook(rows[0] as Row);
    });
  },

  async getCurrentCaptions(clipId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from caption_versions where clip_id = ${clipId} order by version desc limit 1`;
      return rows.length ? toCaptions(rows[0] as Row) : null;
    });
  },

  async audit(entry) {
    const session = await currentSession();
    await withContext(session, async (tx) => {
      await tx`
        insert into audit_log (workspace_id, actor_id, actor_type, action, entity, entity_id, payload)
        values (${session.workspaceId}, ${session.userId}, ${entry.actor_type ?? "user"}, ${entry.action},
                ${entry.entity}, ${entry.entity_id}, ${tx.json((entry.payload ?? {}) as never)})`;
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Auth (ohne Sitzung): users, sessions, login_tokens, Mitgliedschaften, Registrierung, Einladung
   * ---------------------------------------------------------------------------------------- */

  async auditAs(ctx, entry) {
    await withAuthContext(async (tx) => {
      await tx`
        insert into audit_log (workspace_id, actor_id, actor_type, action, entity, entity_id, payload)
        values (${ctx.workspace_id}, ${ctx.actor_id}, ${entry.actor_type ?? "user"}, ${entry.action},
                ${entry.entity}, ${entry.entity_id}, ${tx.json((entry.payload ?? {}) as never)})`;
    });
  },

  async findUserByEmail(email) {
    return withAuthContext(async (tx) => {
      const rows = await tx`select * from users where lower(email) = lower(${email})`;
      return rows.length ? toUser(rows[0] as Row) : null;
    });
  },

  async getUser(id) {
    return withAuthContext(async (tx) => {
      const rows = await tx`select * from users where id = ${id}`;
      return rows.length ? toUser(rows[0] as Row) : null;
    });
  },

  async createUser(input) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        insert into users (email, password_hash, display_name, locale)
        values (${input.email.toLowerCase()}, ${input.password_hash}, ${input.display_name}, ${input.locale ?? "de-AT"})
        returning *`;
      return toUser(rows[0] as Row);
    });
  },

  async updateUser(id, patch) {
    return withAuthContext(async (tx) => {
      const data: Record<string, unknown> = {};
      for (const key of ["email", "email_verified_at", "password_hash", "display_name", "locale", "last_login_at"] as const) {
        if (key in patch) data[key] = key === "email" && patch.email ? patch.email.toLowerCase() : patch[key];
      }
      const rows = Object.keys(data).length
        ? await tx`update users set ${tx(data)} where id = ${id} returning *`
        : await tx`select * from users where id = ${id}`;
      return rows.length ? toUser(rows[0] as Row) : null;
    });
  },

  async createSession(row) {
    await withAuthContext(async (tx) => {
      await tx`
        insert into sessions (id, user_id, workspace_id, expires_at, ip, user_agent)
        values (${row.id}, ${row.user_id}, ${row.workspace_id}, ${row.expires_at}, ${row.ip}, ${row.user_agent})`;
    });
  },

  async getSessionRow(id) {
    return withAuthContext(async (tx) => {
      const rows = await tx`select * from sessions where id = ${id}`;
      return rows.length ? toSessionRow(rows[0] as Row) : null;
    });
  },

  async touchSession(id, expiresAt) {
    await withAuthContext(async (tx) => {
      await tx`update sessions set expires_at = ${expiresAt} where id = ${id}`;
    });
  },

  async setSessionWorkspace(id, workspaceId) {
    await withAuthContext(async (tx) => {
      await tx`update sessions set workspace_id = ${workspaceId} where id = ${id}`;
    });
  },

  async deleteSession(id) {
    await withAuthContext(async (tx) => {
      await tx`delete from sessions where id = ${id}`;
    });
  },

  async deleteUserSessions(userId, exceptId) {
    return withAuthContext(async (tx) => {
      const rows = exceptId
        ? await tx`delete from sessions where user_id = ${userId} and id <> ${exceptId} returning id`
        : await tx`delete from sessions where user_id = ${userId} returning id`;
      return rows.length;
    });
  },

  async listUserSessions(userId) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        select * from sessions where user_id = ${userId} and expires_at > now() order by created_at desc`;
      return rows.map((r) => toSessionRow(r as Row));
    });
  },

  async createLoginToken(row) {
    await withAuthContext(async (tx) => {
      await tx`
        insert into login_tokens (token, user_id, purpose, expires_at)
        values (${row.token}, ${row.user_id}, ${row.purpose}, ${row.expires_at})`;
    });
  },

  async consumeLoginToken(token, purpose) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        update login_tokens set used_at = now()
        where token = ${token} and purpose = ${purpose} and used_at is null and expires_at > now()
        returning *`;
      return rows.length ? toLoginToken(rows[0] as Row) : null;
    });
  },

  async listMemberships(userId) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        select m.workspace_id, w.name as workspace_name, w.slug as workspace_slug, m.role, m.brand_profile_id, m.accepted_at
        from workspace_members m join workspaces w on w.id = m.workspace_id
        where m.user_id = ${userId}
        order by m.created_at asc`;
      return rows.map((r) => toMembership(r as Row));
    });
  },

  async getMembership(userId, workspaceId) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        select m.workspace_id, w.name as workspace_name, w.slug as workspace_slug, m.role, m.brand_profile_id, m.accepted_at
        from workspace_members m join workspaces w on w.id = m.workspace_id
        where m.user_id = ${userId} and m.workspace_id = ${workspaceId}`;
      return rows.length ? toMembership(rows[0] as Row) : null;
    });
  },

  async createWorkspaceWithOwner(input) {
    return withAuthContext(async (tx) => {
      const base = slugify(input.company);
      let slug = base;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        const taken = await tx`select 1 from workspaces where slug = ${slug}`;
        if (!taken.length) break;
        slug = `${base}-${Math.random().toString(36).slice(2, 6)}`;
      }
      const wsRows = await tx`
        insert into workspaces (name, slug, plan) values (${input.company}, ${slug}, 'starter') returning *`;
      const ws = toWorkspace(wsRows[0] as Row);
      await tx`
        insert into workspace_members (workspace_id, user_id, email, display_name, role, accepted_at)
        values (${ws.id}, ${input.user_id}, ${input.email}, ${input.display_name}, 'owner', now())`;
      await tx`
        insert into brand_profiles (workspace_id, name) values (${ws.id}, ${input.company})`;
      const plan = await tx`select * from plans where code = 'starter'`;
      const includedHours = num((plan[0] as Row | undefined)?.included_hours) ?? 4;
      const period = currentPeriod();
      await tx`
        insert into subscriptions (workspace_id, plan_code, provider, status, current_period_start, current_period_end, trial_ends_at, billing_email)
        values (${ws.id}, 'starter', 'manual', 'trialing', now(), now() + interval '14 days', now() + interval '14 days', ${input.email})`;
      await tx`
        insert into usage_periods (workspace_id, period_start, period_end, included_minutes)
        values (${ws.id}, ${period.start}, ${period.end}, ${includedHours * 60})
        on conflict (workspace_id, period_start) do nothing`;
      return ws;
    });
  },

  async getInvite(token) {
    return withAuthContext(async (tx) => {
      const rows = await tx.unsafe(`${INVITE_SELECT} where i.token = $1`, [token]);
      return rows.length ? toInvite(rows[0] as Row) : null;
    });
  },

  async acceptInvite(token, userId) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        update workspace_invites set accepted_at = now()
        where token = ${token} and accepted_at is null and expires_at > now()
        returning *`;
      if (!rows.length) return false;
      const invite = rows[0] as Row;
      const user = await tx`select email, display_name from users where id = ${userId}`;
      const u = (user[0] ?? {}) as Row;
      await tx`
        insert into workspace_members (workspace_id, user_id, email, display_name, role, brand_profile_id, invited_by, accepted_at)
        values (${invite.workspace_id as string}, ${userId}, ${(u.email as string) ?? null}, ${(u.display_name as string) ?? null},
                ${invite.role as string}, ${(invite.brand_profile_id as string | null) ?? null}, ${(invite.invited_by as string | null) ?? null}, now())
        on conflict (workspace_id, user_id) do update
          set role = excluded.role, brand_profile_id = excluded.brand_profile_id, accepted_at = now()`;
      return true;
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Workspace-Verwaltung (im Sitzungskontext)
   * ---------------------------------------------------------------------------------------- */

  async updateWorkspace(patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      for (const key of ["name", "data_region", "retention_days", "render_retention_days"] as const) {
        if (patch[key] !== undefined) data[key] = patch[key];
      }
      const rows = Object.keys(data).length
        ? await tx`update workspaces set ${tx(data)} where id = ${session.workspaceId} returning *`
        : await tx`select * from workspaces where id = ${session.workspaceId}`;
      return toWorkspace(rows[0] as Row);
    });
  },

  async listMembers() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx.unsafe(`${MEMBER_SELECT} where m.workspace_id = $1 order by m.created_at asc`, [session.workspaceId]);
      return rows.map((r) => toMember(r as Row));
    });
  },

  async updateMember(userId, patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const data: Record<string, unknown> = {};
      if (patch.role !== undefined) data.role = patch.role;
      if (patch.brand_profile_id !== undefined) data.brand_profile_id = patch.brand_profile_id;
      if (Object.keys(data).length) {
        await tx`update workspace_members set ${tx(data)} where workspace_id = ${session.workspaceId} and user_id = ${userId}`;
      }
      const rows = await tx.unsafe(`${MEMBER_SELECT} where m.workspace_id = $1 and m.user_id = $2`, [session.workspaceId, userId]);
      return rows.length ? toMember(rows[0] as Row) : null;
    });
  },

  async removeMember(userId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        delete from workspace_members where workspace_id = ${session.workspaceId} and user_id = ${userId} and role <> 'owner' returning user_id`;
      if (rows.length) {
        /* Sitzungen des Entfernten verlieren den aktiven Workspace */
        await tx`update sessions set workspace_id = null where user_id = ${userId} and workspace_id = ${session.workspaceId}`;
      }
      return rows.length > 0;
    });
  },

  async listInvites() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx.unsafe(
        `${INVITE_SELECT} where i.workspace_id = $1 and i.accepted_at is null and i.expires_at > now() order by i.created_at desc`,
        [session.workspaceId],
      );
      return rows.map((r) => toInvite(r as Row));
    });
  },

  async createInvite(input) {
    const session = await currentSession();
    const { randomBytes } = await import("node:crypto");
    const token = randomBytes(32).toString("base64url");
    return withContext(session, async (tx) => {
      await tx`
        insert into workspace_invites (token, workspace_id, email, role, brand_profile_id, invited_by, expires_at)
        values (${token}, ${session.workspaceId}, ${input.email.toLowerCase()}, ${input.role}, ${input.brand_profile_id}, ${session.userId}, ${input.expires_at})`;
      const rows = await tx.unsafe(`${INVITE_SELECT} where i.token = $1`, [token]);
      return toInvite(rows[0] as Row);
    });
  },

  async revokeInvite(token) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`delete from workspace_invites where token = ${token} and workspace_id = ${session.workspaceId} returning token`;
      return rows.length > 0;
    });
  },

  async listAudit(filter) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const where = [`a.workspace_id = $1`];
      const params: unknown[] = [session.workspaceId];
      if (filter.action) {
        params.push(filter.action);
        where.push(`a.action = $${params.length}`);
      }
      if (filter.actor_id) {
        params.push(filter.actor_id);
        where.push(`a.actor_id = $${params.length}`);
      }
      if (filter.from) {
        params.push(filter.from);
        where.push(`a.at >= $${params.length}::date`);
      }
      if (filter.to) {
        params.push(filter.to);
        where.push(`a.at < ($${params.length}::date + interval '1 day')`);
      }
      const clause = where.join(" and ");
      const countRows = await tx.unsafe(`select count(*)::int as total from audit_log a where ${clause}`, params as never);
      params.push(filter.limit, filter.offset);
      const rows = await tx.unsafe(
        `select a.*, coalesce(u.display_name, u.email) as actor_label
         from audit_log a left join users u on u.id = a.actor_id
         where ${clause}
         order by a.at desc, a.id desc
         limit $${params.length - 1} offset $${params.length}`,
        params as never,
      );
      return { rows: rows.map((r) => toAudit(r as Row)), total: num((countRows[0] as Row).total) ?? 0 };
    });
  },

  async listAuditActions() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select distinct action from audit_log where workspace_id = ${session.workspaceId} order by action`;
      return rows.map((r) => (r as Row).action as string);
    });
  },

  async listAuditActors() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select distinct a.actor_id as id, coalesce(u.display_name, u.email, a.actor_id::text) as label
        from audit_log a left join users u on u.id = a.actor_id
        where a.workspace_id = ${session.workspaceId} and a.actor_id is not null
        order by label`;
      return rows.map((r) => ({ id: (r as Row).id as string, label: (r as Row).label as string }));
    });
  },

  async getSubscription() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from subscriptions where workspace_id = ${session.workspaceId}`;
      return rows.length ? toSubscription(rows[0] as Row) : null;
    });
  },

  async getPlan(code) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from plans where code = ${code}`;
      return rows.length ? toPlan(rows[0] as Row) : null;
    });
  },

  async getCurrentUsage() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const period = currentPeriod();
      const existing = await tx`
        select * from usage_periods where workspace_id = ${session.workspaceId} and period_start = ${period.start}`;
      if (existing.length) return toUsage(existing[0] as Row);
      /* Plan aus dem Abo, sonst aus workspaces.plan (ältere Workspaces ohne subscriptions-Zeile) */
      const sub = await tx`
        select p.included_hours from subscriptions s join plans p on p.code = s.plan_code where s.workspace_id = ${session.workspaceId}
        union all
        select p.included_hours from workspaces w join plans p on p.code = w.plan where w.id = ${session.workspaceId}
        limit 1`;
      if (!sub.length) return null;
      const included = (num((sub[0] as Row).included_hours) ?? 0) * 60;
      const rows = await tx`
        insert into usage_periods (workspace_id, period_start, period_end, included_minutes)
        values (${session.workspaceId}, ${period.start}, ${period.end}, ${included})
        on conflict (workspace_id, period_start) do update set included_minutes = usage_periods.included_minutes
        returning *`;
      return toUsage(rows[0] as Row);
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: Gast-Freigabe
   * ---------------------------------------------------------------------------------------- */

  async createGuestApproval(clipId, input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into guest_approvals (clip_id, guest_name, guest_email, message, requested_by, token, expires_at)
        values (${clipId}, ${input.guest_name}, ${input.guest_email}, ${input.message}, ${session.userId}, ${input.token}, ${input.expires_at})
        returning *`;
      await tx`update clips set guest_approval_required = true where id = ${clipId}`;
      return toGuestApproval(rows[0] as Row);
    });
  },

  async listGuestApprovals(sourceId) {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`
        select g.* from guest_approvals g join clips c on c.id = g.clip_id
        where c.source_id = ${sourceId} order by g.created_at desc`;
      return rows.map((r) => toGuestApproval(r as Row));
    });
  },

  async getGuestApprovalByToken(token) {
    return withAuthContext(async (tx) => {
      const rows = await tx.unsafe(`${GUEST_VIEW_SELECT} where g.token = $1`, [token]);
      if (!rows.length) return null;
      const r = rows[0] as Row;
      const hookRows = await tx`select spoken_hook, onscreen_hook, post_captions from hook_versions where clip_id = ${r.clip_id as string} order by version desc limit 1`;
      const hook = hookRows.length ? (hookRows[0] as Row) : null;
      const platform = r.platform as GuestApprovalView["clip"]["platform"];
      const captions = hook ? jsonValue<Record<string, string>>(hook.post_captions, {}) : {};
      return {
        approval: toGuestApproval(r),
        workspace_id: r.workspace_id as string,
        workspace_name: (r.workspace_name as string) ?? "",
        source_title: (r.source_title as string) ?? "",
        clip: {
          id: r.clip_id as string,
          platform,
          aspect: r.aspect as GuestApprovalView["clip"]["aspect"],
          title_card: (r.title_card as string | null) ?? null,
          duration_s: num(r.duration_s),
          file_key: (r.file_key as string | null) ?? null,
          poster_key: (r.poster_key as string | null) ?? null,
          status: r.clip_status as GuestApprovalView["clip"]["status"],
        },
        onscreen_hook: (hook?.onscreen_hook as string | null) ?? null,
        spoken_hook: (hook?.spoken_hook as string | null) ?? null,
        post_caption: captions[platform] ?? Object.values(captions)[0] ?? null,
      };
    });
  },

  async markGuestApprovalViewed(token) {
    await withAuthContext(async (tx) => {
      await tx`update guest_approvals set viewed_at = now() where token = ${token} and viewed_at is null`;
    });
  },

  async decideGuestApproval(token, decision, comment, beiS, ip) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        update guest_approvals set decision = ${decision}, comment = ${comment}, comment_at_s = ${beiS},
               decided_at = now(), viewed_at = coalesce(viewed_at, now())
        where token = ${token} and decision is null and (expires_at is null or expires_at > now())
        returning *`;
      if (!rows.length) return null;
      const approval = toGuestApproval(rows[0] as Row);
      const ws = await tx`
        select s.workspace_id from clips c join sources s on s.id = c.source_id where c.id = ${approval.clip_id}`;
      const workspaceId = ws.length ? ((ws[0] as Row).workspace_id as string) : null;
      await tx`
        insert into audit_log (workspace_id, actor_id, actor_type, action, entity, entity_id, payload, ip)
        values (${workspaceId}, null, 'guest', 'guest_approval.decided', 'guest_approvals', ${approval.id},
                ${tx.json({ clip_id: approval.clip_id, decision, comment, comment_at_s: beiS, guest_name: approval.guest_name } as never)}, ${ip}::inet)`;
      return approval;
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: Abrechnung
   * ---------------------------------------------------------------------------------------- */

  async listPlans() {
    return withContext(await currentSession(), async (tx) => {
      const rows = await tx`select * from plans where active order by monthly_eur asc`;
      return rows.map((r) => toPlan(r as Row));
    });
  },

  async updateSubscription(patch) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const sub = await upsertSubscription(tx, session.workspaceId, patch, session.email);
      if (!sub) throw new Error("Abo konnte nicht gespeichert werden");
      if (patch.plan_code) await tx`update workspaces set plan = ${patch.plan_code} where id = ${session.workspaceId}`;
      return sub;
    });
  },

  async listUsageHistory() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const period = currentPeriod();
      const rows = await tx`
        select * from usage_periods where workspace_id = ${session.workspaceId} and period_start < ${period.start}
        order by period_start desc limit 24`;
      return rows.map((r) => toUsage(r as Row));
    });
  },

  async recordBillingEvent(input) {
    return withAuthContext(async (tx) => {
      const rows = await tx`
        insert into billing_events (workspace_id, provider, provider_event_id, type, payload)
        values (${input.workspace_id}, ${input.provider}, ${input.provider_event_id}, ${input.type}, ${tx.json((input.payload ?? {}) as never)})
        on conflict (provider_event_id) do nothing
        returning id`;
      return rows.length > 0;
    });
  },

  async findWorkspaceIdByProvider(ref) {
    return withAuthContext(async (tx) => {
      if (ref.subscription_id) {
        const rows = await tx`select workspace_id from subscriptions where provider_subscription_id = ${ref.subscription_id}`;
        if (rows.length) return (rows[0] as Row).workspace_id as string;
      }
      if (ref.customer_id) {
        const rows = await tx`select workspace_id from subscriptions where provider_customer_id = ${ref.customer_id}`;
        if (rows.length) return (rows[0] as Row).workspace_id as string;
      }
      return null;
    });
  },

  async updateSubscriptionForWorkspace(workspaceId, patch) {
    return withAuthContext(async (tx) => {
      const exists = await tx`select 1 from workspaces where id = ${workspaceId}`;
      if (!exists.length) return null;
      const sub = await upsertSubscription(tx, workspaceId, patch, null);
      if (sub && patch.plan_code) await tx`update workspaces set plan = ${patch.plan_code} where id = ${workspaceId}`;
      return sub;
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: AVV
   * ---------------------------------------------------------------------------------------- */

  async acceptDpa(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into dpa_acceptances (workspace_id, dpa_version, accepted_by, ip, company, representative)
        values (${session.workspaceId}, ${input.version}, ${session.userId}, ${input.ip}::inet, ${input.company}, ${input.representative})
        returning *`;
      await tx`update workspaces set dpa_signed_at = now() where id = ${session.workspaceId}`;
      return { ...toDpa(rows[0] as Row), accepted_by_label: session.displayName };
    });
  },

  async getDpaAcceptance() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select d.*, coalesce(u.display_name, u.email) as accepted_by_label
        from dpa_acceptances d left join users u on u.id = d.accepted_by
        where d.workspace_id = ${session.workspaceId} order by d.accepted_at desc limit 1`;
      return rows.length ? toDpa(rows[0] as Row) : null;
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: Löschung und Export
   * ---------------------------------------------------------------------------------------- */

  async requestSourceDeletion(sourceId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = session.brandScope
        ? await tx`update sources set status = 'deleted', deleted_at = now() where id = ${sourceId} and workspace_id = ${session.workspaceId} and status <> 'deleted' and brand_profile_id = ${session.brandScope} returning title`
        : await tx`update sources set status = 'deleted', deleted_at = now() where id = ${sourceId} and workspace_id = ${session.workspaceId} and status <> 'deleted' returning title`;
      if (!rows.length) return null;
      const job = await tx`
        insert into deletion_jobs (workspace_id, entity, entity_id, reason, requested_by)
        values (${session.workspaceId}, 'source', ${sourceId}, 'user_request', ${session.userId}) returning *`;
      return { ...toDeletionJob(job[0] as Row), entity_label: (rows[0] as Row).title as string, requested_by_label: session.displayName };
    });
  },

  async requestClipDeletion(clipId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update clips c set status = 'deleted', deleted_at = now()
        from sources s
        where c.id = ${clipId} and s.id = c.source_id and s.workspace_id = ${session.workspaceId} and c.status <> 'deleted'
        returning c.platform`;
      if (!rows.length) return null;
      const job = await tx`
        insert into deletion_jobs (workspace_id, entity, entity_id, reason, requested_by)
        values (${session.workspaceId}, 'clip', ${clipId}, 'user_request', ${session.userId}) returning *`;
      return { ...toDeletionJob(job[0] as Row), entity_label: (rows[0] as Row).platform as string, requested_by_label: session.displayName };
    });
  },

  async listDeletionJobs() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx.unsafe(`${DELETION_SELECT} where j.workspace_id = $1 order by j.requested_at desc limit 200`, [session.workspaceId]);
      return rows.map((r) => toDeletionJob(r as Row));
    });
  },

  async requestWorkspaceDeletion(scheduledFor) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update workspaces set deletion_requested_at = now(), deletion_scheduled_for = ${scheduledFor}
        where id = ${session.workspaceId} returning *`;
      return toWorkspace(rows[0] as Row);
    });
  },

  async cancelWorkspaceDeletion() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update workspaces set deletion_requested_at = null, deletion_scheduled_for = null
        where id = ${session.workspaceId} returning *`;
      return toWorkspace(rows[0] as Row);
    });
  },

  async exportWorkspace() {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const ws = session.workspaceId;
      const wsRows = await tx`select * from workspaces where id = ${ws}`;
      const brands = await tx`select * from brand_profiles where workspace_id = ${ws} order by created_at`;
      const assets = await tx`select * from brand_assets where workspace_id = ${ws} order by created_at`;
      const versions = await tx`
        select v.* from brand_profile_versions v join brand_profiles b on b.id = v.brand_profile_id
        where b.workspace_id = ${ws} order by v.brand_profile_id, v.version`;
      const sources = await tx`select * from sources where workspace_id = ${ws} order by created_at`;
      const transcripts = await tx`
        select t.* from transcript_versions t join sources s on s.id = t.source_id where s.workspace_id = ${ws} order by t.source_id, t.version`;
      const candidates = await tx`
        select c.* from candidates c join sources s on s.id = c.source_id where s.workspace_id = ${ws} order by c.created_at`;
      const clips = await tx`
        select c.* from clips c join sources s on s.id = c.source_id where s.workspace_id = ${ws} order by c.created_at`;
      const hooks = await tx`
        select h.* from hook_versions h join clips c on c.id = h.clip_id join sources s on s.id = c.source_id
        where s.workspace_id = ${ws} order by h.clip_id, h.version`;
      const captions = await tx`
        select v.* from caption_versions v join clips c on c.id = v.clip_id join sources s on s.id = c.source_id
        where s.workspace_id = ${ws} order by v.clip_id, v.version`;
      const approvals = await tx`
        select g.* from guest_approvals g join clips c on c.id = g.clip_id join sources s on s.id = c.source_id
        where s.workspace_id = ${ws} order by g.created_at`;
      const audit = await tx`
        select a.*, coalesce(u.display_name, u.email) as actor_label from audit_log a left join users u on u.id = a.actor_id
        where a.workspace_id = ${ws} order by a.id`;
      const costs = await tx`select * from job_costs where workspace_id = ${ws} order by created_at`;
      const usage = await tx`select * from usage_periods where workspace_id = ${ws} order by period_start`;
      const subs = await tx`select * from subscriptions where workspace_id = ${ws}`;
      const dpa = await tx`select * from dpa_acceptances where workspace_id = ${ws} order by accepted_at`;
      const jobs = await tx.unsafe(`${DELETION_SELECT} where j.workspace_id = $1 order by j.requested_at`, [ws]);

      const sourceList = sources.map((r) => toSource(r as Row));
      const clipList = clips.map((r) => toClip(r as Row));
      const assetList = assets.map((r) => toBrandAsset(r as Row));
      const captionList = captions.map((r) => toCaptions(r as Row));
      const mediaKeys: WorkspaceExport["media_keys"] = [];
      for (const src of sources as unknown as Row[]) {
        if (src.storage_key) mediaKeys.push({ bucket: "sources", key: src.storage_key as string, entity: "sources", entity_id: src.id as string });
        for (const k of ["audio_key", "proxy_key"] as const) {
          if (src[k]) mediaKeys.push({ bucket: "derived", key: src[k] as string, entity: "sources", entity_id: src.id as string });
        }
      }
      for (const clip of clipList) {
        for (const k of [clip.file_key, clip.srt_key, clip.vtt_key, clip.poster_key]) {
          if (k) mediaKeys.push({ bucket: "derived", key: k, entity: "clips", entity_id: clip.id });
        }
      }
      for (const cap of captionList) {
        for (const k of [cap.ass_key, cap.srt_key]) {
          if (k) mediaKeys.push({ bucket: "derived", key: k, entity: "caption_versions", entity_id: cap.id });
        }
      }
      for (const asset of assetList) mediaKeys.push({ bucket: "derived", key: asset.storage_key, entity: "brand_assets", entity_id: asset.id });

      const sub = subs.length ? toSubscription(subs[0] as Row) : null;
      const subscription = sub ? { ...sub, provider_customer_id: undefined, provider_subscription_id: undefined } : null;
      return {
        workspace: toWorkspace(wsRows[0] as Row),
        brand_profiles: brands.map((r) => toBrand(r as Row)),
        brand_assets: assetList,
        brand_profile_versions: versions.map((r) => toBrandVersion(r as Row)),
        sources: sourceList,
        transcript_versions: transcripts.map((r) => toTranscript(r as Row)),
        candidates: candidates.map((r) => toCandidate(r as Row)),
        clips: clipList,
        hook_versions: hooks.map((r) => toHook(r as Row)),
        caption_versions: captionList,
        guest_approvals: approvals.map((r) => toGuestApproval(r as Row)),
        audit_log: audit.map((r) => toAudit(r as Row)),
        job_costs: (costs as unknown as Row[]).map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v instanceof Date ? v.toISOString() : v]))),
        usage_periods: usage.map((r) => toUsage(r as Row)),
        subscription,
        dpa_acceptances: dpa.map((r) => toDpa(r as Row)),
        deletion_jobs: jobs.map((r) => toDeletionJob(r as Row)),
        media_keys: mediaKeys,
      };
    });
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: CI-Assets und Markenprofil-Historie
   * ---------------------------------------------------------------------------------------- */

  async listBrandAssets(profileId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select * from brand_assets where brand_profile_id = ${profileId} and workspace_id = ${session.workspaceId} order by created_at asc`;
      return rows.map((r) => toBrandAsset(r as Row));
    });
  },

  async getBrandAsset(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`select * from brand_assets where id = ${id} and workspace_id = ${session.workspaceId}`;
      return rows.length ? toBrandAsset(rows[0] as Row) : null;
    });
  },

  async createBrandAsset(input) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        insert into brand_assets (workspace_id, brand_profile_id, kind, name, storage_key, mime_type, size_bytes, sha256, font_family, font_weight, license_note, uploaded_by)
        values (${session.workspaceId}, ${input.brand_profile_id}, ${input.kind}, ${input.name}, ${input.storage_key}, ${input.mime_type},
                ${input.size_bytes}, ${input.sha256}, ${input.font_family}, ${input.font_weight}, ${input.license_note}, ${session.userId})
        returning *`;
      return toBrandAsset(rows[0] as Row);
    });
  },

  async deleteBrandAsset(id) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`delete from brand_assets where id = ${id} and workspace_id = ${session.workspaceId} returning *`;
      return rows.length ? toBrandAsset(rows[0] as Row) : null;
    });
  },

  async listBrandProfileVersions(profileId) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select v.*, coalesce(u.display_name, u.email) as changed_by_label
        from brand_profile_versions v
        join brand_profiles b on b.id = v.brand_profile_id
        left join users u on u.id = v.changed_by
        where v.brand_profile_id = ${profileId} and b.workspace_id = ${session.workspaceId}
        order by v.version desc limit 50`;
      return rows.map((r) => toBrandVersion(r as Row));
    });
  },

  async restoreBrandProfileVersion(profileId, version) {
    const session = await currentSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        select v.* from brand_profile_versions v join brand_profiles b on b.id = v.brand_profile_id
        where v.brand_profile_id = ${profileId} and v.version = ${version} and b.workspace_id = ${session.workspaceId}`;
      if (!rows.length) return null;
      const snap = toBrandVersion(rows[0] as Row).snapshot;
      await snapshotBrandProfile(tx, profileId, session.workspaceId, session.userId);
      const updated = await tx`
        update brand_profiles set
          name = ${snap.name},
          address = ${snap.address},
          country = ${snap.country},
          gender_mode = ${snap.gender_mode},
          asr_variant = ${snap.asr_variant},
          brand_vocab = ${snap.brand_vocab},
          protected_terms = ${snap.protected_terms},
          banned_phrases = ${snap.banned_phrases},
          tone_adjectives = ${snap.tone_adjectives},
          default_platform = ${snap.default_platform},
          caption_preset = ${snap.caption_preset ?? null},
          ci = ${tx.json((snap.ci ?? {}) as never)},
          caption_style = ${tx.json((snap.caption_style ?? {}) as never)},
          version = version + 1
        where id = ${profileId} and workspace_id = ${session.workspaceId}
        returning *`;
      return updated.length ? toBrand(updated[0] as Row) : null;
    });
  },
};

/* Abo-Zeile anlegen oder ändern (unique index auf workspace_id). Fehlende Pflichtfelder beim Anlegen: starter, manual, trialing. */
async function upsertSubscription(tx: Tx, workspaceId: string, patch: SubscriptionPatch, fallbackEmail: string | null): Promise<Subscription | null> {
  const data: Record<string, unknown> = {};
  for (const key of [
    "plan_code",
    "provider",
    "provider_customer_id",
    "provider_subscription_id",
    "status",
    "current_period_start",
    "current_period_end",
    "trial_ends_at",
    "cancel_at_period_end",
    "billing_email",
  ] as const) {
    if (patch[key] !== undefined) data[key] = patch[key];
  }
  if (patch.billing_address !== undefined) data.billing_address = patch.billing_address == null ? null : tx.json(patch.billing_address as never);
  const existing = await tx`select * from subscriptions where workspace_id = ${workspaceId}`;
  if (existing.length) {
    const rows = Object.keys(data).length
      ? await tx`update subscriptions set ${tx(data)} where workspace_id = ${workspaceId} returning *`
      : existing;
    return toSubscription(rows[0] as Row);
  }
  const planRows = await tx`select plan from workspaces where id = ${workspaceId}`;
  const rows = await tx`
    insert into subscriptions (workspace_id, plan_code, provider, status, billing_email)
    values (${workspaceId}, ${patch.plan_code ?? ((planRows[0] as Row | undefined)?.plan as string | undefined) ?? "starter"},
            ${patch.provider ?? "manual"}, ${patch.status ?? "trialing"}, ${patch.billing_email ?? fallbackEmail})
    returning *`;
  const inserted = toSubscription(rows[0] as Row);
  const rest = { ...data };
  delete rest.plan_code;
  delete rest.provider;
  delete rest.status;
  delete rest.billing_email;
  if (Object.keys(rest).length) {
    const again = await tx`update subscriptions set ${tx(rest)} where workspace_id = ${workspaceId} returning *`;
    return toSubscription(again[0] as Row);
  }
  return inserted;
}
