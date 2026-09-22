import type { BrandProfile, CaptionVersion, Clip, GuestApproval, HookVersion, Source, TranscriptVersion, Workspace } from "@/lib/repo/types";
import type { ApiKey, Publication, WebhookEndpoint } from "@/lib/repo/types-api";
import type { QuotaState } from "@/lib/billing/quota";
import { mediaUrl } from "@/lib/clips/labels";

/* Antwortformen der öffentlichen API (PHASE5.md, 5a und packages/mcp-server/test/mock-api.ts):
 * Listen { sources: [...] }, Einzelobjekte { source }, Medien-URLs am Clip unter media: { video_url, poster_url, srt_url, vtt_url }.
 * Interne Speicherschlüssel (storage_key, proxy_key, Workflow-IDs) bleiben draußen. */

export function serializeSource(s: Source) {
  return {
    id: s.id,
    title: s.title,
    status: s.status,
    status_message: s.status_message,
    duration_s: s.duration_s,
    width: s.width,
    height: s.height,
    fps: s.fps,
    brand_profile_id: s.brand_profile_id,
    original_filename: s.original_filename,
    mime_type: s.mime_type,
    size_bytes: s.size_bytes,
    rights_status: s.rights_status,
    rights_confirmed_at: s.rights_confirmed_at,
    source_owner: s.source_owner,
    source_title: s.source_title,
    source_url: s.source_url,
    expected_speakers: s.expected_speakers,
    brief: s.brief,
    delete_after: s.delete_after,
    created_at: s.created_at,
    updated_at: s.updated_at,
  };
}

export function serializeTranscript(t: TranscriptVersion) {
  return {
    id: t.id,
    source_id: t.source_id,
    version: t.version,
    origin: t.origin,
    asr_model_id: t.asr_model_id,
    asr_variant: t.asr_variant,
    language: t.language,
    words: t.words,
    stats: t.stats,
    created_at: t.created_at,
  };
}

export interface ClipMedia {
  video_url: string | null;
  poster_url: string | null;
  srt_url: string | null;
  vtt_url: string | null;
}

export function clipMedia(c: Clip): ClipMedia {
  const base = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;
  return {
    video_url: mediaUrl(base, c.file_key),
    poster_url: mediaUrl(base, c.poster_key),
    srt_url: mediaUrl(base, c.srt_key),
    vtt_url: mediaUrl(base, c.vtt_key),
  };
}

export function serializeGuestApproval(a: GuestApproval | null | undefined) {
  if (!a) return null;
  return {
    id: a.id,
    clip_id: a.clip_id,
    guest_name: a.guest_name,
    guest_email: a.guest_email,
    message: a.message,
    expires_at: a.expires_at,
    decision: a.decision,
    comment: a.comment,
    decided_at: a.decided_at,
    viewed_at: a.viewed_at,
    created_at: a.created_at,
  };
}

export function serializeClip(c: Clip, extra?: { hook?: HookVersion | null; captions?: CaptionVersion | null; guest_approval?: GuestApproval | null }) {
  const base = {
    id: c.id,
    source_id: c.source_id,
    candidate_id: c.candidate_id,
    version: c.version,
    platform: c.platform,
    destination: c.destination,
    aspect: c.aspect,
    composition: c.composition,
    fidelity_warnings: c.fidelity_warnings,
    render_plan: c.render_plan,
    title_card: c.title_card,
    ad_label: c.ad_label,
    ai_features: c.ai_features,
    guest_approval_required: c.guest_approval_required,
    status: c.status,
    cps_warnings: c.cps_warnings,
    duration_s: c.duration_s,
    width: c.width,
    height: c.height,
    fps: c.fps,
    loudness: c.loudness,
    provenance: c.provenance,
    render_error: c.render_error,
    rendered_at: c.rendered_at,
    created_at: c.created_at,
    updated_at: c.updated_at,
    media: clipMedia(c),
  };
  if (!extra) return base;
  return {
    ...base,
    hook: extra.hook ?? null,
    captions: extra.captions ? { id: extra.captions.id, version: extra.captions.version, preset: extra.captions.preset, cards: extra.captions.cards, cps_warnings: extra.captions.cps_warnings, origin: extra.captions.origin } : null,
    guest_approval: serializeGuestApproval(extra.guest_approval),
  };
}

export function serializeBrandProfile(b: BrandProfile) {
  return { ...b };
}

export function serializeUsage(q: QuotaState) {
  const u = q.usage;
  return {
    period_start: u?.period_start ?? null,
    period_end: u?.period_end ?? null,
    included_minutes: q.included_minutes,
    used_source_minutes: q.used_minutes,
    render_count: u?.render_count ?? 0,
    overage_minutes: u?.overage_minutes ?? 0,
    overage_eur: u?.overage_eur ?? 0,
    plan: q.plan?.code ?? null,
    plan_name: q.plan?.name ?? null,
    allow_overage: q.allow_overage,
    exhausted: q.exhausted,
    subscription_status: q.subscription?.status ?? null,
  };
}

export function serializeWorkspace(w: Workspace) {
  return { id: w.id, name: w.name, slug: w.slug, plan: w.plan, tier: w.tier, data_region: w.data_region, dpa_signed_at: w.dpa_signed_at };
}

export function serializeApiKey(k: ApiKey) {
  return {
    id: k.id,
    name: k.name,
    key_prefix: k.key_prefix,
    scopes: k.scopes,
    created_at: k.created_at,
    last_used_at: k.last_used_at,
    expires_at: k.expires_at,
    revoked_at: k.revoked_at,
  };
}

export function serializeWebhook(e: WebhookEndpoint) {
  return { id: e.id, url: e.url, events: e.events, active: e.active, created_at: e.created_at, updated_at: e.updated_at };
}

export function serializePublication(p: Publication) {
  return {
    id: p.id,
    clip_id: p.clip_id,
    connection_id: p.connection_id,
    platform: p.platform,
    status: p.status,
    scheduled_for: p.scheduled_for,
    caption: p.caption,
    title: p.title,
    external_id: p.external_id,
    external_url: p.external_url,
    error: p.error,
    published_at: p.published_at,
    metrics: p.metrics,
    metrics_fetched_at: p.metrics_fetched_at,
    created_at: p.created_at,
  };
}
