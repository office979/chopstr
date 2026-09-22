import type { FillerKind, TranscriptWord } from "@/lib/repo/types";

/* Deutsche Füllwörter (Spiegel der dach_nlp-Regeln im Worker).
 * hart: ohne Bedeutungsverlust entfernbar, weich: Vorschlag, Modalpartikel: nie anfassen. */
export const HARD_FILLERS = new Set(["ähm", "äh", "ähh", "öhm", "öh", "hm", "hmm", "mhm", "ähem"]);
export const SOFT_FILLERS = new Set(["also", "quasi", "sozusagen", "irgendwie", "genau", "praktisch"]);
export const MODAL_PARTICLES = new Set(["halt", "eigentlich", "eben", "doch", "mal", "schon", "ja", "wohl"]);
export const NEGATIONS = new Set(["nicht", "nie", "niemals", "kein", "keine", "keinen", "keiner", "keinem", "nichts", "weder", "noch"]);

export function normalize(text: string): string {
  return text.toLowerCase().replace(/[.,;:!?„“"'()]/g, "").trim();
}

export function classifyFiller(text: string): FillerKind {
  const t = normalize(text);
  if (HARD_FILLERS.has(t)) return "hard";
  if (SOFT_FILLERS.has(t)) return "soft";
  return null;
}

export function isNegation(text: string): boolean {
  return NEGATIONS.has(normalize(text));
}

export function isModalParticle(text: string): boolean {
  return MODAL_PARTICLES.has(normalize(text));
}

/* Nach einer manuellen Korrektur gilt das Wort als geprüft (Konfidenz 1). */
export function reclassify(word: TranscriptWord, newText: string): TranscriptWord {
  return {
    ...word,
    text: newText,
    prob: 1,
    filler: classifyFiller(newText),
    negation: isNegation(newText),
  };
}

export function countFillers(words: TranscriptWord[]): { hard: number; soft: number } {
  let hard = 0;
  let soft = 0;
  for (const w of words) {
    if (w.filler === "hard") hard += 1;
    else if (w.filler === "soft") soft += 1;
  }
  return { hard, soft };
}
