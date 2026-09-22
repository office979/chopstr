import type { Address, Country, GenderMode } from "@/lib/repo/types";

/* Deterministischer Copy-Linter: Spiegel der Kernregeln von workers/chopstr_worker/pipeline/copy_de.lint.
 * Korrigiert nur Eindeutiges (Em-Dash, ß bei CH), alles andere sind Hinweise. Muss mit dem Worker
 * identisch bleiben, damit Hook-Studio und Worker dieselben Hinweise zeigen. */

export const AI_FLOSKELN = [
  "essenziell", "nahtlos", "maßgeschneidert", "vielfältig", "ganzheitlich", "im digitalen zeitalter",
  "in der heutigen welt", "es ist wichtig zu beachten", "zusammenfassend lässt sich", "tauche ein",
  "revolutionär", "game changer", "gamechanger", "entfessle", "auf das nächste level", "spannend",
];

export const WORN_HOOKS = [
  "du glaubst nicht", "wenn ich das früher gewusst hätte", "niemand spricht darüber",
  "das hat mein leben verändert", "warte bis zum ende",
];

const DU_FORMS = /\b(du|dich|dir|dein|deine|deinen|deinem|deiner|euch|euer|eure)\b/i;
/* case-sensitiv: großes Sie */
const SIE_FORMS = /\b(Sie|Ihnen|Ihr|Ihre|Ihren|Ihrem|Ihrer)\b/;
const GENDER_CHARS = /(\w+)[*:_](innen|in)\b/u;

export const SPOKEN_HOOK_MAX_WORDS = 12;
export const ONSCREEN_HOOK_MAX_WORDS = 9;

export interface LintProfile {
  address: Address;
  country: Country;
  gender_mode: GenderMode;
  banned_phrases: string[];
}

export const DEFAULT_LINT_PROFILE: LintProfile = {
  address: "du",
  country: "AT",
  gender_mode: "neutral",
  banned_phrases: [],
};

export interface LintResult {
  text: string;
  notes: string[];
}

export function countWords(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

export function lintCopy(input: string, profile: LintProfile = DEFAULT_LINT_PROFILE): LintResult {
  const notes: string[] = [];
  let out = input;

  if (out.includes("—")) {
    out = out.replace(/ — /g, ", ").replace(/—/g, ", ");
    notes.push("Em-Dash ersetzt (im Deutschen unüblich)");
  }
  if ((out.match(/–/g) ?? []).length > 1) {
    notes.push("Mehrere Gedankenstriche: wirkt KI-generiert");
  }

  const low = out.toLowerCase();
  for (const f of [...AI_FLOSKELN, ...profile.banned_phrases.map((b) => b.toLowerCase())]) {
    if (f && low.includes(f)) notes.push(`Floskel: '${f}'`);
  }
  for (const h of WORN_HOOKS) {
    if (low.includes(h)) notes.push(`Abgenutzter Hook: '${h}'`);
  }
  if (/\bnicht\b[^.]{0,40}, sondern\b/.test(low)) {
    notes.push("Muster 'nicht A, sondern B': sparsam einsetzen");
  }

  const hasDu = DU_FORMS.test(out);
  const hasSie = SIE_FORMS.test(out);
  if (profile.address === "sie" && hasDu) notes.push("Du-Form in Sie-Profil");
  if (profile.address === "du" && hasSie && !out.startsWith("Sie ") && !out.startsWith("Ihr ")) {
    notes.push("Mögliche Sie-Form in Du-Profil prüfen");
  }

  if (profile.country === "CH" && out.includes("ß")) {
    out = out.replace(/ß/g, "ss");
    notes.push("ß zu ss (CH)");
  }

  if (["neutral", "paarform", "keine"].includes(profile.gender_mode) && GENDER_CHARS.test(out)) {
    notes.push("Genderzeichen im Wortinneren passen nicht zum Profil");
  }

  return { text: out, notes };
}

/* Hook-Linter: Copy-Regeln plus Wortlimit (gesprochen 12, On-Screen 9) */
export function lintHook(input: string, kind: "spoken" | "onscreen", profile: LintProfile = DEFAULT_LINT_PROFILE): LintResult {
  const result = lintCopy(input, profile);
  const max = kind === "spoken" ? SPOKEN_HOOK_MAX_WORDS : ONSCREEN_HOOK_MAX_WORDS;
  const words = countWords(result.text);
  if (words > max) {
    result.notes.push(`${words} Wörter, erlaubt sind ${max} (${kind === "spoken" ? "gesprochener Hook" : "On-Screen-Hook"})`);
  }
  return result;
}
