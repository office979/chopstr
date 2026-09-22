import type {
  AuditEntry,
  BrandProfile,
  PipelineEvent,
  Repo,
  Source,
  TranscriptVersion,
  Workspace,
} from "@/lib/repo/types";
import {
  DEMO_IDS,
  buildSeedTranscript,
  seedBrandProfile,
  seedKeynoteEvents,
  seedPodcastEvents,
  seedSources,
  seedWorkspace,
} from "@/lib/repo/seed";
import { getSession } from "@/lib/session";

/* In-Memory-Repository für den Demo-Modus. Überlebt Hot Reloads über globalThis. */

interface DemoState {
  workspace: Workspace;
  brandProfiles: BrandProfile[];
  sources: Source[];
  events: PipelineEvent[];
  transcripts: TranscriptVersion[];
  audit: (AuditEntry & { at: string; workspace_id: string; actor_id: string })[];
  nextEventId: number;
  bootedAt: number;
  /* Simulationen laufender Pipelines: sourceId -> Startzeit */
  simulations: Map<string, number>;
}

declare global {
  var __chopstrDemoState: DemoState | undefined;
}

function createState(): DemoState {
  const events: PipelineEvent[] = [];
  let id = 1;
  for (const e of [...seedPodcastEvents, ...seedKeynoteEvents]) {
    events.push({ ...e, id: id++ });
  }
  const now = Date.now();
  return {
    workspace: seedWorkspace,
    brandProfiles: [seedBrandProfile],
    sources: seedSources.map((s) => ({ ...s })),
    events,
    transcripts: [buildSeedTranscript()],
    audit: [],
    nextEventId: id,
    bootedAt: now,
    simulations: new Map([[DEMO_IDS.keynote, now - 60_000]]),
  };
}

function state(): DemoState {
  if (!globalThis.__chopstrDemoState) {
    globalThis.__chopstrDemoState = createState();
  }
  return globalThis.__chopstrDemoState;
}

const uuid = () => globalThis.crypto.randomUUID();
const nowIso = () => new Date().toISOString();

/* Simulierte Pipeline: Fortschritt anhand der vergangenen Zeit, damit SSE und Statusseiten Leben zeigen */
interface SimPhase {
  step: PipelineEvent["step"];
  status: Source["status"];
  duration: number; // Sekunden
  startMessage: string;
  endMessage: string;
}

const SIM_PHASES: SimPhase[] = [
  { step: "probe_and_extract", status: "ingesting", duration: 12, startMessage: "Datei wird geprüft", endMessage: "Prüfung abgeschlossen" },
  { step: "transcribe_de", status: "transcribing", duration: 70, startMessage: "whisper-large-v3-turbo-german", endMessage: "Transkription abgeschlossen" },
  { step: "diarize", status: "analyzing", duration: 25, startMessage: "Sprecher werden getrennt", endMessage: "Sprecher erkannt" },
  { step: "fuse_and_nlp", status: "analyzing", duration: 18, startMessage: "dach_nlp", endMessage: "Sätze, Füllwörter und Verneinungen markiert" },
];

function pushEvent(s: DemoState, e: Omit<PipelineEvent, "id" | "at">, at = nowIso()) {
  s.events.push({ ...e, id: s.nextEventId++, at });
}

function advanceSimulation(sourceId: string) {
  const s = state();
  const startedAt = s.simulations.get(sourceId);
  if (startedAt == null) return;
  const source = s.sources.find((x) => x.id === sourceId);
  if (!source) return;

  const elapsed = (Date.now() - startedAt) / 1000;
  const has = (step: string, status: string) =>
    s.events.some((e) => e.source_id === sourceId && e.step === step && e.status === status);

  let offset = 0;
  for (const phase of SIM_PHASES) {
    const phaseStart = offset;
    const phaseEnd = offset + phase.duration;
    offset = phaseEnd;
    if (elapsed < phaseStart) return;

    if (!has(phase.step, "started")) {
      pushEvent(s, { source_id: sourceId, step: phase.step, status: "started", progress: 0, message: phase.startMessage, payload: null });
      source.status = phase.status;
      source.status_message = phase.startMessage;
      source.updated_at = nowIso();
    }
    if (elapsed < phaseEnd) {
      const progress = Math.min(0.99, (elapsed - phaseStart) / phase.duration);
      const last = [...s.events].reverse().find((e) => e.source_id === sourceId && e.step === phase.step);
      if (!last || last.status === "started" || (last.progress ?? 0) + 0.04 < progress) {
        pushEvent(s, {
          source_id: sourceId,
          step: phase.step,
          status: "progress",
          progress: Number(progress.toFixed(2)),
          message: phase.step === "transcribe_de" && source.duration_s
            ? `Minute ${Math.floor((source.duration_s / 60) * progress)} von ${Math.round(source.duration_s / 60)}`
            : `${Math.round(progress * 100)} %`,
          payload: null,
        });
      }
      return;
    }
    if (!has(phase.step, "finished")) {
      pushEvent(s, { source_id: sourceId, step: phase.step, status: "finished", progress: 1, message: phase.endMessage, payload: null });
      if (phase.step === "probe_and_extract") {
        source.duration_s ??= 1520;
        source.width ??= 1920;
        source.height ??= 1080;
        source.fps ??= 25;
        source.sha256 ??= `${uuid().replace(/-/g, "")}${uuid().replace(/-/g, "")}`.slice(0, 64);
      }
    }
  }
  if (!has("detect_candidates", "skipped")) {
    pushEvent(s, { source_id: sourceId, step: "detect_candidates", status: "skipped", progress: null, message: "Kommt in Phase 2", payload: null });
    source.status = "ready";
    source.status_message = "Ohne Transkript (Demo)";
    source.updated_at = nowIso();
    s.simulations.delete(sourceId);
  }
}

export const demoRepo: Repo = {
  kind: "demo",

  async getWorkspace() {
    return state().workspace;
  },

  async listBrandProfiles() {
    return state().brandProfiles;
  },

  async getBrandProfile(id) {
    return state().brandProfiles.find((b) => b.id === id) ?? null;
  },

  async saveBrandProfile(input) {
    const s = state();
    const existing = input.id ? s.brandProfiles.find((b) => b.id === input.id) : undefined;
    if (existing) {
      Object.assign(existing, input, { version: existing.version + 1, updated_at: nowIso() });
      return existing;
    }
    const created: BrandProfile = {
      ...input,
      id: uuid(),
      workspace_id: s.workspace.id,
      version: 1,
      created_at: nowIso(),
      updated_at: nowIso(),
    };
    s.brandProfiles.push(created);
    return created;
  },

  async addBrandVocab(profileId, words) {
    const b = state().brandProfiles.find((x) => x.id === profileId);
    if (!b) return;
    for (const w of words) {
      if (w && !b.brand_vocab.includes(w)) b.brand_vocab.push(w);
    }
    b.updated_at = nowIso();
  },

  async listSources() {
    const s = state();
    for (const id of s.simulations.keys()) advanceSimulation(id);
    return [...s.sources]
      .filter((x) => x.status !== "deleted")
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  async getSource(id) {
    advanceSimulation(id);
    return state().sources.find((x) => x.id === id) ?? null;
  },

  async createSource(input) {
    const s = state();
    const { actorId } = getSession();
    const now = nowIso();
    const source: Source = {
      id: input.id ?? uuid(),
      workspace_id: s.workspace.id,
      brand_profile_id: input.brand_profile_id,
      title: input.title,
      original_filename: input.original_filename,
      mime_type: input.mime_type,
      size_bytes: input.size_bytes,
      sha256: null,
      storage_key: input.storage_key,
      proxy_key: null,
      duration_s: null,
      width: null,
      height: null,
      fps: null,
      rights_status: input.rights_status,
      rights_confirmed_at: now,
      rights_confirmed_by: input.rights_confirmed_by ?? actorId,
      source_owner: input.source_owner ?? null,
      source_title: input.source_title ?? null,
      source_url: input.source_url ?? null,
      expected_speakers: input.expected_speakers,
      brief: input.brief,
      status: input.status ?? "uploaded",
      status_message: null,
      temporal_workflow_id: null,
      delete_after: new Date(Date.now() + s.workspace.retention_days * 86_400_000).toISOString(),
      created_by: actorId,
      created_at: now,
      updated_at: now,
    };
    s.sources.push(source);
    s.simulations.set(source.id, Date.now());
    return source;
  },

  async updateSource(id, patch) {
    const src = state().sources.find((x) => x.id === id);
    if (!src) return null;
    Object.assign(src, patch, { updated_at: nowIso() });
    return src;
  },

  async listPipelineEvents(sourceId, afterId = 0) {
    advanceSimulation(sourceId);
    return state().events.filter((e) => e.source_id === sourceId && e.id > afterId);
  },

  async getCurrentTranscript(sourceId) {
    const versions = state().transcripts.filter((t) => t.source_id === sourceId);
    if (versions.length === 0) return null;
    return versions.reduce((a, b) => (a.version >= b.version ? a : b));
  },

  async saveTranscript(sourceId, input) {
    const s = state();
    const { actorId } = getSession();
    const current = await this.getCurrentTranscript(sourceId);
    const words = input.words;
    const lowConf = words.filter((w) => w.prob < 0.9).length;
    const mean = words.length ? words.reduce((acc, w) => acc + w.prob, 0) / words.length : 0;
    const version: TranscriptVersion = {
      id: uuid(),
      source_id: sourceId,
      version: (current?.version ?? 0) + 1,
      origin: "manual",
      asr_model_id: current?.asr_model_id ?? null,
      asr_variant: current?.asr_variant ?? null,
      diarizer_id: current?.diarizer_id ?? null,
      language: current?.language ?? "de",
      words,
      stats: {
        word_count: words.length,
        speakers: new Set(words.map((w) => w.speaker)).size,
        mean_prob: Number(mean.toFixed(3)),
        low_conf_ratio: words.length ? Number((lowConf / words.length).toFixed(3)) : 0,
        speaker_names: input.speaker_names,
      },
      created_by: actorId,
      created_at: nowIso(),
    };
    s.transcripts.push(version);
    return version;
  },

  async audit(entry) {
    const { workspaceId, actorId } = getSession();
    state().audit.push({ ...entry, at: nowIso(), workspace_id: workspaceId, actor_id: actorId });
  },
};
