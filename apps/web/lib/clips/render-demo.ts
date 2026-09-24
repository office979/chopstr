import type {
  BrandProfile,
  Candidate,
  CaptionVersion,
  Clip,
  HookVersion,
  RenderPlan,
  Source,
  TranscriptWord,
} from "@/lib/repo/types";
import { DEFAULT_LINT_PROFILE, type LintProfile } from "@/lib/copy/lint";
import { demoHookVariants, demoPostCaptions } from "@/lib/copy/hooks";
import { buildCaptionCards, wordsFromText, wordsOnOutputTimeline } from "@/lib/clips/captions";
import { ASPECT_SIZE, captionPresetFor, layoutFor, presetFor } from "@/lib/clips/presets";
import { AD_LABELS, PLATFORMS } from "@/lib/clips/labels";

/* Demo-Render: deterministische Ergebnisse in Vertragsform (packages/schema/CLIPS.md), ohne ffmpeg.
 * Strategie neutral, detector none, C2PA übersprungen. Nur im Demo-Modus verwendet. */

export const DEMO_MODEL_ID = "claude über Bedrock EU (Demo)";
export const HOOK_PROMPT_VERSION = "hooks_v1";

export function lintProfileFrom(brand: BrandProfile | null): LintProfile {
  if (!brand) return DEFAULT_LINT_PROFILE;
  return {
    address: brand.address,
    country: brand.country,
    gender_mode: brand.gender_mode,
    banned_phrases: brand.banned_phrases,
  };
}

export function adLabelFor(source: Source, brand: BrandProfile | null): string | null {
  if (!source.brief.is_ad) return null;
  return AD_LABELS[brand?.country ?? "AT"];
}

export function compositionDuration(clip: Clip): number {
  return Number(clip.composition.reduce((acc, s) => acc + Math.max(0, s.end - s.start), 0).toFixed(1));
}

export type HookFields = Omit<HookVersion, "id" | "clip_id" | "version" | "created_by" | "created_at">;

export function buildDemoHookV1(candidate: Candidate, source: Source, brand: BrandProfile | null, clip: Clip): HookFields {
  const ctx = {
    clipText: candidate.rubric.text,
    audience: source.brief.audience,
    hookEvidence: candidate.rubric.scores?.hook?.evidence,
    payoffEvidence: candidate.rubric.scores?.payoff?.evidence,
    titleCard: clip.title_card,
    profile: lintProfileFrom(brand),
  };
  const variants = demoHookVariants(ctx);
  const chosen = variants.find((v) => v.claim_issues.length === 0) ?? variants[0];
  const { post_captions, cta } = demoPostCaptions(ctx);
  return {
    spoken_hook: chosen.spoken,
    onscreen_hook: chosen.onscreen,
    pattern: chosen.pattern,
    variants,
    post_captions,
    cta,
    lint_notes: chosen.lint_notes,
    claim_issues: chosen.claim_issues,
    origin: "llm",
    model_id: DEMO_MODEL_ID,
    prompt_version: HOOK_PROMPT_VERSION,
  };
}

export type CaptionFields = Omit<CaptionVersion, "id" | "clip_id" | "version" | "created_by" | "created_at">;

export function buildDemoCaptions(clip: Clip, candidate: Candidate, words: TranscriptWord[] | null, brand: BrandProfile | null): CaptionFields {
  const preset = presetFor(captionPresetFor(clip.platform, clip.aspect, brand));
  const layout = layoutFor(preset, clip.aspect);
  const timed = words && words.length
    ? wordsOnOutputTimeline(words, clip.composition)
    : wordsFromText(candidate.rubric.text, compositionDuration(clip));
  const built = buildCaptionCards(timed, layout.max_chars, preset.max_lines);
  return {
    preset: preset.name,
    cards: built.cards,
    ass_key: null,
    srt_key: null,
    cps_warnings: built.cps_warnings,
    origin: "auto",
  };
}

export interface DemoRenderResult {
  patch: Partial<Clip>;
}

export function buildDemoRenderPlan(
  clip: Clip,
  candidate: Candidate,
  source: Source,
  hook: HookVersion | null,
  captions: CaptionFields,
  transcriptVersion: number,
): RenderPlan {
  const size = ASPECT_SIZE[clip.aspect];
  const fps = source.fps ?? 25;
  const preset = presetFor(captions.preset);
  const layout = layoutFor(preset, clip.aspect);
  const srcW = source.width ?? 1920;
  const srcH = source.height ?? 1080;
  /* Ausschnitt in voller Höhe der Quelle; wo er waagerecht sitzt, entscheidet unten die
   * erfundene Sitzposition je Abschnitt. */
  const cropW = Math.round((srcH * size.width) / size.height);
  return {
    contract: "render_plan_v1",
    platform: clip.platform,
    aspect: clip.aspect,
    output: { width: size.width, height: size.height, fps },
    segments: clip.composition,
    filler_cuts: false,
    reframe: { strategy: "neutral", detector: "none", faces_detected: false, positions: [], min_shot_s: 1.2 },
    /* Im Demo-Modus laeuft kein Worker, es gibt also keine Gesichtserkennung. Damit die Zeitleiste
     * trotzdem zeigt, was sie im Betrieb zeigt, wird jedes Segment in Abschnitte von rund acht
     * Sekunden geteilt und mit zwei Sitzpositionen versehen. Das ist erfunden und heisst hier auch
     * so; ohne das saehe der Demo-Modus aus, als koennte das Werkzeug keine Kameraschnitte. */
    shots: clip.composition.flatMap((s) => {
      const positionen = [Math.round(srcW * 0.3), Math.round(srcW * 0.68)];
      const n = Math.max(1, Math.round((s.end - s.start) / 8));
      const schritt = (s.end - s.start) / n;
      return Array.from({ length: n }, (_, i) => {
        const quelle = positionen[i % positionen.length];
        return {
          start: Math.round((s.start + i * schritt) * 1000) / 1000,
          end: Math.round((s.start + (i + 1) * schritt) * 1000) / 1000,
          crop_x: Math.max(0, Math.min(srcW - Math.min(srcW, cropW), Math.round(quelle - cropW / 2))),
          crop_y: 0,
          crop_w: Math.min(srcW, cropW),
          crop_h: srcH,
          layout: "single" as const,
          quelle_x: quelle,
          auswahl: positionen,
          grund: "sprecher",
        };
      });
    }),
    captions: {
      preset: captions.preset,
      font: preset.font,
      font_px: layout.font_px,
      max_chars: layout.max_chars,
      baseline_y: layout.baseline_y,
      safe_zone: {
        top: layout.safe.top,
        bottom: layout.height - layout.safe.bottom,
        left: layout.safe.left,
        right: layout.width - layout.safe.right,
      },
      cards: captions.cards.length,
      highlight: preset.highlight_words,
    },
    title_card: clip.title_card ? { text: clip.title_card, seconds: 2.5 } : null,
    hook_overlay: hook?.onscreen_hook ? { text: hook.onscreen_hook, seconds: 3 } : null,
    audio: { preset: "master", lufs: -16, true_peak: -1.5, micro_fade_ms: 20 },
    sources: {
      storage_key: source.storage_key,
      transcript_version: transcriptVersion,
      hook_version: hook?.version ?? 0,
      candidate_id: candidate.id,
    },
    versions: { captions_de: "captions_v1", render: "render_v1", reframe: "reframe_v2" },
  };
}

export function buildDemoRenderPatch(clip: Clip, source: Source, brand: BrandProfile | null, plan: RenderPlan, captions: CaptionFields): Partial<Clip> {
  const size = ASPECT_SIZE[clip.aspect];
  return {
    status: "rendered",
    render_plan: plan,
    duration_s: compositionDuration(clip),
    width: size.width,
    height: size.height,
    fps: source.fps ?? 25,
    loudness: { integrated_lufs: -16, true_peak_dbtp: -1.5, preset: "master" },
    provenance: {
      c2pa: "skipped",
      reason: "c2patool nicht installiert",
      ai_label_required: false,
      ai_features: [],
      source_credit:
        source.rights_status === "third_party"
          ? `Quelle: ${[source.source_owner, source.source_title].filter(Boolean).join(", ") || "Fremdmaterial"}`
          : null,
      ad_label: adLabelFor(source, brand),
    },
    cps_warnings: captions.cps_warnings,
    fidelity_warnings: [],
    render_error: null,
    rendered_at: new Date().toISOString(),
    /* Demo: keine Dateien im Bucket, die Export-Links bleiben deaktiviert */
    file_key: null,
    srt_key: null,
    vtt_key: null,
    poster_key: null,
    /* Filmstreifen zum Demo-Video, damit die Zeitleiste Einzelbilder zeigt statt eines leeren
     * Kastens. Beides ist ein synthetisches Testbild und kein echtes Material: in ein
     * oeffentliches Repository gehoeren keine erkennbaren Menschen. */
    filmstrip_key: "/demo/streifen.jpg",
    filmstrip_meta: { bilder: 20, breite: 60, hoehe: 108, dauer_s: 38 },
  };
}

export const ALL_PLATFORMS = PLATFORMS;
