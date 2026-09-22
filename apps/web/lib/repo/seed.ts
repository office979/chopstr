import type {
  BrandProfile,
  Candidate,
  CandidateGates,
  CandidateRubric,
  PipelineEvent,
  RubricKey,
  Source,
  TranscriptVersion,
  TranscriptWord,
  Workspace,
} from "@/lib/repo/types";
import { classifyFiller, isNegation } from "@/lib/transcript/fillers";
import { clipText, sentenceRange, sentencesFromWords } from "@/lib/transcript/sentences";
import { allGatesPassed } from "@/lib/candidates/gates";
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
  candidates: [
    "66666666-6666-4666-8666-666666666601",
    "66666666-6666-4666-8666-666666666602",
    "66666666-6666-4666-8666-666666666603",
    "66666666-6666-4666-8666-666666666604",
    "66666666-6666-4666-8666-666666666605",
    "66666666-6666-4666-8666-666666666606",
  ],
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
  ci: {
    colors: { primary: "#020cf5", secondary: "#0a0a13", accent: "#f4f5fe" },
    fonts: { primary_key: null, secondary_key: null },
    logo_key: null,
    lower_third: { enabled: true, name: "Ferdinand Platz", role: "Geschäftsführer PLACEMedia" },
  },
  caption_style: {
    highlight_color: "#ffd700",
    hook_overlay: { tiktok: true, reels: true, shorts: true, linkedin: false },
  },
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
  { source_id: DEMO_IDS.podcast, step: "detect_candidates", status: "started", progress: 0, message: "Story-Engine über Bedrock EU", payload: null, at: iso(-days(2) + minutes(52)) },
  {
    source_id: DEMO_IDS.podcast,
    step: "detect_candidates",
    status: "finished",
    progress: 1,
    message: "6 Kandidaten, 3 erfüllen alle Pflichtkriterien",
    payload: {
      candidates: 6,
      gate_passed: 3,
      chapters: 15,
      provider: "bedrock-eu",
      model_id: "claude über Bedrock EU (Demo)",
      prompt_versions: ["propose_moments_v1", "score_clip_v1", "story_graph_confirm_v1"],
    },
    at: iso(-days(2) + minutes(58)),
  },
];

/* Ereignisse für die laufende Keynote (Startzustand; die Simulation ergänzt weitere) */
export const seedKeynoteEvents: Omit<PipelineEvent, "id">[] = [
  { source_id: DEMO_IDS.keynote, step: "probe_and_extract", status: "started", progress: 0, message: "Datei wird geprüft", payload: null, at: iso(-minutes(11)) },
  { source_id: DEMO_IDS.keynote, step: "probe_and_extract", status: "finished", progress: 1, message: "3840×2160, 50 fps, 41:00", payload: null, at: iso(-minutes(8)) },
  { source_id: DEMO_IDS.keynote, step: "transcribe_de", status: "started", progress: 0, message: "whisper-large-v3-turbo-german", payload: null, at: iso(-minutes(8)) },
  { source_id: DEMO_IDS.keynote, step: "transcribe_de", status: "progress", progress: 0.35, message: "Minute 14 von 41", payload: null, at: iso(-minutes(1)) },
];

/* Transkript: B2B-Gespräch über Vakanzkosten, ca. 46 Sätze, zwei Sprecher.
 * Enthält Zahlen, eine Gegenposition (Satz 14), einen Witz (Satz 32) und eine spätere
 * Relativierung „Das heißt aber nicht …“ (Satz 41). Satz 10 endet als ASR-Fragment auf „deshalb“. */
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
    text: "Ja, ähm, das ist halt der Denkfehler. Recruiting ist keine Kostenstelle, sondern eine Investition mit messbarem Rückfluss. Wir sagen unseren Kunden wie Kleinecke oder Rimowa immer: Rechnet die Vakanzkosten gegen das Budget, dann ist die Entscheidung eigentlich klar, und deshalb.",
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
  {
    speaker: "SPEAKER_00",
    text: "Ich halte trotzdem mal dagegen. Ein Handwerksbetrieb mit zwölf Leuten hat keine Finanzabteilung, die so eine Rechnung aufmacht. Der Chef steht selbst auf der Baustelle und sieht nur, dass die Anzeige dreitausend Euro kostet.",
    low: { 5: 0.87 },
  },
  {
    speaker: "SPEAKER_01",
    text: "Stimmt, und genau da setzen wir an. Wir rechnen es für ihn in Tagen, nicht in Tabellen. Eine Stelle im Handwerk bleibt in Österreich im Schnitt zweiundvierzig Tage offen. Wenn ein Monteur am Tag achthundert Euro Umsatz bringt, dann sind das über dreißigtausend Euro, die einfach fehlen. Das versteht jeder, der schon einmal eine Rechnung geschrieben hat.",
    low: { 21: 0.83, 34: 0.78 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Zweiundvierzig Tage, okay. Und in der Zeit macht das restliche Team die Arbeit mit.",
  },
  {
    speaker: "SPEAKER_01",
    text: "Und das ist der Teil, über den niemand gern spricht. Wir haben bei einem Kunden im Elektrohandwerk gesehen, dass die Krankenstände im Team um dreißig Prozent gestiegen sind, während zwei Stellen offen waren. Die Leute haben Überstunden geschoben, bis der Erste ausgefallen ist. Das ist nicht mehr nur eine Vakanz, das ist eine Kettenreaktion.",
    low: { 17: 0.74, 41: 0.85 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Das ist hart. Also die offene Stelle kostet nicht nur Umsatz, sondern auch Gesundheit.",
  },
  {
    speaker: "SPEAKER_01",
    text: "So ist es. Und deshalb ist meine Antwort auf die Budgetfrage immer dieselbe: Die einzige Stelle, die sich von selbst besetzt, ist der Parkplatz vom Chef. Alles andere kostet Geld, ob ihr es ausgebt oder nicht.",
    low: { 22: 0.82 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Sehr gut. Aber jetzt mal konkret: Wie viel Budget ist denn vernünftig?",
  },
  {
    speaker: "SPEAKER_01",
    text: "Unsere Faustregel ist ein Monat Vakanzkosten. Wenn die offene Stelle vierzehntausend Euro im Monat kostet, dann sind vierzehntausend Euro für die Besetzung gut angelegt. Die meisten geben deutlich weniger aus und wundern sich, dass nichts passiert.",
    low: { 3: 0.88 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Das ist mehr, als die meisten im Kopf haben. Ich kenne Betriebe, die geben zweitausend Euro für eine Anzeige aus und warten dann ein halbes Jahr. Das gilt jetzt aber für den Vertrieb, oder?",
    low: { 12: 0.86 },
  },
  {
    speaker: "SPEAKER_01",
    text: "Das heißt aber nicht, dass das für jede Branche gilt. In der Pflege oder in der Gastronomie rechnet sich das anders, weil dort die Margen pro Kopf viel niedriger sind. Da reden wir eher über ein Drittel davon.",
    low: { 15: 0.8 },
  },
  {
    speaker: "SPEAKER_00",
    text: "Gut, dann halten wir fest: erst rechnen, dann entscheiden. Und die Rechnung dauert keine zehn Minuten.",
  },
  {
    speaker: "SPEAKER_01",
    text: "Genau. Und wer sie nicht macht, hat sie trotzdem bezahlt.",
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
      const dur = filler === "hard" ? 0.42 : Math.min(1.1, 0.22 + bare.length * 0.055);
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
      t = end + (/[.?!:]$/.test(token) ? 0.55 : 0.09);
      if (/[.?!]$/.test(token)) sentence += 1;
      globalIndex += 1;
    });
    t += 1.1;
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

/* Kandidaten (Phase 2) für das fertige Projekt, passend zum Seed-Transkript. Grenzen, Text und Dauer
 * werden aus den Sätzen abgeleitet, damit sie mit dem Transkript übereinstimmen. */
const MODEL_CLAUDE = "claude über Bedrock EU (Demo)";
const WEIGHTS: Record<RubricKey, number> = { hook: 0.3, payoff: 0.25, specificity: 0.2, tension: 0.15, audience_fit: 0.1 };

type ScoreInput = Record<RubricKey, [number, string]>;

function scores(input: ScoreInput): CandidateRubric["scores"] {
  const out = {} as CandidateRubric["scores"];
  for (const key of Object.keys(WEIGHTS) as RubricKey[]) {
    out[key] = { value: input[key][0], weight: WEIGHTS[key], evidence: input[key][1] };
  }
  return out;
}

function weightedTotal(sc: CandidateRubric["scores"]): number {
  const sum = (Object.keys(WEIGHTS) as RubricKey[]).reduce((acc, k) => acc + sc[k].value * sc[k].weight, 0);
  return Number(sum.toFixed(1));
}

const PASS_GATES: CandidateGates = {
  standalone: { passed: true, detail: "keine offenen Verweise" },
  fidelity: { passed: true, detail: "keine entfernte Verneinung oder Einschränkung" },
  sentence_boundaries: { passed: true, detail: "Start und Ende an Satzgrenzen" },
  verb_bracket: { passed: true, detail: "kein Schnitt in einer Verbklammer", available: true },
  no_open_loop: { passed: true, detail: "endet mit abgeschlossenem Satz" },
};

interface SeedCandidateSpec {
  id: string;
  first: number;
  last: number;
  structure: Candidate["structure"];
  scores: ScoreInput;
  gates?: Partial<CandidateGates>;
  rubric?: Partial<CandidateRubric>;
  risk_flags?: Candidate["risk_flags"];
  flags?: { sentence_idx: number; marker: string; overlap: number; confirmed: boolean | null; reason: string; repair: "extend" | "overlay"; suggestion: string }[];
  why: string;
  model_id: string;
  prompt_version: string | null;
  minutesAgo: number;
}

const SEED_CANDIDATES: SeedCandidateSpec[] = [
  {
    id: DEMO_IDS.candidates[0],
    first: 3,
    last: 7,
    structure: "payoff_first",
    scores: {
      hook: [8, "Eine unbesetzte Stelle im Vertrieb kostet ein mittelständisches Unternehmen im Schnitt vierzehntausend Euro pro Monat."],
      payoff: [8, "Nicht die Anzeige, nicht der Recruiter, sondern der Umsatz, der einfach nicht entsteht."],
      specificity: [9, "vierzehntausend Euro pro Monat"],
      tension: [7, "Und trotzdem sparen viele beim Recruiting-Budget, weil sie es als Kostenstelle sehen."],
      audience_fit: [9, "Die meisten Geschäftsführer haben das halt nie ausgerechnet."],
    },
    rubric: { proposal_why: "Die Zahl steht am Anfang, der zweite Sprecher greift sie auf und benennt den Widerspruch zum Budget." },
    why: "Kernaussage mit konkreter Zahl in 39 Sekunden vollständig, Einstieg direkt mit der Rechnung, keine spätere Relativierung gefunden, passt für LinkedIn.",
    model_id: MODEL_CLAUDE,
    prompt_version: "score_clip_v1",
    minutesAgo: 6,
  },
  {
    id: DEMO_IDS.candidates[1],
    first: 14,
    last: 21,
    structure: "tension_first",
    scores: {
      hook: [9, "Ich halte trotzdem mal dagegen."],
      payoff: [9, "Wenn ein Monteur am Tag achthundert Euro Umsatz bringt, dann sind das über dreißigtausend Euro, die einfach fehlen."],
      specificity: [9, "zweiundvierzig Tage offen"],
      tension: [9, "Der Chef steht selbst auf der Baustelle und sieht nur, dass die Anzeige dreitausend Euro kostet."],
      audience_fit: [8, "Das versteht jeder, der schon einmal eine Rechnung geschrieben hat."],
    },
    rubric: { proposal_why: "Gegenposition des Hosts, dann Auflösung in Tagen und Euro. Der Konflikt wird im Clip aufgelöst." },
    why: "Beginnt mit einer Gegenposition und löst sie mit zwei Zahlen auf, beide Sprecher kommen vor, Ende an einem abgeschlossenen Gedanken.",
    model_id: MODEL_CLAUDE,
    prompt_version: "score_clip_v1",
    minutesAgo: 6,
  },
  {
    id: DEMO_IDS.candidates[2],
    first: 35,
    last: 37,
    structure: "decision_story",
    scores: {
      hook: [7, "Unsere Faustregel ist ein Monat Vakanzkosten."],
      payoff: [8, "dann sind vierzehntausend Euro für die Besetzung gut angelegt."],
      specificity: [8, "vierzehntausend Euro im Monat"],
      tension: [6, "Die meisten geben deutlich weniger aus und wundern sich, dass nichts passiert."],
      audience_fit: [8, "Unsere Faustregel ist ein Monat Vakanzkosten."],
    },
    rubric: { proposal_why: "Klare Regel mit Zahl und Konsequenz, als Entscheidungshilfe formuliert." },
    flags: [
      {
        sentence_idx: 41,
        marker: "das heißt aber nicht",
        overlap: 0.34,
        confirmed: true,
        reason: "Der spätere Satz beschränkt die Faustregel auf den Vertrieb; für Pflege und Gastronomie gilt ein Drittel.",
        repair: "extend",
        suggestion: "Clip bis Satz 41 verlängern oder Einschränkung als Text einblenden",
      },
    ],
    why: "Faustregel mit Zahl in 23 Sekunden, aber 23 Sekunden später schränkt der Sprecher sie auf eine Branche ein. Ohne die Einschränkung wäre der Clip nicht sinntreu.",
    model_id: MODEL_CLAUDE,
    prompt_version: "score_clip_v1",
    minutesAgo: 6,
  },
  {
    id: DEMO_IDS.candidates[3],
    first: 8,
    last: 10,
    structure: "hook_build_payoff",
    scores: {
      hook: [7, "das ist halt der Denkfehler."],
      payoff: [7, "Recruiting ist keine Kostenstelle, sondern eine Investition mit messbarem Rückfluss."],
      specificity: [6, "Rechnet die Vakanzkosten gegen das Budget"],
      tension: [7, "Rechnet die Vakanzkosten gegen das Budget, dann ist die Entscheidung eigentlich klar"],
      audience_fit: [8, "Wir sagen unseren Kunden wie Kleinecke oder Rimowa immer"],
    },
    gates: { no_open_loop: { passed: false, detail: "endet auf „deshalb“" } },
    rubric: {
      suggested_title_card: "Recruiting ist keine Kostenstelle",
      repair: { rounds: 2, expanded_front: 0, expanded_back: 0, failed: true },
      proposal_why: "These mit Kundennamen und klarer Handlungsanweisung, aber der letzte Satz bricht ab.",
    },
    why: "Klare These mit Handlungsanweisung, aber der Ausschnitt endet auf „und deshalb“. Verlängern um einen Satz oder Titelkarte setzen.",
    model_id: MODEL_CLAUDE,
    prompt_version: "score_clip_v1",
    minutesAgo: 6,
  },
  {
    id: DEMO_IDS.candidates[4],
    first: 24,
    last: 32,
    structure: "hook_build_payoff",
    scores: {
      hook: [8, "Und das ist der Teil, über den niemand gern spricht."],
      payoff: [8, "Die einzige Stelle, die sich von selbst besetzt, ist der Parkplatz vom Chef."],
      specificity: [7, "die Krankenstände im Team um dreißig Prozent gestiegen sind"],
      tension: [8, "Die Leute haben Überstunden geschoben, bis der Erste ausgefallen ist."],
      audience_fit: [6, "Alles andere kostet Geld, ob ihr es ausgebt oder nicht."],
    },
    gates: { standalone: { passed: false, detail: "Einstieg „Und das ist der Teil“ verweist auf Vorheriges" } },
    rubric: {
      unresolved_references: ["das ist der Teil"],
      needs_earlier_context: true,
      is_humor: true,
      sensitive_topic: true,
      repair: { rounds: 2, expanded_front: 1, expanded_back: 0, failed: true },
      proposal_why: "Krankenstände als Folge offener Stellen, dann ein Witz als Pointe. Humor und Gesundheitsthema trifft nicht jede Marke.",
    },
    risk_flags: ["humor", "sensitive_topic"],
    why: "Starke Pointe und ein konkreter Fall, aber der Clip verbindet Krankenstände mit einem Witz. Ob der Ton zur Marke passt, entscheidet ein Mensch.",
    model_id: MODEL_CLAUDE,
    prompt_version: "score_clip_v1",
    minutesAgo: 6,
  },
  {
    id: DEMO_IDS.candidates[5],
    first: 44,
    last: 47,
    structure: "how_to_list",
    scores: {
      hook: [6, "erst rechnen, dann entscheiden."],
      payoff: [6, "Und wer sie nicht macht, hat sie trotzdem bezahlt."],
      specificity: [6, "keine zehn Minuten"],
      tension: [6, "Und wer sie nicht macht, hat sie trotzdem bezahlt."],
      audience_fit: [7, "Gut, dann halten wir fest: erst rechnen, dann entscheiden."],
    },
    gates: {
      standalone: { passed: false, detail: "Verweiswort „dann“ am Anfang, Bezug unklar" },
      verb_bracket: { passed: true, detail: "spaCy nicht geladen, Verbklammer nicht geprüft", available: false },
    },
    rubric: {
      unresolved_references: ["dann halten wir fest"],
      needs_earlier_context: true,
      repair: { rounds: 0, expanded_front: 0, expanded_back: 0, failed: false },
      proposal_why: "Heuristik: Schrittfolge („erst, dann“), Zahl und Verneinung im Zielbereich.",
    },
    risk_flags: ["heuristic_only"],
    why: "Heuristik ohne Sprachmodell: Schrittfolge mit Zahl und Verneinung erkannt, Sinntreue und Eigenständigkeit nicht geprüft.",
    model_id: "heuristic-v1",
    prompt_version: null,
    minutesAgo: 6,
  },
];

export function buildSeedCandidates(words: TranscriptWord[] = buildSeedWords()): Candidate[] {
  const sentences = sentencesFromWords(words);
  return SEED_CANDIDATES.map((spec) => {
    const range = sentenceRange(sentences, spec.first, spec.last);
    const start = range[0].start;
    const end = range[range.length - 1].end;
    const sc = scores(spec.scores);
    const gates: CandidateGates = { ...PASS_GATES, ...(spec.gates ?? {}) };
    const rubric: CandidateRubric = {
      contract: "candidates_v1",
      text: clipText(range),
      speakers: [...new Set(range.map((r) => r.speaker))],
      duration_s: Number((end - start).toFixed(1)),
      scores: sc,
      unresolved_references: [],
      needs_earlier_context: false,
      ends_before_answer: false,
      is_humor: false,
      sensitive_topic: false,
      suggested_title_card: "",
      repair: { rounds: 1, expanded_front: 0, expanded_back: 0, failed: false },
      proposal_why: "",
      parent_id: null,
      ...(spec.rubric ?? {}),
    };
    return {
      id: spec.id,
      source_id: DEMO_IDS.podcast,
      version: 1,
      segments: [{ start, end, role: "body" }],
      start_s: start,
      end_s: end,
      first_sent: spec.first,
      last_sent: spec.last,
      structure: spec.structure,
      rubric,
      gates,
      story_graph_flags: (spec.flags ?? []).map((f) => {
        const sent = sentences.find((x) => x.idx === f.sentence_idx);
        return {
          ...f,
          seconds_after: sent ? Number((sent.start - end).toFixed(1)) : 0,
          text: sent?.text ?? "",
        };
      }),
      risk_flags: spec.risk_flags ?? [],
      total: weightedTotal(sc),
      gate_passed: allGatesPassed(gates),
      why: spec.why,
      model_id: spec.model_id,
      prompt_version: spec.prompt_version,
      human_verdict: null,
      verdict_reason: null,
      verdict_by: null,
      verdict_at: null,
      created_at: iso(-days(2) + minutes(58) - minutes(spec.minutesAgo)),
    };
  });
}
