import type {
  AuditEntry,
  AuditRow,
  BrandAsset,
  BrandProfile,
  BrandProfileVersion,
  Candidate,
  CaptionVersion,
  Clip,
  DeletionJob,
  DpaAcceptance,
  GuestApproval,
  GuestApprovalView,
  HookVersion,
  LoginToken,
  Membership,
  PipelineEvent,
  Plan,
  RenderStage,
  Repo,
  SessionRow,
  Source,
  Subscription,
  TranscriptVersion,
  UsagePeriod,
  User,
  Workspace,
  WorkspaceInvite,
  WorkspaceMember,
  Zeitmarke,
} from "@/lib/repo/types";
import {
  DEMO_IDS,
  buildSeedCandidates,
  buildSeedTranscript,
  buildSeedWords,
  seedBrandProfile,
  seedKeynoteEvents,
  seedPodcastEvents,
  seedSources,
  seedWorkspace,
} from "@/lib/repo/seed";
import { currentSession } from "@/lib/session";
import { sentencesFromWords } from "@/lib/transcript/sentences";
import { buildRevision, isRevisionError } from "@/lib/candidates/revise";
import { aspectFor } from "@/lib/clips/presets";
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
  audit: (AuditEntry & { id: number; at: string; workspace_id: string; actor_id: string })[];
  nextAuditId: number;
  users: User[];
  sessions: SessionRow[];
  loginTokens: LoginToken[];
  members: MemberRow[];
  invites: WorkspaceInvite[];
  subscription: Subscription;
  usage: UsagePeriod;
  usageHistory: UsagePeriod[];
  guestApprovals: GuestApproval[];
  billingEventIds: Set<string>;
  dpaAcceptances: DpaAcceptance[];
  deletionJobs: DeletionJob[];
  brandAssets: BrandAsset[];
  brandVersions: BrandProfileVersion[];
  nextEventId: number;
  bootedAt: number;
  /* Simulationen laufender Pipelines: sourceId -> Startzeit */
  simulations: Map<string, number>;
  /* Simulierte Renders: clipId -> Zustand */
  renders: Map<string, RenderSim>;
}

interface MemberRow {
  workspace_id: string;
  user_id: string;
  role: WorkspaceMember["role"];
  brand_profile_id: string | null;
  invited_by: string | null;
  accepted_at: string | null;
  created_at: string;
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

/* Demo-Seed: drei Mitglieder (owner, editor, client mit Markenbindung) */
function seedUsers(): User[] {
  const created = new Date(Date.now() - 40 * 86_400_000).toISOString();
  return [
    { id: DEMO_IDS.actor, email: "demo@chopstr.local", email_verified_at: created, password_hash: null, display_name: "Demo", locale: "de-AT", last_login_at: new Date().toISOString(), created_at: created },
    { id: DEMO_IDS.editor, email: "mara@placemedia.test", email_verified_at: created, password_hash: null, display_name: "Mara Huber", locale: "de-AT", last_login_at: null, created_at: created },
    { id: DEMO_IDS.client, email: "kunde@kleinecke.test", email_verified_at: null, password_hash: null, display_name: "Kleinecke GmbH", locale: "de-DE", last_login_at: null, created_at: created },
  ];
}

function seedMembers(): MemberRow[] {
  const created = new Date(Date.now() - 40 * 86_400_000).toISOString();
  return [
    { workspace_id: DEMO_IDS.workspace, user_id: DEMO_IDS.actor, role: "owner", brand_profile_id: null, invited_by: null, accepted_at: created, created_at: created },
    { workspace_id: DEMO_IDS.workspace, user_id: DEMO_IDS.editor, role: "editor", brand_profile_id: null, invited_by: DEMO_IDS.actor, accepted_at: created, created_at: created },
    { workspace_id: DEMO_IDS.workspace, user_id: DEMO_IDS.client, role: "client", brand_profile_id: DEMO_IDS.brand, invited_by: DEMO_IDS.actor, accepted_at: null, created_at: created },
  ];
}

const DEMO_PLANS: Plan[] = [
  { code: "starter", name: "Starter", monthly_eur: 29, included_hours: 4, overage_eur_per_hour: 9, max_brand_profiles: 1, max_members: 2, features: { guest_approval: false, sovereign: false } },
  { code: "pro", name: "Pro", monthly_eur: 79, included_hours: 12, overage_eur_per_hour: 7.5, max_brand_profiles: 3, max_members: 5, features: { guest_approval: true, sovereign: false } },
  { code: "agency", name: "Agentur", monthly_eur: 199, included_hours: 40, overage_eur_per_hour: 6, max_brand_profiles: null, max_members: null, features: { guest_approval: true, sovereign: false, white_label: true } },
  { code: "sovereign", name: "Sovereign", monthly_eur: 399, included_hours: 40, overage_eur_per_hour: 6, max_brand_profiles: null, max_members: null, features: { guest_approval: true, sovereign: true, white_label: true } },
];

/* Zwei vergangene Monate mit Verbrauch (Demo-Verlauf auf der Abrechnungsseite) */
function seedUsageHistory(now: number): UsagePeriod[] {
  const d = new Date(now);
  const out: UsagePeriod[] = [];
  for (const [back, used, renders] of [
    [1, 262, 14],
    [2, 118, 6],
  ] as const) {
    const start = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - back, 1));
    const end = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - back + 1, 0));
    const overage = Math.max(0, used - 240);
    out.push({
      id: `77777777-7777-4777-8777-7777777777${10 + back}`,
      workspace_id: DEMO_IDS.workspace,
      period_start: start.toISOString().slice(0, 10),
      period_end: end.toISOString().slice(0, 10),
      included_minutes: 240,
      used_source_minutes: used,
      render_count: renders,
      overage_minutes: overage,
      overage_eur: Math.ceil(overage / 60) * 9,
      closed_at: end.toISOString(),
    });
  }
  return out;
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
    nextAuditId: 1,
    users: seedUsers(),
    sessions: [],
    loginTokens: [],
    members: seedMembers(),
    invites: [],
    subscription: {
      id: "77777777-7777-4777-8777-777777777701",
      workspace_id: DEMO_IDS.workspace,
      plan_code: "starter",
      provider: "manual",
      provider_customer_id: null,
      provider_subscription_id: null,
      status: "trialing",
      current_period_start: new Date(now).toISOString(),
      current_period_end: new Date(now + 14 * 86_400_000).toISOString(),
      trial_ends_at: new Date(now + 14 * 86_400_000).toISOString(),
      cancel_at_period_end: false,
      billing_email: "demo@chopstr.local",
      billing_address: { company: "PLACEMedia", street: "Beispielgasse 1", zip: "1010", city: "Wien", country: "AT", vat_id: "ATU12345678" },
      updated_at: new Date(now).toISOString(),
    },
    usage: {
      id: "77777777-7777-4777-8777-777777777702",
      workspace_id: DEMO_IDS.workspace,
      period_start: new Date(now).toISOString().slice(0, 8) + "01",
      period_end: new Date(Date.UTC(new Date(now).getUTCFullYear(), new Date(now).getUTCMonth() + 1, 0)).toISOString().slice(0, 10),
      included_minutes: 240,
      used_source_minutes: 103,
      render_count: 0,
      overage_minutes: 0,
      overage_eur: 0,
    },
    usageHistory: seedUsageHistory(now),
    guestApprovals: [],
    billingEventIds: new Set(),
    dpaAcceptances: [],
    deletionJobs: [],
    brandAssets: [],
    brandVersions: [],
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
  { step: "detect_candidates", status: "scoring", duration: 20, startMessage: "Gute Stellen werden gesucht", endMessage: "Clips gefunden" },
];

/* Demo: am Ende der Simulation bekommt ein hochgeladenes Video dieselbe Textgrundlage wie das
 * Beispielprojekt. Ohne das endete der Weg nach der Analyse im Nichts: Status „Fertig“, aber kein
 * Transkript und keine Clips, also nichts zum Auswählen und nichts zum Rendern.
 * Echte Transkription und echte Dateien liefert nur der lokale Stack (README, „Lokaler Testmodus“). */
function attachDemoAnalysis(s: DemoState, source: Source) {
  if (s.transcripts.some((t) => t.source_id === source.id)) return;
  const words = buildSeedWords();
  s.transcripts.push({
    ...buildSeedTranscript(),
    id: uuid(),
    source_id: source.id,
    created_at: nowIso(),
  });
  for (const c of buildSeedCandidates(words)) {
    s.candidates.push({ ...c, id: uuid(), source_id: source.id, created_at: nowIso() });
  }
  /* Dauer an den Text angleichen, sonst zeigt der Player eine Länge, zu der es keine Wörter gibt */
  const end = words.at(-1)?.end;
  if (end) source.duration_s = Math.ceil(end);
}

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
    attachDemoAnalysis(s, source);
    const found = s.candidates.filter((c) => c.source_id === sourceId).length;
    source.status = "ready";
    source.status_message = found === 1 ? "Ein Clip gefunden" : `${found} Clips gefunden`;
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
  const actorId = DEMO_IDS.actor;

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
      await snapshotBrand(existing);
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

  /* client sieht nur Quellen seiner Marke */
  async listSources(scope) {
    const s = state();
    const { brandScope } = await currentSession();
    const withDeleted = scope?.includeDeleted === true;
    for (const id of s.simulations.keys()) advanceSimulation(id);
    return [...s.sources]
      .filter((x) => (x.status !== "deleted" || withDeleted) && (!brandScope || x.brand_profile_id === brandScope))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  async getSource(id, scope) {
    advanceSimulation(id);
    const { brandScope } = await currentSession();
    const withDeleted = scope?.includeDeleted === true;
    const src = state().sources.find((x) => x.id === id && (x.status !== "deleted" || withDeleted)) ?? null;
    if (src && brandScope && src.brand_profile_id !== brandScope) return null;
    return src;
  },

  async createSource(input) {
    const s = state();
    const { userId: actorId } = await currentSession();
    const now = nowIso();
    const source: Source = {
      id: input.id ?? uuid(),
      workspace_id: s.workspace.id,
      brand_profile_id: input.brand_profile_id,
      title: input.title,
      original_filename: input.original_filename,
      mime_type: input.mime_type,
      size_bytes: input.size_bytes,
      sha256: input.sha256 ?? null,
      storage_key: input.storage_key,
      proxy_key: null,
      waveform_key: null,
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
    const { userId: actorId } = await currentSession();
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
    const { userId: actorId } = await currentSession();
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
    const { userId: actorId } = await currentSession();
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


  async createClips(candidateId, platforms, opts) {
    const s = state();
    const candidate = s.candidates.find((c) => c.id === candidateId);
    if (!candidate) throw new Error("Kandidat nicht gefunden");
    const source = s.sources.find((x) => x.id === candidate.source_id);
    if (!source) throw new Error("Projekt nicht gefunden");
    const brand = source.brand_profile_id ? s.brandProfiles.find((b) => b.id === source.brand_profile_id) ?? null : null;
    const { userId: actorId } = await currentSession();
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
        aspect: aspectFor(platform, source, opts?.keepSourceAspect),
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
        review: "offen",
        file_key: null,
        srt_key: null,
        vtt_key: null,
        poster_key: null,
        filmstrip_key: null,
        filmstrip_meta: null,
        zeitmarken: [],
        cps_warnings: [],
        duration_s: null,
        width: null,
        height: null,
        fps: null,
        loudness: null,
        provenance: {},
        render_error: null,
        rendered_at: null,
        /* In Postgres setzt das ein Trigger (Migration 0006); hier von Hand, sonst hätte der
         * Testmodus keine Frist am Clip und die Seite nach dem Löschen kein Datum. */
        delete_after: new Date(Date.now() + s.workspace.render_retention_days * 86_400_000).toISOString(),
        deleted_at: null,
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
      .clips.filter((c) => c.source_id === sourceId && c.status !== "deleted")
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map((c) => ({ ...c }));
  },

  async getClip(id) {
    const c = state().clips.find((x) => x.id === id && x.status !== "deleted");
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

  async resolveMediaBucket() {
    /* Demo: keine Dateien, die Medienroute antwortet 404 */
    return null;
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

  async listClipStands() {
    const st = state();
    /* Im Testmodus liegt der eigene Untertitelstil in einer eigenen Ablage (publishing-demo).
     * Gelesen wird er hier bewusst nicht: die Übersicht käme sonst an einen Stand, den die
     * Clip-Seite anders sieht. Ohne eigenen Stil gilt der Stil aus dem Renderplan, und das ist
     * genau das, was auch die Clip-Seite tut. */
    return st.clips
      .filter((c) => c.status !== "deleted" && !c.deleted_at)
      .map((c) => ({
        id: c.id,
        source_id: c.source_id,
        status: c.status,
        review: c.review,
        hat_datei: Boolean(c.file_key),
        composition: c.composition,
        zeitmarken: c.zeitmarken ?? [],
        cps_warnings: c.cps_warnings ?? [],
        fidelity_warnings: c.fidelity_warnings ?? [],
        render_error: c.render_error,
        plan_captions: (c.render_plan?.captions as unknown as Record<string, unknown>) ?? null,
        plan_segments: (c.render_plan?.segments as Clip["composition"]) ?? null,
        plan_zeitmarken: (c.render_plan?.zeitmarken as Zeitmarke[]) ?? null,
        plan_transcript_version: c.render_plan?.sources?.transcript_version ?? null,
        plan_output_height: c.render_plan?.output?.height ?? null,
        caption_style: null,
        transkript_version:
          st.transcripts.filter((t) => t.source_id === c.source_id).reduce((m, t) => Math.max(m, t.version), 0) || null,
      }));
  },

  async countClips(sourceId) {
    advanceRenderSimulations(sourceId);
    const list = state().clips.filter((c) => c.source_id === sourceId && c.status !== "deleted");
    return {
      total: list.length,
      rendered: list.filter((c) => c.status === "rendered" || c.status === "exported").length,
      rendering: list.filter((c) => c.status === "rendering").length,
      failed: list.filter((c) => c.status === "failed").length,
      offen: list.filter((c) => (c.status === "rendered" || c.status === "exported") && c.review === "offen").length,
      bereit: list.filter((c) => c.review === "bereit").length,
      verworfen: list.filter((c) => c.review === "verworfen").length,
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
    const { userId: actorId } = await currentSession();
    const version: HookVersion = { ...fields, id: uuid(), clip_id: clipId, version: (prev?.version ?? 0) + 1, created_by: actorId, created_at: nowIso() };
    s.hooks.push(version);
    return { ...version };
  },

  async getCurrentCaptions(clipId) {
    const c = currentCaptionsOf(clipId);
    return c ? { ...c } : null;
  },

  async audit(entry) {
    const { workspaceId, userId } = await currentSession();
    const s = state();
    s.audit.push({ ...entry, id: s.nextAuditId++, at: nowIso(), workspace_id: workspaceId, actor_id: userId });
  },

  /* ------------------------------------------------------------------------------------------
   * Auth und Verwaltung (Demo: In-Memory, ein Workspace, drei Mitglieder als Seed)
   * ---------------------------------------------------------------------------------------- */

  async auditAs(ctx, entry) {
    const s = state();
    s.audit.push({ ...entry, id: s.nextAuditId++, at: nowIso(), workspace_id: ctx.workspace_id ?? s.workspace.id, actor_id: ctx.actor_id ?? "" });
  },

  async findUserByEmail(email) {
    return state().users.find((u) => u.email.toLowerCase() === email.toLowerCase()) ?? null;
  },

  async getUser(id) {
    return state().users.find((u) => u.id === id) ?? null;
  },

  async createUser(input) {
    const user: User = {
      id: uuid(),
      email: input.email.toLowerCase(),
      email_verified_at: null,
      password_hash: input.password_hash,
      display_name: input.display_name,
      locale: input.locale ?? "de-AT",
      last_login_at: null,
      created_at: nowIso(),
    };
    state().users.push(user);
    return user;
  },

  async updateUser(id, patch) {
    const u = state().users.find((x) => x.id === id);
    if (!u) return null;
    Object.assign(u, patch, patch.email ? { email: patch.email.toLowerCase() } : {});
    return { ...u };
  },

  async createSession(row) {
    state().sessions.push({ ...row, created_at: nowIso() });
  },

  async getSessionRow(id) {
    return state().sessions.find((x) => x.id === id) ?? null;
  },

  async touchSession(id, expiresAt) {
    const row = state().sessions.find((x) => x.id === id);
    if (row) row.expires_at = expiresAt;
  },

  async setSessionWorkspace(id, workspaceId) {
    const row = state().sessions.find((x) => x.id === id);
    if (row) row.workspace_id = workspaceId;
  },

  async deleteSession(id) {
    const s = state();
    s.sessions = s.sessions.filter((x) => x.id !== id);
  },

  async deleteUserSessions(userId, exceptId) {
    const s = state();
    const before = s.sessions.length;
    s.sessions = s.sessions.filter((x) => x.user_id !== userId || x.id === exceptId);
    return before - s.sessions.length;
  },

  async listUserSessions(userId) {
    return state().sessions.filter((x) => x.user_id === userId && Date.parse(x.expires_at) > Date.now());
  },

  async createLoginToken(row) {
    state().loginTokens.push({ ...row, used_at: null });
  },

  async consumeLoginToken(token, purpose) {
    const t = state().loginTokens.find((x) => x.token === token && x.purpose === purpose);
    if (!t || t.used_at || Date.parse(t.expires_at) <= Date.now()) return null;
    t.used_at = nowIso();
    return { ...t };
  },

  async listMemberships(userId) {
    const s = state();
    return s.members
      .filter((m) => m.user_id === userId)
      .map<Membership>((m) => ({
        workspace_id: m.workspace_id,
        workspace_name: s.workspace.name,
        workspace_slug: s.workspace.slug,
        role: m.role,
        brand_profile_id: m.brand_profile_id,
        accepted_at: m.accepted_at,
      }));
  },

  async getMembership(userId, workspaceId) {
    const all = await this.listMemberships(userId);
    return all.find((m) => m.workspace_id === workspaceId) ?? null;
  },

  async createWorkspaceWithOwner(input) {
    /* Demo: genau ein Workspace; der neue Nutzer wird owner des bestehenden */
    const s = state();
    s.members.push({ workspace_id: s.workspace.id, user_id: input.user_id, role: "owner", brand_profile_id: null, invited_by: null, accepted_at: nowIso(), created_at: nowIso() });
    return s.workspace;
  },

  async getInvite(token) {
    const i = state().invites.find((x) => x.token === token);
    return i ? { ...i } : null;
  },

  async acceptInvite(token, userId) {
    const s = state();
    const i = s.invites.find((x) => x.token === token);
    if (!i || i.accepted_at || Date.parse(i.expires_at) <= Date.now()) return false;
    i.accepted_at = nowIso();
    const existing = s.members.find((m) => m.user_id === userId && m.workspace_id === i.workspace_id);
    if (existing) {
      Object.assign(existing, { role: i.role, brand_profile_id: i.brand_profile_id, accepted_at: nowIso() });
    } else {
      s.members.push({ workspace_id: i.workspace_id, user_id: userId, role: i.role, brand_profile_id: i.brand_profile_id, invited_by: i.invited_by, accepted_at: nowIso(), created_at: nowIso() });
    }
    return true;
  },

  async updateWorkspace(patch) {
    const s = state();
    for (const key of ["name", "data_region", "retention_days", "render_retention_days"] as const) {
      if (patch[key] !== undefined) Object.assign(s.workspace, { [key]: patch[key] });
    }
    return { ...s.workspace };
  },

  async listMembers() {
    const s = state();
    return s.members.map<WorkspaceMember>((m) => {
      const u = s.users.find((x) => x.id === m.user_id);
      const b = m.brand_profile_id ? s.brandProfiles.find((x) => x.id === m.brand_profile_id) : undefined;
      return {
        user_id: m.user_id,
        email: u?.email ?? "",
        display_name: u?.display_name ?? null,
        role: m.role,
        brand_profile_id: m.brand_profile_id,
        brand_profile_name: b?.name ?? null,
        invited_by: m.invited_by,
        accepted_at: m.accepted_at,
        created_at: m.created_at,
        last_login_at: u?.last_login_at ?? null,
      };
    });
  },

  async updateMember(userId, patch) {
    const m = state().members.find((x) => x.user_id === userId);
    if (!m) return null;
    if (patch.role !== undefined) m.role = patch.role;
    if (patch.brand_profile_id !== undefined) m.brand_profile_id = patch.brand_profile_id;
    return (await this.listMembers()).find((x) => x.user_id === userId) ?? null;
  },

  async removeMember(userId) {
    const s = state();
    const before = s.members.length;
    s.members = s.members.filter((m) => m.user_id !== userId || m.role === "owner");
    return s.members.length < before;
  },

  async listInvites() {
    return state().invites.filter((i) => !i.accepted_at && Date.parse(i.expires_at) > Date.now());
  },

  async createInvite(input) {
    const s = state();
    const { userId, displayName } = await currentSession();
    const b = input.brand_profile_id ? s.brandProfiles.find((x) => x.id === input.brand_profile_id) : undefined;
    const invite: WorkspaceInvite = {
      token: uuid().replace(/-/g, "") + uuid().replace(/-/g, ""),
      workspace_id: s.workspace.id,
      workspace_name: s.workspace.name,
      email: input.email.toLowerCase(),
      role: input.role,
      brand_profile_id: input.brand_profile_id,
      brand_profile_name: b?.name ?? null,
      invited_by: userId,
      invited_by_name: displayName,
      expires_at: input.expires_at,
      accepted_at: null,
      created_at: nowIso(),
    };
    s.invites.push(invite);
    return { ...invite };
  },

  async revokeInvite(token) {
    const s = state();
    const before = s.invites.length;
    s.invites = s.invites.filter((i) => i.token !== token);
    return s.invites.length < before;
  },

  async listAudit(filter) {
    const s = state();
    const label = (id: string | null) => {
      const u = id ? s.users.find((x) => x.id === id) : undefined;
      return u ? u.display_name ?? u.email : null;
    };
    const rows = [...s.audit]
      .filter((a) => !filter.action || a.action === filter.action)
      .filter((a) => !filter.actor_id || a.actor_id === filter.actor_id)
      .filter((a) => !filter.from || a.at >= filter.from)
      .filter((a) => !filter.to || a.at < `${filter.to}T23:59:59.999Z`)
      .sort((a, b) => b.at.localeCompare(a.at) || b.id - a.id)
      .map<AuditRow>((a) => ({
        id: a.id,
        workspace_id: a.workspace_id,
        actor_id: a.actor_id,
        actor_type: a.actor_type ?? "user",
        actor_label: label(a.actor_id),
        action: a.action,
        entity: a.entity,
        entity_id: a.entity_id,
        payload: a.payload ?? null,
        at: a.at,
      }));
    return { rows: rows.slice(filter.offset, filter.offset + filter.limit), total: rows.length };
  },

  async listAuditActions() {
    return [...new Set(state().audit.map((a) => a.action))].sort();
  },

  async listAuditActors() {
    const s = state();
    const ids = [...new Set(s.audit.map((a) => a.actor_id))];
    return ids.map((id) => {
      const u = s.users.find((x) => x.id === id);
      return { id, label: u ? u.display_name ?? u.email : id };
    });
  },

  async getSubscription() {
    return { ...state().subscription };
  },

  async getPlan(code) {
    return DEMO_PLANS.find((p) => p.code === code) ?? null;
  },

  async getCurrentUsage() {
    return { ...state().usage };
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: Gast-Freigabe (vollständig simuliert)
   * ---------------------------------------------------------------------------------------- */

  async createGuestApproval(clipId, input) {
    const s = state();
    const clip = s.clips.find((c) => c.id === clipId);
    if (!clip) throw new Error("Clip nicht gefunden");
    const { userId } = await currentSession();
    const approval: GuestApproval = {
      id: uuid(),
      clip_id: clipId,
      guest_name: input.guest_name,
      guest_email: input.guest_email,
      token: input.token,
      message: input.message,
      requested_by: userId,
      expires_at: input.expires_at,
      decision: null,
      comment: null,
      decided_at: null,
      viewed_at: null,
      created_at: nowIso(),
    };
    s.guestApprovals.push(approval);
    clip.guest_approval_required = true;
    clip.updated_at = nowIso();
    return { ...approval };
  },

  async listGuestApprovals(sourceId) {
    const s = state();
    const clipIds = new Set(s.clips.filter((c) => c.source_id === sourceId).map((c) => c.id));
    return s.guestApprovals
      .filter((g) => clipIds.has(g.clip_id))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map((g) => ({ ...g }));
  },

  async getGuestApprovalByToken(token) {
    const s = state();
    const approval = s.guestApprovals.find((g) => g.token === token);
    if (!approval) return null;
    const clip = s.clips.find((c) => c.id === approval.clip_id);
    if (!clip) return null;
    const source = s.sources.find((x) => x.id === clip.source_id);
    const hook = currentHookOf(clip.id);
    const view: GuestApprovalView = {
      approval: { ...approval },
      workspace_id: s.workspace.id,
      workspace_name: s.workspace.name,
      source_title: source?.title ?? "",
      clip: {
        id: clip.id,
        platform: clip.platform,
        aspect: clip.aspect,
        title_card: clip.title_card,
        duration_s: clip.duration_s,
        file_key: clip.file_key,
        poster_key: clip.poster_key,
        status: clip.status,
      },
      onscreen_hook: hook?.onscreen_hook ?? null,
      spoken_hook: hook?.spoken_hook ?? null,
      post_caption: hook?.post_captions[clip.platform] ?? Object.values(hook?.post_captions ?? {})[0] ?? null,
    };
    return view;
  },

  async markGuestApprovalViewed(token) {
    const g = state().guestApprovals.find((x) => x.token === token);
    if (g && !g.viewed_at) g.viewed_at = nowIso();
  },

  async decideGuestApproval(token, decision, comment, ip) {
    const s = state();
    const g = s.guestApprovals.find((x) => x.token === token);
    if (!g || g.decision || (g.expires_at && Date.parse(g.expires_at) <= Date.now())) return null;
    g.decision = decision;
    g.comment = comment;
    g.decided_at = nowIso();
    g.viewed_at ??= g.decided_at;
    s.audit.push({
      id: s.nextAuditId++,
      at: nowIso(),
      workspace_id: s.workspace.id,
      actor_id: "",
      actor_type: "guest",
      action: "guest_approval.decided",
      entity: "guest_approvals",
      entity_id: g.id,
      payload: { clip_id: g.clip_id, decision, comment, guest_name: g.guest_name, ip },
    });
    return { ...g };
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: Abrechnung (manual, im Speicher)
   * ---------------------------------------------------------------------------------------- */

  async listPlans() {
    return DEMO_PLANS.map((p) => ({ ...p }));
  },

  async updateSubscription(patch) {
    const s = state();
    Object.assign(s.subscription, patch, { updated_at: nowIso() });
    if (patch.plan_code) {
      s.workspace.plan = patch.plan_code;
      const plan = DEMO_PLANS.find((p) => p.code === patch.plan_code);
      if (plan) s.usage.included_minutes = plan.included_hours * 60;
    }
    return { ...s.subscription };
  },

  async listUsageHistory() {
    return state().usageHistory.map((u) => ({ ...u }));
  },

  async recordBillingEvent(input) {
    const s = state();
    if (input.provider_event_id) {
      if (s.billingEventIds.has(input.provider_event_id)) return false;
      s.billingEventIds.add(input.provider_event_id);
    }
    return true;
  },

  async findWorkspaceIdByProvider(ref) {
    const sub = state().subscription;
    if (ref.subscription_id && sub.provider_subscription_id === ref.subscription_id) return sub.workspace_id;
    if (ref.customer_id && sub.provider_customer_id === ref.customer_id) return sub.workspace_id;
    return null;
  },

  async updateSubscriptionForWorkspace(workspaceId, patch) {
    const s = state();
    if (workspaceId !== s.workspace.id) return null;
    Object.assign(s.subscription, patch, { updated_at: nowIso() });
    if (patch.plan_code) s.workspace.plan = patch.plan_code;
    return { ...s.subscription };
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: AVV
   * ---------------------------------------------------------------------------------------- */

  async acceptDpa(input) {
    const s = state();
    const { userId, displayName } = await currentSession();
    const row: DpaAcceptance = {
      id: uuid(),
      workspace_id: s.workspace.id,
      dpa_version: input.version,
      accepted_by: userId,
      accepted_by_label: displayName,
      accepted_at: nowIso(),
      ip: input.ip,
      company: input.company,
      representative: input.representative,
    };
    s.dpaAcceptances.push(row);
    s.workspace.dpa_signed_at = row.accepted_at;
    return { ...row };
  },

  async getDpaAcceptance() {
    const list = state().dpaAcceptances;
    return list.length ? { ...list[list.length - 1] } : null;
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: Löschung (Simulation: nach 5 Sekunden „done“ mit Nachweis) und Export
   * ---------------------------------------------------------------------------------------- */

  async requestSourceDeletion(sourceId) {
    const s = state();
    const src = s.sources.find((x) => x.id === sourceId && x.status !== "deleted");
    if (!src) return null;
    const { userId, displayName } = await currentSession();
    src.status = "deleted";
    src.updated_at = nowIso();
    s.simulations.delete(sourceId);
    const clipKeys = s.clips.filter((c) => c.source_id === sourceId).flatMap((c) => [c.file_key, c.srt_key, c.vtt_key, c.poster_key]).filter((k): k is string => Boolean(k));
    const job = newDeletionJob(s, "source", sourceId, src.title, userId, displayName, [src.storage_key, ...clipKeys], {
      transcript_versions: s.transcripts.filter((t) => t.source_id === sourceId).length,
      candidates: s.candidates.filter((c) => c.source_id === sourceId).length,
      clips: s.clips.filter((c) => c.source_id === sourceId).length,
      hook_versions: s.hooks.filter((h) => s.clips.some((c) => c.id === h.clip_id && c.source_id === sourceId)).length,
      caption_versions: s.captions.filter((h) => s.clips.some((c) => c.id === h.clip_id && c.source_id === sourceId)).length,
      pipeline_events: s.events.filter((e) => e.source_id === sourceId).length,
      guest_approvals: s.guestApprovals.filter((g) => s.clips.some((c) => c.id === g.clip_id && c.source_id === sourceId)).length,
    });
    return { ...job };
  },

  async requestClipDeletion(clipId) {
    const s = state();
    const clip = s.clips.find((c) => c.id === clipId && c.status !== "deleted");
    if (!clip) return null;
    const { userId, displayName } = await currentSession();
    clip.status = "deleted";
    clip.deleted_at = nowIso();
    clip.updated_at = clip.deleted_at;
    s.renders.delete(clipId);
    const keys = [clip.file_key, clip.srt_key, clip.vtt_key, clip.poster_key].filter((k): k is string => Boolean(k));
    const job = newDeletionJob(s, "clip", clipId, PLATFORM_LABELS[clip.platform], userId, displayName, keys, {
      clips: 1,
      hook_versions: s.hooks.filter((h) => h.clip_id === clipId).length,
      caption_versions: s.captions.filter((c) => c.clip_id === clipId).length,
      guest_approvals: s.guestApprovals.filter((g) => g.clip_id === clipId).length,
    });
    return { ...job };
  },

  async listDeletionJobs() {
    advanceDeletionJobs();
    return [...state().deletionJobs].sort((a, b) => b.requested_at.localeCompare(a.requested_at)).map((j) => ({ ...j }));
  },

  async requestWorkspaceDeletion(scheduledFor) {
    const s = state();
    s.workspace.deletion_requested_at = nowIso();
    s.workspace.deletion_scheduled_for = scheduledFor;
    return { ...s.workspace };
  },

  async cancelWorkspaceDeletion() {
    const s = state();
    s.workspace.deletion_requested_at = null;
    s.workspace.deletion_scheduled_for = null;
    return { ...s.workspace };
  },

  async exportWorkspace() {
    const s = state();
    advanceDeletionJobs();
    const audit = await this.listAudit({ limit: 10_000, offset: 0 });
    const mediaKeys: { bucket: "sources" | "derived"; key: string; entity: string; entity_id: string }[] = [];
    for (const src of s.sources) {
      mediaKeys.push({ bucket: "sources", key: src.storage_key, entity: "sources", entity_id: src.id });
      if (src.proxy_key) mediaKeys.push({ bucket: "derived", key: src.proxy_key, entity: "sources", entity_id: src.id });
    }
    for (const clip of s.clips) {
      for (const k of [clip.file_key, clip.srt_key, clip.vtt_key, clip.poster_key]) {
        if (k) mediaKeys.push({ bucket: "derived", key: k, entity: "clips", entity_id: clip.id });
      }
    }
    for (const a of s.brandAssets) mediaKeys.push({ bucket: "derived", key: a.storage_key, entity: "brand_assets", entity_id: a.id });
    const subscription = { ...s.subscription, provider_customer_id: undefined, provider_subscription_id: undefined };
    return {
      workspace: { ...s.workspace },
      brand_profiles: s.brandProfiles.map((b) => ({ ...b })),
      brand_assets: s.brandAssets.map((a) => ({ ...a })),
      brand_profile_versions: s.brandVersions.map((v) => ({ ...v })),
      sources: s.sources.map((x) => ({ ...x })),
      transcript_versions: s.transcripts.map((t) => ({ ...t })),
      candidates: s.candidates.map((c) => ({ ...c })),
      clips: s.clips.map((c) => ({ ...c })),
      hook_versions: s.hooks.map((h) => ({ ...h })),
      caption_versions: s.captions.map((c) => ({ ...c })),
      guest_approvals: s.guestApprovals.map((g) => ({ ...g })),
      audit_log: audit.rows,
      job_costs: [],
      usage_periods: [...s.usageHistory, s.usage].map((u) => ({ ...u })),
      subscription,
      dpa_acceptances: s.dpaAcceptances.map((d) => ({ ...d })),
      deletion_jobs: s.deletionJobs.map((j) => ({ ...j })),
      media_keys: mediaKeys,
    };
  },

  /* ------------------------------------------------------------------------------------------
   * Block B: CI-Assets und Historie
   * ---------------------------------------------------------------------------------------- */

  async listBrandAssets(profileId) {
    return state()
      .brandAssets.filter((a) => a.brand_profile_id === profileId)
      .map((a) => ({ ...a }));
  },

  async getBrandAsset(id) {
    const a = state().brandAssets.find((x) => x.id === id);
    return a ? { ...a } : null;
  },

  async createBrandAsset(input) {
    const s = state();
    const { userId } = await currentSession();
    const asset: BrandAsset = { ...input, id: uuid(), workspace_id: s.workspace.id, uploaded_by: userId, created_at: nowIso() };
    s.brandAssets.push(asset);
    return { ...asset };
  },

  async deleteBrandAsset(id) {
    const s = state();
    const a = s.brandAssets.find((x) => x.id === id);
    if (!a) return null;
    s.brandAssets = s.brandAssets.filter((x) => x.id !== id);
    return { ...a };
  },

  async listBrandProfileVersions(profileId) {
    return state()
      .brandVersions.filter((v) => v.brand_profile_id === profileId)
      .sort((a, b) => b.version - a.version)
      .map((v) => ({ ...v, snapshot: { ...v.snapshot } }));
  },

  async restoreBrandProfileVersion(profileId, version) {
    const s = state();
    const profile = s.brandProfiles.find((b) => b.id === profileId);
    const snap = s.brandVersions.find((v) => v.brand_profile_id === profileId && v.version === version);
    if (!profile || !snap) return null;
    await snapshotBrand(profile);
    const fields = structuredClone(snap.snapshot) as Partial<BrandProfile>;
    delete fields.id;
    delete fields.workspace_id;
    delete fields.version;
    delete fields.created_at;
    delete fields.updated_at;
    Object.assign(profile, fields, { version: profile.version + 1, updated_at: nowIso() });
    return { ...profile };
  },
};

/* Snapshot vor jeder Änderung am Markenprofil (version = max + 1) */
async function snapshotBrand(profile: BrandProfile): Promise<void> {
  const s = state();
  const { userId, displayName } = await currentSession();
  const max = s.brandVersions.filter((v) => v.brand_profile_id === profile.id).reduce((m, v) => Math.max(m, v.version), 0);
  s.brandVersions.push({
    id: uuid(),
    brand_profile_id: profile.id,
    version: max + 1,
    snapshot: structuredClone(profile),
    changed_by: userId,
    changed_by_label: displayName,
    changed_at: nowIso(),
  });
}

function newDeletionJob(
  s: DemoState,
  entity: DeletionJob["entity"],
  entityId: string,
  label: string,
  userId: string,
  userLabel: string,
  keys: string[],
  rows: Record<string, number>,
): DeletionJob {
  const job: DeletionJob & { _keys?: string[]; _rows?: Record<string, number> } = {
    id: uuid(),
    workspace_id: s.workspace.id,
    entity,
    entity_id: entityId,
    entity_label: label,
    reason: "user_request",
    requested_by: userId,
    requested_by_label: userLabel,
    status: "queued",
    keys_deleted: [],
    rows_deleted: {},
    error: null,
    requested_at: nowIso(),
    finished_at: null,
  };
  job._keys = keys;
  job._rows = rows;
  s.deletionJobs.push(job);
  return job;
}

/* Simulation: queued → running nach 1,5 s → done nach 5 s mit Nachweis (Keys mit Zeitstempel, Zeilenzähler) */
function advanceDeletionJobs() {
  const s = state();
  for (const job of s.deletionJobs as (DeletionJob & { _keys?: string[]; _rows?: Record<string, number> })[]) {
    if (job.status === "done" || job.status === "failed") continue;
    const elapsed = Date.now() - Date.parse(job.requested_at);
    if (elapsed >= 5000) {
      job.status = "done";
      job.finished_at = nowIso();
      job.keys_deleted = (job._keys ?? []).map((key, i) => ({ bucket: i === 0 && job.entity === "source" ? "sources" : "derived", key, deleted_at: job.finished_at ?? nowIso(), existed: true }));
      job.rows_deleted = { ...(job._rows ?? {}) };
      s.audit.push({
        id: s.nextAuditId++,
        at: job.finished_at,
        workspace_id: s.workspace.id,
        actor_id: "",
        actor_type: "system",
        action: `${job.entity}.deleted`,
        entity: job.entity,
        entity_id: job.entity_id,
        payload: { job_id: job.id, keys: job.keys_deleted.length, rows: job.rows_deleted },
      });
      if (job.entity === "source") {
        const src = s.sources.find((x) => x.id === job.entity_id);
        if (src) Object.assign(src, { title: "gelöscht", storage_key: "", proxy_key: null, sha256: null });
      }
    } else if (elapsed >= 1500) {
      job.status = "running";
    }
  }
}
