import type {
  AuditEntry,
  BrandProfile,
  Candidate,
  CaptionVersion,
  Clip,
  HookVersion,
  PipelineEvent,
  RenderStage,
  Repo,
  Source,
  TranscriptVersion,
  Workspace,
} from "@/lib/repo/types";
import {
  DEMO_IDS,
  buildSeedCandidates,
  buildSeedTranscript,
  seedBrandProfile,
  seedKeynoteEvents,
  seedPodcastEvents,
  seedSources,
  seedWorkspace,
} from "@/lib/repo/seed";
import { getSession } from "@/lib/session";
import { sentencesFromWords } from "@/lib/transcript/sentences";
import { buildRevision, isRevisionError } from "@/lib/candidates/revise";
import { PLATFORM_ASPECT } from "@/lib/clips/presets";
import { PLATFORM_LABELS, RENDER_STAGE_LABELS } from "@/lib/clips/labels";
import {
  adLabelFor,
  buildDemoCaptions,
  buildDemoHookV1,
  buildDemoRenderPatch,
  buildDemoRenderPlan,
  lintProfileFrom,
} from "@/lib/clips/render-demo";
import { prepareManualHook } from "@/lib/copy/hooks";

/* In-Memory-Repository für den Demo-Modus. Überlebt Hot Reloads über globalThis. */

interface DemoState {
  workspace: Workspace;
  brandProfiles: BrandProfile[];
  sources: Source[];
  events: PipelineEvent[];
  transcripts: TranscriptVersion[];
  candidates: Candidate[];
  clips: Clip[];
  hooks: HookVersion[];
  captions: CaptionVersion[];
  audit: (AuditEntry & { at: string; workspace_id: string; actor_id: string })[];
  nextEventId: number;
  bootedAt: number;
  /* Simulationen laufender Pipelines: sourceId -> Startzeit */
  simulations: Map<string, number>;
  /* Simulierte Renders: clipId -> Zustand */
  renders: Map<string, RenderSim>;
}

interface RenderSim {
  clipId: string;
  sourceId: string;
  startedAt: number;
  /* Index der zuletzt gemeldeten Stufe, -1 = noch kein started-Ereignis */
  stage: number;
  lastProgress: number;
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
    candidates: buildSeedCandidates(),
    clips: [],
    hooks: [],
    captions: [],
    audit: [],
    nextEventId: id,
    bootedAt: now,
    simulations: new Map([[DEMO_IDS.keynote, now - 60_000]]),
    renders: new Map(),
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
  { step: "detect_candidates", status: "scoring", duration: 20, startMessage: "Story-Engine: Vorschlag, Rubrik, Story-Graph", endMessage: "Keine Kandidaten (Demo ohne Transkript)" },
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
  if (source.status !== "ready") {
    source.status = "ready";
    source.status_message = "Ohne Transkript (Demo)";
    source.updated_at = nowIso();
    s.simulations.delete(sourceId);
  }
}


/* Simulierter Render (Demo): draft → rendering → rendered in etwa 6 Sekunden, Ereignisse step = 'render'
 * mit Fortschritt je Schritt (copy, reframe, captions, encode, provenance). Beim Abschluss entstehen
 * render_plan, loudness, provenance, hook_versions v1 (falls keine Version existiert) und caption_versions n+1. */
const RENDER_SIM_STAGES: { stage: RenderStage; duration: number }[] = [
  { stage: "copy", duration: 1.2 },
  { stage: "reframe", duration: 1.4 },
  { stage: "captions", duration: 1.2 },
  { stage: "encode", duration: 1.4 },
  { stage: "provenance", duration: 0.8 },
];
const RENDER_SIM_TOTAL = RENDER_SIM_STAGES.reduce((acc, s) => acc + s.duration, 0);

function startRenderSimulation(clip: Clip, delayMs: number) {
  state().renders.set(clip.id, { clipId: clip.id, sourceId: clip.source_id, startedAt: Date.now() + delayMs, stage: -1, lastProgress: 0 });
}

function currentHookOf(clipId: string): HookVersion | null {
  const versions = state().hooks.filter((h) => h.clip_id === clipId);
  if (versions.length === 0) return null;
  return versions.reduce((a, b) => (a.version >= b.version ? a : b));
}

function currentCaptionsOf(clipId: string): CaptionVersion | null {
  const versions = state().captions.filter((c) => c.clip_id === clipId);
  if (versions.length === 0) return null;
  return versions.reduce((a, b) => (a.version >= b.version ? a : b));
}

function finishRenderSimulation(s: DemoState, clip: Clip) {
  const source = s.sources.find((x) => x.id === clip.source_id);
  const candidate = clip.candidate_id ? s.candidates.find((c) => c.id === clip.candidate_id) : undefined;
  if (!source || !candidate) {
    Object.assign(clip, { status: "failed", render_error: "Kandidat oder Quelle nicht mehr vorhanden", updated_at: nowIso() });
    pushEvent(s, { source_id: clip.source_id, step: "render", status: "failed", progress: null, message: clip.render_error, payload: { clip_id: clip.id, platform: clip.platform } });
    return;
  }
  const brand = source.brand_profile_id ? s.brandProfiles.find((b) => b.id === source.brand_profile_id) ?? null : null;
  const transcripts = s.transcripts.filter((t) => t.source_id === source.id);
  const transcript = transcripts.length ? transcripts.reduce((a, b) => (a.version >= b.version ? a : b)) : null;
  const { actorId } = getSession();

  let hook = currentHookOf(clip.id);
  if (!hook) {
    hook = { ...buildDemoHookV1(candidate, source, brand, clip), id: uuid(), clip_id: clip.id, version: 1, created_by: null, created_at: nowIso() };
    s.hooks.push(hook);
  }
  const captionFields = buildDemoCaptions(clip, candidate, transcript?.words ?? null, brand);
  const prevCaptions = currentCaptionsOf(clip.id);
  s.captions.push({ ...captionFields, id: uuid(), clip_id: clip.id, version: (prevCaptions?.version ?? 0) + 1, created_by: null, created_at: nowIso() });

  const plan = buildDemoRenderPlan(clip, candidate, source, hook, captionFields, transcript?.version ?? 0);
  Object.assign(clip, buildDemoRenderPatch(clip, source, brand, plan, captionFields), { updated_at: nowIso() });
  if (!clip.created_by) clip.created_by = actorId;
  pushEvent(s, {
    source_id: clip.source_id,
    step: "render",
    status: "finished",
    progress: 1,
    message: `Gerendert: ${clip.width}×${clip.height}, ${clip.fps} fps, ${(clip.duration_s ?? 0).toLocaleString("de-AT", { maximumFractionDigits: 1 })} s`,
    payload: { clip_id: clip.id, platform: clip.platform, stage: "provenance", cards: captionFields.cards.length, c2pa: "skipped" },
  });
}

function advanceRenderSimulations(sourceId: string) {
  const s = state();
  for (const sim of [...s.renders.values()]) {
    if (sim.sourceId !== sourceId) continue;
    const clip = s.clips.find((c) => c.id === sim.clipId);
    if (!clip) {
      s.renders.delete(sim.clipId);
      continue;
    }
    const elapsed = (Date.now() - sim.startedAt) / 1000;
    if (elapsed < 0) continue;
    if (sim.stage < 0) {
      pushEvent(s, {
        source_id: sourceId,
        step: "render",
        status: "started",
        progress: 0,
        message: `Render ${PLATFORM_LABELS[clip.platform]} (${clip.aspect}) gestartet`,
        payload: { clip_id: clip.id, platform: clip.platform, stage: "copy" },
      });
      Object.assign(clip, { status: "rendering", render_error: null, updated_at: nowIso() });
      sim.stage = 0;
    }
    if (elapsed >= RENDER_SIM_TOTAL) {
      finishRenderSimulation(s, clip);
      s.renders.delete(sim.clipId);
      continue;
    }
    let offset = 0;
    let stageIndex = 0;
    for (let i = 0; i < RENDER_SIM_STAGES.length; i += 1) {
      if (elapsed >= offset) stageIndex = i;
      offset += RENDER_SIM_STAGES[i].duration;
    }
    const progress = Math.min(0.99, elapsed / RENDER_SIM_TOTAL);
    if (stageIndex > sim.stage || progress >= sim.lastProgress + 0.08) {
      const stage = RENDER_SIM_STAGES[stageIndex].stage;
      pushEvent(s, {
        source_id: sourceId,
        step: "render",
        status: "progress",
        progress: Number(progress.toFixed(2)),
        message: `${RENDER_STAGE_LABELS[stage]} (${Math.round(progress * 100)} %)`,
        payload: { clip_id: clip.id, platform: clip.platform, stage },
      });
      sim.stage = Math.max(sim.stage, stageIndex);
      sim.lastProgress = progress;
    }
  }
}

/* Aktuelle Kandidaten-Versionen: Zeilen mit human_verdict = 'edited' sind durch eine neue Version ersetzt */
function currentCandidates(sourceId: string): Candidate[] {
  return state()
    .candidates.filter((c) => c.source_id === sourceId && c.human_verdict !== "edited")
    .sort((a, b) => {
      if (a.gate_passed !== b.gate_passed) return a.gate_passed ? -1 : 1;
      return (b.total ?? -1) - (a.total ?? -1) || a.created_at.localeCompare(b.created_at);
    });
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
    advanceRenderSimulations(sourceId);
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

  async listCandidates(sourceId) {
    return currentCandidates(sourceId).map((c) => ({ ...c }));
  },

  async getCandidate(id) {
    const c = state().candidates.find((x) => x.id === id);
    return c ? { ...c } : null;
  },

  async setCandidateVerdict(id, verdict, reason) {
    const c = state().candidates.find((x) => x.id === id);
    if (!c) return null;
    const { actorId } = getSession();
    c.human_verdict = verdict;
    c.verdict_reason = reason?.trim() || null;
    c.verdict_by = actorId;
    c.verdict_at = nowIso();
    return { ...c };
  },

  async reviseCandidate(id, input) {
    const s = state();
    const prev = s.candidates.find((x) => x.id === id);
    if (!prev) return null;
    const transcript = await this.getCurrentTranscript(prev.source_id);
    if (!transcript) throw new Error("Kein Transkript vorhanden");
    const revision = buildRevision(prev, sentencesFromWords(transcript.words), input);
    if (isRevisionError(revision)) throw new Error(revision.error);
    const { actorId } = getSession();
    const created: Candidate = { ...revision, id: uuid(), created_at: nowIso() };
    prev.human_verdict = "edited";
    prev.verdict_by = actorId;
    prev.verdict_at = created.created_at;
    s.candidates.push(created);
    return { ...created };
  },

  async countCandidates(sourceId) {
    const list = currentCandidates(sourceId);
    return {
      total: list.length,
      gate_passed: list.filter((c) => c.gate_passed).length,
      accepted: list.filter((c) => c.human_verdict === "accepted").length,
      rejected: list.filter((c) => c.human_verdict === "rejected").length,
    };
  },


  async createClips(candidateId, platforms) {
    const s = state();
    const candidate = s.candidates.find((c) => c.id === candidateId);
    if (!candidate) throw new Error("Kandidat nicht gefunden");
    const source = s.sources.find((x) => x.id === candidate.source_id);
    if (!source) throw new Error("Projekt nicht gefunden");
    const brand = source.brand_profile_id ? s.brandProfiles.find((b) => b.id === source.brand_profile_id) ?? null : null;
    const { actorId } = getSession();
    const out: Clip[] = [];
    platforms.forEach((platform, i) => {
      const existing = s.clips.find((c) => c.candidate_id === candidateId && c.platform === platform);
      if (existing) {
        out.push({ ...existing });
        return;
      }
      const now = nowIso();
      const clip: Clip = {
        id: uuid(),
        source_id: source.id,
        candidate_id: candidate.id,
        version: 1,
        platform,
        destination: platform,
        aspect: PLATFORM_ASPECT[platform],
        composition: candidate.segments.map((seg) => ({ ...seg })),
        kept_ranges: null,
        fidelity_warnings: [],
        speaker_positions: null,
        render_plan: null,
        title_card: candidate.rubric.suggested_title_card?.trim() || null,
        ad_label: adLabelFor(source, brand),
        ai_features: [],
        guest_approval_required: false,
        status: "draft",
        file_key: null,
        srt_key: null,
        vtt_key: null,
        poster_key: null,
        cps_warnings: [],
        duration_s: null,
        width: null,
        height: null,
        fps: null,
        loudness: null,
        provenance: {},
        render_error: null,
        rendered_at: null,
        created_by: actorId,
        created_at: now,
        updated_at: now,
      };
      s.clips.push(clip);
      /* Demo: Render startet nach kurzer Entwurfsphase, leicht versetzt je Plattform */
      startRenderSimulation(clip, 900 + i * 700);
      out.push({ ...clip });
    });
    return out;
  },

  async listClips(sourceId) {
    advanceRenderSimulations(sourceId);
    return state()
      .clips.filter((c) => c.source_id === sourceId)
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map((c) => ({ ...c }));
  },

  async getClip(id) {
    const c = state().clips.find((x) => x.id === id);
    if (!c) return null;
    advanceRenderSimulations(c.source_id);
    return { ...c };
  },

  async updateClip(id, patch) {
    const c = state().clips.find((x) => x.id === id);
    if (!c) return null;
    Object.assign(c, patch, { updated_at: nowIso() });
    return { ...c };
  },

  async requestClipRender(id) {
    const c = state().clips.find((x) => x.id === id);
    if (!c) return null;
    /* Demo: die Simulation ist der Worker, der Clip wechselt sofort in „Wird gerendert“ */
    c.render_error = null;
    c.status = "rendering";
    c.updated_at = nowIso();
    startRenderSimulation(c, 400);
    return { ...c };
  },

  async countClips(sourceId) {
    advanceRenderSimulations(sourceId);
    const list = state().clips.filter((c) => c.source_id === sourceId);
    return {
      total: list.length,
      rendered: list.filter((c) => c.status === "rendered" || c.status === "exported").length,
      rendering: list.filter((c) => c.status === "rendering").length,
      failed: list.filter((c) => c.status === "failed").length,
    };
  },

  async getCurrentHook(clipId) {
    const h = currentHookOf(clipId);
    return h ? { ...h } : null;
  },

  async listHookVersions(clipId) {
    return state()
      .hooks.filter((h) => h.clip_id === clipId)
      .sort((a, b) => a.version - b.version)
      .map((h) => ({ ...h }));
  },

  async saveHook(clipId, input) {
    const s = state();
    const clip = s.clips.find((c) => c.id === clipId);
    if (!clip) throw new Error("Clip nicht gefunden");
    const candidate = clip.candidate_id ? s.candidates.find((c) => c.id === clip.candidate_id) : undefined;
    const source = s.sources.find((x) => x.id === clip.source_id);
    const brand = source?.brand_profile_id ? s.brandProfiles.find((b) => b.id === source.brand_profile_id) ?? null : null;
    const prev = currentHookOf(clipId);
    const fields = prepareManualHook(input, { clipText: candidate?.rubric.text ?? "", profile: lintProfileFrom(brand) }, prev);
    const { actorId } = getSession();
    const version: HookVersion = { ...fields, id: uuid(), clip_id: clipId, version: (prev?.version ?? 0) + 1, created_by: actorId, created_at: nowIso() };
    s.hooks.push(version);
    return { ...version };
  },

  async getCurrentCaptions(clipId) {
    const c = currentCaptionsOf(clipId);
    return c ? { ...c } : null;
  },

  async audit(entry) {
    const { workspaceId, actorId } = getSession();
    state().audit.push({ ...entry, at: nowIso(), workspace_id: workspaceId, actor_id: actorId });
  },
};
