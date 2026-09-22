import { withContext, type Tx } from "@/lib/db";
import { getSession } from "@/lib/session";
import type {
  BrandProfile,
  Candidate,
  PipelineEvent,
  Repo,
  Source,
  TranscriptVersion,
  Workspace,
} from "@/lib/repo/types";
import { sentencesFromWords } from "@/lib/transcript/sentences";
import { buildRevision, isRevisionError } from "@/lib/candidates/revise";

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
            version = version + 1
          where id = ${input.id}
          returning *`;
        if (rows.length) return toBrand(rows[0] as Row);
      }
      const rows = await tx`
        insert into brand_profiles (
          workspace_id, name, address, country, gender_mode, asr_variant, brand_vocab,
          protected_terms, banned_phrases, tone_adjectives, default_platform, caption_preset
        ) values (
          ${session.workspaceId}, ${input.name}, ${input.address}, ${input.country}, ${input.gender_mode},
          ${input.asr_variant}, ${input.brand_vocab}, ${input.protected_terms}, ${input.banned_phrases},
          ${input.tone_adjectives}, ${input.default_platform}, ${input.caption_preset}
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
