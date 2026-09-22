import type { HookPattern, HookVariant, HookVersion, Platform, PostCaptions, SaveHookInput } from "@/lib/repo/types";
import { hookClaimCheck } from "@/lib/copy/claims";
import { lintCopy, lintHook, type LintProfile } from "@/lib/copy/lint";
import { PLATFORMS } from "@/lib/clips/labels";

/* Hook-Versionen: gemeinsame Logik für Demo- und Postgres-Repository */

export interface HookContext {
  clipText: string;
  profile: LintProfile;
}

export type ManualHookFields = Pick<
  HookVersion,
  "spoken_hook" | "onscreen_hook" | "pattern" | "variants" | "post_captions" | "cta" | "lint_notes" | "claim_issues" | "origin" | "model_id" | "prompt_version"
>;

/* Manuelle Version aus dem Hook-Studio: Linter und Claim-Check laufen serverseitig noch einmal,
 * Varianten der Vorversion bleiben erhalten (sie sind die Auswahlbasis im Studio). */
export function prepareManualHook(input: SaveHookInput, ctx: HookContext, prev: HookVersion | null): ManualHookFields {
  const spoken = lintHook(input.spoken_hook.trim(), "spoken", ctx.profile);
  const onscreen = lintHook(input.onscreen_hook.trim(), "onscreen", ctx.profile);
  const notes = [...spoken.notes, ...onscreen.notes];
  const issues = [...hookClaimCheck(spoken.text, ctx.clipText), ...hookClaimCheck(onscreen.text, ctx.clipText)];
  const captions: PostCaptions = {};
  for (const p of PLATFORMS) {
    const raw = input.post_captions[p];
    if (typeof raw !== "string") continue;
    const linted = lintCopy(raw.trim(), ctx.profile);
    captions[p] = linted.text;
    for (const n of linted.notes) notes.push(`Post-Caption ${p}: ${n}`);
    for (const i of hookClaimCheck(linted.text, ctx.clipText)) issues.push(`Post-Caption ${p}: ${i}`);
  }
  return {
    spoken_hook: spoken.text,
    onscreen_hook: onscreen.text,
    pattern: input.pattern,
    variants: prev?.variants ?? [],
    post_captions: captions,
    cta: input.cta.trim() || null,
    lint_notes: [...new Set(notes)],
    claim_issues: [...new Set(issues)],
    origin: "manual",
    model_id: null,
    prompt_version: prev?.prompt_version ?? "hooks_v1",
  };
}

/* ---------------------------------------------------------------------------------------------
 * Demo: fünf Hook-Varianten aus dem Clip-Text (deterministisch, kein Sprachmodell).
 * Eine Variante trägt Lint-Hinweise (Em-Dash, Floskel), eine Claim-Issues (Zahl, die nicht im Clip steht).
 * ------------------------------------------------------------------------------------------- */

export interface DemoHookInput {
  clipText: string;
  audience: string | null | undefined;
  hookEvidence: string | null | undefined;
  payoffEvidence: string | null | undefined;
  titleCard: string | null | undefined;
  profile: LintProfile;
}

function firstWords(text: string, max: number): string {
  const words = text
    .replace(/^SPEAKER_\d+:\s*/gm, "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean)
    .slice(0, max);
  const joined = words.join(" ").replace(/[,;:]$/, "");
  return /[.!?]$/.test(joined) ? joined : `${joined}.`;
}

function audienceShort(audience: string | null | undefined): string {
  const first = (audience ?? "").split(",")[0]?.trim();
  return first || "Entscheider im Mittelstand";
}

function applyLint(pattern: HookPattern, spoken: string, onscreen: string, ctx: DemoHookInput): HookVariant {
  const s = lintHook(spoken, "spoken", ctx.profile);
  const o = lintHook(onscreen, "onscreen", ctx.profile);
  return {
    pattern,
    spoken: s.text,
    onscreen: o.text,
    lint_notes: [...s.notes, ...o.notes],
    claim_issues: [...hookClaimCheck(s.text, ctx.clipText), ...hookClaimCheck(o.text, ctx.clipText)],
  };
}

export function demoHookVariants(ctx: DemoHookInput): HookVariant[] {
  const audience = audienceShort(ctx.audience);
  const hook = firstWords(ctx.hookEvidence || ctx.clipText, 9);
  const payoff = firstWords(ctx.payoffEvidence || ctx.clipText, 10);
  const title = ctx.titleCard?.trim() || firstWords(ctx.hookEvidence || ctx.clipText, 6).replace(/[.!?]$/, "");
  return [
    applyLint("identity_call", `Wenn du für ${audience} entscheidest, hör kurz zu.`, `Für ${audience}`, ctx),
    applyLint("contrarian", `Die meisten rechnen hier falsch. ${hook}`, "Die meisten rechnen falsch", ctx),
    applyLint("open_loop", "Eine Zahl, die kaum jemand vorher ausrechnet.", "Diese Zahl kennt kaum jemand", ctx),
    /* Claim-Issue: die Prozentzahl steht nicht im Clip */
    applyLint("results_first", `90 % sparen hier am falschen Ende. ${payoff}`, "90 % sparen am falschen Ende", ctx),
    /* Lint-Hinweise: Em-Dash wird ersetzt, Floskel bleibt als Hinweis */
    applyLint("mistake_warning", `Der teuerste Fehler beim Recruiting — und ein nahtloser Ausweg.`, `Der teuerste Fehler: ${title}`, ctx),
  ];
}

export function demoPostCaptions(ctx: DemoHookInput): { post_captions: PostCaptions; cta: string } {
  const lead = firstWords(ctx.payoffEvidence || ctx.clipText, 14);
  const cta = "Wie rechnet ihr das? Schreib es in die Kommentare.";
  const post: PostCaptions = {
    tiktok: `${lead} Mehr dazu im Podcast.`,
    reels: `${lead} Ganze Folge im Profil.`,
    shorts: `${lead} Die ganze Folge findest du im Kanal.`,
    linkedin: `${lead}\n\nWir haben bei PLACEMedia nachgerechnet, was eine offene Stelle wirklich kostet. ${cta}`,
  };
  for (const p of Object.keys(post) as Platform[]) {
    post[p] = lintCopy(post[p] ?? "", ctx.profile).text;
  }
  return { post_captions: post, cta };
}
