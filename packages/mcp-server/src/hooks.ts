/* Clientseitige Prüfung der Hook-Wortlimits (hooks_v1: gesprochen max. 12, im Bild max. 9 Wörter). */

import { countWords } from "./format.js";

export const SPOKEN_HOOK_MAX_WORDS = 12;
export const ONSCREEN_HOOK_MAX_WORDS = 9;

export interface HookLimitViolation {
  field: "spoken_hook" | "onscreen_hook";
  words: number;
  max: number;
  message: string;
}

export function checkHookLimits(input: { spoken_hook?: string | null; onscreen_hook?: string | null }): HookLimitViolation[] {
  const violations: HookLimitViolation[] = [];
  const spoken = (input.spoken_hook ?? "").trim();
  const onscreen = (input.onscreen_hook ?? "").trim();
  if (spoken) {
    const words = countWords(spoken);
    if (words > SPOKEN_HOOK_MAX_WORDS) {
      violations.push({
        field: "spoken_hook",
        words,
        max: SPOKEN_HOOK_MAX_WORDS,
        message: `Gesprochener Hook hat ${words} Wörter, erlaubt sind höchstens ${SPOKEN_HOOK_MAX_WORDS}.`,
      });
    }
  }
  if (onscreen) {
    const words = countWords(onscreen);
    if (words > ONSCREEN_HOOK_MAX_WORDS) {
      violations.push({
        field: "onscreen_hook",
        words,
        max: ONSCREEN_HOOK_MAX_WORDS,
        message: `On-Screen-Hook hat ${words} Wörter, erlaubt sind höchstens ${ONSCREEN_HOOK_MAX_WORDS}.`,
      });
    }
  }
  return violations;
}

/* Stilhinweise, die der Server ohne Sprachmodell erkennen kann. Kein Ersatz für den Linter im Worker. */
export function styleNotes(text: string): string[] {
  const notes: string[] = [];
  if (/[–—]/.test(text)) notes.push("enthält einen Gedankenstrich");
  if (/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(text)) notes.push("enthält ein Emoji");
  if (/du glaubst nicht|wenn ich das früher gewusst hätte|niemand spricht darüber|hat mein leben verändert|warte bis zum ende/i.test(text)) {
    notes.push("nutzt ein abgenutztes Hook-Muster");
  }
  return notes;
}
