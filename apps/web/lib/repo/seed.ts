import type {
  BrandProfile,
  PipelineEvent,
  Source,
  TranscriptVersion,
  TranscriptWord,
  Workspace,
} from "@/lib/repo/types";
import { classifyFiller, isNegation } from "@/lib/transcript/fillers";
import { DEV_ACTOR_ID, DEV_WORKSPACE_ID } from "@/lib/session";

/* Realistische Seed-Daten für den Demo-Modus (ohne Datenbank) */

export const DEMO_IDS = {
  workspace: DEV_WORKSPACE_ID,
  actor: DEV_ACTOR_ID,
  brand: "33333333-3333-4333-8333-333333333333",
  podcast: "44444444-4444-4444-8444-444444444401",
  keynote: "44444444-4444-4444-8444-444444444402",
  interview: "44444444-4444-4444-8444-444444444403",
  transcript: "55555555-5555-4555-8555-555555555501",
} as const;

const NOW = Date.now();
const iso = (offsetMs: number) => new Date(NOW + offsetMs).toISOString();
const days = (n: number) => n * 24 * 60 * 60 * 1000;
const hours = (n: number) => n * 60 * 60 * 1000;
const minutes = (n: number) => n * 60 * 1000;

export const seedWorkspace: Workspace = {
  id: DEMO_IDS.workspace,
  name: "PLACEMedia",
  slug: "placemedia",
  plan: "starter",
  tier: "standard",
  data_region: "eu-central-1",
  retention_days: 30,
  render_retention_days: 90,
  allow_us_subprocessors: false,
  training_opt_in: false,
  dpa_signed_at: null,
  created_at: iso(-days(40)),
};

export const seedBrandProfile: BrandProfile = {
  id: DEMO_IDS.brand,
  workspace_id: DEMO_IDS.workspace,
  name: "PLACEMedia Podcast",
  version: 1,
  address: "du",
  country: "AT",
  gender_mode: "neutral",
  asr_variant: "de",
  brand_vocab: ["PLACEMedia", "Kleinecke", "Rimowa", "Vakanzkosten"],
  protected_terms: ["Jänner", "Marille", "heuer"],
  banned_phrases: ["Game Changer", "revolutionär"],
  tone_adjectives: ["ruhig", "konkret", "belegt"],
  default_platform: "linkedin",
  caption_preset: "linkedin_static",
  created_at: iso(-days(38)),
  updated_at: iso(-days(3)),
};

const baseSource = {
  workspace_id: DEMO_IDS.workspace,
  brand_profile_id: DEMO_IDS.brand,
  rights_confirmed_by: DEMO_IDS.actor,
  source_owner: null,
  source_title: null,
  source_url: null,
  created_by: DEMO_IDS.actor,
  temporal_workflow_id: null as string | null,
  proxy_key: null as string | null,
};

export const seedSources: Source[] = [
  {
    ...baseSource,
    id: DEMO_IDS.podcast,
    title: "Podcast Folge 12: Was eine offene Stelle wirklich kostet",
    original_filename: "placemedia-podcast-012.mp4",
    mime_type: "video/mp4",
    size_bytes: 2_147_483_648,
    sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    storage_key: `sources/${DEMO_IDS.workspace}/${DEMO_IDS.podcast}/placemedia-podcast-012.mp4`,
    duration_s: 3720,
    width: 1920,
    height: 1080,
    fps: 25,
    rights_status: "own",
    rights_confirmed_at: iso(-days(2)),
    expected_speakers: 2,
    brief: {
      audience: "Geschäftsführung im Mittelstand, HR-Leitung",
      wanted: "Zahlen zu Vakanzkosten, klare Aussagen zu Recruiting-Budget",
      exclude: "Smalltalk am Anfang, Werbeblock ab Minute 40",
      platform: "linkedin",
    },
    status: "ready",
    status_message: null,
    temporal_workflow_id: `project-${DEMO_IDS.podcast}`,
    delete_after: iso(days(28)),
    created_at: iso(-days(2)),
    updated_at: iso(-days(2) + hours(1)),
  },
  {
    ...baseSource,
    id: DEMO_IDS.keynote,
    title: "Keynote Recruiting Summit Wien 2026",
    original_filename: "keynote-recruiting-summit-wien.mov",
    mime_type: "video/quicktime",
    size_bytes: 3_650_000_000,
    sha256: "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
    storage_key: `sources/${DEMO_IDS.workspace}/${DEMO_IDS.keynote}/keynote-recruiting-summit-wien.mov`,
    duration_s: 2460,
    width: 3840,
    height: 2160,
    fps: 50,
    rights_status: "licensed",
    rights_confirmed_at: iso(-minutes(12)),
    expected_speakers: 1,
    brief: {
      audience: "Recruiter, Personalberatungen",
      wanted: "Thesen zur Zukunft von Stellenanzeigen",
      exclude: "Begrüßung, Q&A",
      platform: "shorts",
    },
    status: "transcribing",
    status_message: "Transkription läuft",
    temporal_workflow_id: `project-${DEMO_IDS.keynote}`,
    delete_after: iso(days(30)),
    created_at: iso(-minutes(12)),
    updated_at: iso(-minutes(1)),
  },
  {
    ...baseSource,
    id: DEMO_IDS.interview,
    title: "Interview mit Kleinecke: Preise im Handwerk",
    original_filename: "interview-kleinecke-preise.mp4",
    mime_type: "video/mp4",
    size_bytes: 1_180_000_000,
    sha256: null,
    storage_key: `sources/${DEMO_IDS.workspace}/${DEMO_IDS.interview}/interview-kleinecke-preise.mp4`,
    duration_s: null,
    width: null,
    height: null,
    fps: null,
    rights_status: "own",
    rights_confirmed_at: iso(-minutes(2)),
    expected_speakers: 2,
    brief: { audience: "Handwerksbetriebe", wanted: "Preisargumente", exclude: "", platform: "reels" },
    status: "uploaded",
    status_message: null,
    temporal_workflow_id: null,
    delete_after: iso(days(30)),
    created_at: iso(-minutes(2)),
    updated_at: iso(-minutes(2)),
  },
];

/* Pipeline-Ereignisse für das fertige Projekt */
export const seedPodcastEvents: Omit<PipelineEvent, "id">[] = [
  { source_id: DEMO_IDS.podcast, step: "probe_and_extract", status: "started", progress: 0, message: "Datei wird geprüft", payload: null, at: iso(-days(2) + minutes(1)) },
  { source_id: DEMO_IDS.podcast, step: "probe_and_extract", status: "finished", progress: 1, message: "1920×1080, 25 fps, 62:00", payload: { sha256_verified: true }, at: iso(-days(2) + minutes(4)) },
  { source_id: DEMO_IDS.podcast, step: "transcribe_de", status: "started", progress: 0, message: "whisper-large-v3-turbo-german", payload: null, at: iso(-days(2) + minutes(4)) },
  { source_id: DEMO_IDS.podcast, step: "transcribe_de", status: "finished", progress: 1, message: "9.412 Wörter, mittlere Konfidenz 0,94", payload: null, at: iso(-days(2) + minutes(31)) },
  { source_id: DEMO_IDS.podcast, step: "diarize", status: "started", progress: 0, message: "2 Sprecher erwartet", payload: null, at: iso(-days(2) + minutes(31)) },
  { source_id: DEMO_IDS.podcast, step: "diarize", status: "finished", progress: 1, message: "2 Sprecher erkannt", payload: null, at: iso(-days(2) + minutes(44)) },
  { source_id: DEMO_IDS.podcast, step: "fuse_and_nlp", status: "started", progress: 0, message: "dach_nlp", payload: null, at: iso(-days(2) + minutes(44)) },
  { source_id: DEMO_IDS.podcast, step: "fuse_and_nlp", status: "finished", progress: 1, message: "612 Sätze, 184 Füllwörter, 96 Verneinungen", payload: null, at: iso(-days(2) + minutes(52)) },
  { source_id: DEMO_IDS.podcast, step: "detect_candidates", status: "skipped", progress: null, message: "Kommt in Phase 2", payload: null, at: iso(-days(2) + minutes(52)) },
];

/* Ereignisse für die laufende Keynote (Startzustand; die Simulation ergänzt weitere) */
export const seedKeynoteEvents: Omit<PipelineEvent, "id">[] = [
  { source_id: DEMO_IDS.keynote, step: "probe_and_extract", status: "started", progress: 0, message: "Datei wird geprüft", payload: null, at: iso(-minutes(11)) },
  { source_id: DEMO_IDS.keynote, step: "probe_and_extract", status: "finished", progress: 1, message: "3840×2160, 50 fps, 41:00", payload: null, at: iso(-minutes(8)) },
  { source_id: DEMO_IDS.keynote, step: "transcribe_de", status: "started", progress: 0, message: "whisper-large-v3-turbo-german", payload: null, at: iso(-minutes(8)) },
  { source_id: DEMO_IDS.keynote, step: "transcribe_de", status: "progress", progress: 0.35, message: "Minute 14 von 41", payload: null, at: iso(-minutes(1)) },
];

/* Transkript: B2B-Gespräch über Vakanzkosten, ca. 160 Wörter, zwei Sprecher */
interface Segment {
  speaker: string;
  text: string;
  /* Wörter mit erzwungener niedriger Konfidenz (Index innerhalb des Segments -> prob) */
  low?: Record<number, number>;
}

const SEGMENTS: Segment[] = [
  {
    speaker: "SPEAKER_00",
    text: "Also ähm, wenn wir über Preise reden, dann ist die erste Frage eigentlich immer: Was kostet euch eine offene Stelle pro Monat? Die meisten Geschäftsführer haben das halt nie ausgerechnet.",
    low: { 24: 0.86 },
  },
  {
    speaker: "SPEAKER_01",
    text: "Genau, und äh das ist der Punkt. Wir haben bei PLACEMedia mal nachgerechnet: Eine unbesetzte Stelle im Vertrieb kostet ein mittelständisches Unternehmen im Schnitt vierzehntausend Euro pro Monat. Nicht die Anzeige, nicht der Recruiter, sondern der Umsatz, der einfach nicht entsteht.",
    low: { 10: 0.62, 24: 0.81, 12: 0.88 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Vierzehntausend. Das ist eine Zahl, die man sich merken kann. Und trotzdem sparen viele beim Recruiting-Budget, weil sie es als Kostenstelle sehen.",
    low: { 0: 0.79 },
  },
  {
    speaker: "SPEAKER_01",
    text: "Ja, ähm, das ist halt der Denkfehler. Recruiting ist keine Kostenstelle, sondern eine Investition mit messbarem Rückfluss. Wir sagen unseren Kunden wie Kleinecke oder Rimowa immer: Rechnet die Vakanzkosten gegen das Budget, dann ist die Entscheidung eigentlich klar.",
    low: { 22: 0.71, 24: 0.77, 28: 0.84 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Und wie überzeugt ihr die, die sagen, wir haben äh gerade kein Geld dafür?",
  },
  {
    speaker: "SPEAKER_01",
    text: "Mit genau dieser Rechnung. Wer drei Monate wartet, hat schon mehr verloren, als die ganze Kampagne kostet.",
    low: { 6: 0.89 },
  },
];

/* Deterministische Pseudozufallszahl (kein Math.random, damit Server und Client gleich rendern) */
function seeded(n: number): number {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

export function buildSeedWords(): TranscriptWord[] {
  const words: TranscriptWord[] = [];
  let t = 0.4;
  let sentence = 0;
  let globalIndex = 0;
  for (const seg of SEGMENTS) {
    const tokens = seg.text.split(/\s+/);
    tokens.forEach((token, i) => {
      const bare = token.replace(/[.,;:!?]/g, "");
      const filler = classifyFiller(token);
      const dur = filler === "hard" ? 0.42 : Math.min(0.9, 0.16 + bare.length * 0.045);
      const start = Number(t.toFixed(2));
      const end = Number((t + dur).toFixed(2));
      const forced = seg.low?.[i];
      const prob = forced ?? Number((0.91 + seeded(globalIndex) * 0.08).toFixed(2));
      words.push({
        text: token,
        start,
        end,
        prob,
        speaker: seg.speaker,
        filler,
        negation: isNegation(token),
        sentence_idx: sentence,
      });
      t = end + (/[.?!:]$/.test(token) ? 0.32 : 0.06);
      if (/[.?!]$/.test(token)) sentence += 1;
      globalIndex += 1;
    });
    t += 0.45;
  }
  return words;
}

export function buildSeedTranscript(): TranscriptVersion {
  const words = buildSeedWords();
  const lowConf = words.filter((w) => w.prob < 0.9).length;
  const mean = words.reduce((acc, w) => acc + w.prob, 0) / words.length;
  return {
    id: DEMO_IDS.transcript,
    source_id: DEMO_IDS.podcast,
    version: 1,
    origin: "asr",
    asr_model_id: "primeline/whisper-large-v3-turbo-german",
    asr_variant: "de",
    diarizer_id: "pyannote/speaker-diarization-3.1",
    language: "de",
    words,
    stats: {
      word_count: words.length,
      speakers: 2,
      mean_prob: Number(mean.toFixed(3)),
      low_conf_ratio: Number((lowConf / words.length).toFixed(3)),
      speaker_names: {},
    },
    created_by: null,
    created_at: iso(-days(2) + minutes(52)),
  };
}
