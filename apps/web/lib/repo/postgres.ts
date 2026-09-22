import { withContext, type Tx } from "@/lib/db";
import { getSession } from "@/lib/session";
import type {
  BrandProfile,
  Candidate,
  CaptionVersion,
  Clip,
  HookVersion,
  PipelineEvent,
  Repo,
  Source,
  TranscriptVersion,
  Workspace,
} from "@/lib/repo/types";
import { sentencesFromWords } from "@/lib/transcript/sentences";
import { buildRevision, isRevisionError } from "@/lib/candidates/revise";
import { PLATFORM_ASPECT } from "@/lib/clips/presets";
import { adLabelFor, lintProfileFrom } from "@/lib/clips/render-demo";
import { prepareManualHook } from "@/lib/copy/hooks";

/* Postgres-Repository. Alle Zugriffe laufen in einer Transaktion mit RLS-Kontext (lib/db.ts). */

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
    caption_preset: r.caption_preset as BrandProfile["caption_preset"],
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
    cps_warnings: jsonValue<string[]>(r.cps_warnings, []),
    duration_s: num(r.duration_s),
    width: num(r.width),
    height: num(r.height),
    fps: num(r.fps),
    loudness: jsonValue<Clip["loudness"]>(r.loudness, null),
    provenance: jsonValue<Clip["provenance"]>(r.provenance, {}),
    render_error: (r.render_error as string | null) ?? null,
    rendered_at: isoOrNull(r.rendered_at),
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

async function ensureWorkspace(tx: Tx, workspaceId: string): Promise<Workspace> {
  const rows = await tx`select * from workspaces where id = ${workspaceId}`;
  if (rows.length > 0) return rows[0] as unknown as Workspace;
  /* Entwicklung: der Dev-Workspace wird beim ersten Zugriff angelegt (RLS: with check über id) */
  const inserted = await tx`
    insert into workspaces (id, name, slug) values (${workspaceId}, 'Entwicklung', 'dev')
    on conflict (id) do nothing
    returning *`;
  if (inserted.length > 0) return inserted[0] as unknown as Workspace;
  const again = await tx`select * from workspaces where id = ${workspaceId}`;
  return again[0] as unknown as Workspace;
}

export const postgresRepo: Repo = {
  kind: "postgres",

  async getWorkspace() {
    const session = getSession();
    return withContext(session, async (tx) => {
      const ws = await ensureWorkspace(tx, session.workspaceId);
      return {
        ...ws,
        dpa_signed_at: isoOrNull(ws.dpa_signed_at),
        created_at: isoOrNull(ws.created_at) ?? "",
      };
    });
  },

  async listBrandProfiles() {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from brand_profiles order by created_at asc`;
      return rows.map((r) => toBrand(r as Row));
    });
  },

  async getBrandProfile(id) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from brand_profiles where id = ${id}`;
      return rows.length ? toBrand(rows[0] as Row) : null;
    });
  },

  async saveBrandProfile(input) {
    const session = getSession();
    return withContext(session, async (tx) => {
      await ensureWorkspace(tx, session.workspaceId);
      if (input.id) {
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
            caption_preset = ${input.caption_preset},
            ci = ${tx.json((input.ci ?? {}) as never)},
            caption_style = ${tx.json((input.caption_style ?? {}) as never)},
            version = version + 1
          where id = ${input.id}
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
          ${input.tone_adjectives}, ${input.default_platform}, ${input.caption_preset},
          ${tx.json((input.ci ?? {}) as never)}, ${tx.json((input.caption_style ?? {}) as never)}
        ) returning *`;
      return toBrand(rows[0] as Row);
    });
  },

  async addBrandVocab(profileId, words) {
    if (words.length === 0) return;
    await withContext(getSession(), async (tx) => {
      await tx`
        update brand_profiles
        set brand_vocab = (
          select array_agg(distinct w) from unnest(brand_vocab || ${words}::text[]) as w
        )
        where id = ${profileId}`;
    });
  },

  async listSources() {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`
        select * from sources where status <> 'deleted' order by created_at desc`;
      return rows.map((r) => toSource(r as Row));
    });
  },

  async getSource(id) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from sources where id = ${id}`;
      return rows.length ? toSource(rows[0] as Row) : null;
    });
  },

  async createSource(input) {
    const session = getSession();
    return withContext(session, async (tx) => {
      const ws = await ensureWorkspace(tx, session.workspaceId);
      const rows = await tx`
        insert into sources (
          id, workspace_id, brand_profile_id, title, original_filename, mime_type, size_bytes,
          storage_key, rights_status, rights_confirmed_at, rights_confirmed_by, source_owner,
          source_title, source_url, expected_speakers, brief, status, delete_after, created_by
        ) values (
          ${input.id ?? tx`gen_random_uuid()`}, ${session.workspaceId}, ${input.brand_profile_id},
          ${input.title}, ${input.original_filename}, ${input.mime_type}, ${input.size_bytes},
          ${input.storage_key}, ${input.rights_status}, now(), ${input.rights_confirmed_by ?? session.actorId},
          ${input.source_owner ?? null}, ${input.source_title ?? null}, ${input.source_url ?? null},
          ${input.expected_speakers}, ${tx.json((input.brief ?? {}) as never)}, ${input.status ?? "uploaded"},
          now() + make_interval(days => ${ws.retention_days}), ${session.actorId}
        ) returning *`;
      return toSource(rows[0] as Row);
    });
  },

  async updateSource(id, patch) {
    return withContext(getSession(), async (tx) => {
      const allowed: (keyof Source)[] = ["status", "status_message", "temporal_workflow_id", "title"];
      const data: Record<string, unknown> = {};
      for (const key of allowed) {
        if (key in patch) data[key] = patch[key];
      }
      if (Object.keys(data).length === 0) {
        const rows = await tx`select * from sources where id = ${id}`;
        return rows.length ? toSource(rows[0] as Row) : null;
      }
      const rows = await tx`update sources set ${tx(data)} where id = ${id} returning *`;
      return rows.length ? toSource(rows[0] as Row) : null;
    });
  },

  async listPipelineEvents(sourceId, afterId = 0) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`
        select * from pipeline_events where source_id = ${sourceId} and id > ${afterId} order by id asc`;
      return rows.map((r) => toEvent(r as Row));
    });
  },

  async getCurrentTranscript(sourceId) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from transcripts_current where source_id = ${sourceId}`;
      return rows.length ? toTranscript(rows[0] as Row) : null;
    });
  },

  async saveTranscript(sourceId, input) {
    const session = getSession();
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
          ${tx.json(words as never)}, ${tx.json(stats as never)}, ${session.actorId}
        ) returning *`;
      for (const c of input.corrections) {
        await tx`
          insert into transcript_corrections (source_id, from_version, word_index, old_text, new_text, add_to_vocab, created_by)
          values (${sourceId}, ${prev?.version ?? 0}, ${c.word_index}, ${c.old_text}, ${c.new_text}, ${c.add_to_vocab}, ${session.actorId})`;
      }
      return toTranscript(rows[0] as Row);
    });
  },

  async listCandidates(sourceId) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`
        select * from candidates
        where source_id = ${sourceId} and human_verdict is distinct from 'edited'
        order by gate_passed desc, total desc nulls last, created_at asc`;
      return rows.map((r) => toCandidate(r as Row));
    });
  },

  async getCandidate(id) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from candidates where id = ${id}`;
      return rows.length ? toCandidate(rows[0] as Row) : null;
    });
  },

  async setCandidateVerdict(id, verdict, reason) {
    const session = getSession();
    return withContext(session, async (tx) => {
      const rows = await tx`
        update candidates set
          human_verdict = ${verdict},
          verdict_reason = ${reason?.trim() || null},
          verdict_by = ${session.actorId},
          verdict_at = now()
        where id = ${id}
        returning *`;
      return rows.length ? toCandidate(rows[0] as Row) : null;
    });
  },

  async reviseCandidate(id, input) {
    const session = getSession();
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
        update candidates set human_verdict = 'edited', verdict_by = ${session.actorId}, verdict_at = now()
        where id = ${id}`;
      return toCandidate(rows[0] as Row);
    });
  },

  async countCandidates(sourceId) {
    return withContext(getSession(), async (tx) => {
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

  async createClips(candidateId, platforms) {
    const session = getSession();
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
            ${source.id}, ${candidate.id}, ${platform}, ${platform}, ${PLATFORM_ASPECT[platform]},
            ${tx.json(candidate.segments as never)}, ${candidate.rubric.suggested_title_card?.trim() || null},
            ${adLabelFor(source, brand)}, 'draft', ${session.actorId}
          ) returning *`;
        out.push(toClip(rows[0] as Row));
      }
      return out;
    });
  },

  async listClips(sourceId) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from clips where source_id = ${sourceId} order by created_at asc`;
      return rows.map((r) => toClip(r as Row));
    });
  },

  async getClip(id) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from clips where id = ${id}`;
      return rows.length ? toClip(rows[0] as Row) : null;
    });
  },

  async updateClip(id, patch) {
    return withContext(getSession(), async (tx) => {
      const scalar: (keyof Clip)[] = ["status", "title_card", "ad_label", "render_error", "destination"];
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

  /* Der Worker setzt status = 'rendering' nach dem Signal; hier nur der Fehlertext zurücksetzen */
  async requestClipRender(id) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`update clips set render_error = null where id = ${id} returning *`;
      return rows.length ? toClip(rows[0] as Row) : null;
    });
  },

  async countClips(sourceId) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`
        select
          count(*)::int as total,
          count(*) filter (where status in ('rendered', 'exported'))::int as rendered,
          count(*) filter (where status = 'rendering')::int as rendering,
          count(*) filter (where status = 'failed')::int as failed
        from clips where source_id = ${sourceId}`;
      const r = (rows[0] ?? {}) as Row;
      return { total: num(r.total) ?? 0, rendered: num(r.rendered) ?? 0, rendering: num(r.rendering) ?? 0, failed: num(r.failed) ?? 0 };
    });
  },

  async getCurrentHook(clipId) {
    return withContext(getSession(), async (tx) => currentHookRow(tx, clipId));
  },

  async listHookVersions(clipId) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from hook_versions where clip_id = ${clipId} order by version asc`;
      return rows.map((r) => toHook(r as Row));
    });
  },

  async saveHook(clipId, input) {
    const session = getSession();
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
          ${f.prompt_version}, ${session.actorId}
        ) returning *`;
      return toHook(rows[0] as Row);
    });
  },

  async getCurrentCaptions(clipId) {
    return withContext(getSession(), async (tx) => {
      const rows = await tx`select * from caption_versions where clip_id = ${clipId} order by version desc limit 1`;
      return rows.length ? toCaptions(rows[0] as Row) : null;
    });
  },

  async audit(entry) {
    const session = getSession();
    await withContext(session, async (tx) => {
      await tx`
        insert into audit_log (workspace_id, actor_id, actor_type, action, entity, entity_id, payload)
        values (${session.workspaceId}, ${session.actorId}, ${entry.actor_type ?? "user"}, ${entry.action},
                ${entry.entity}, ${entry.entity_id}, ${tx.json((entry.payload ?? {}) as never)})`;
    });
  },
};
