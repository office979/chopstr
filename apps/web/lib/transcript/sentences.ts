import type { TranscriptWord } from "@/lib/repo/types";

/* Sätze aus dem aktuellen Transkript: Gruppen gleicher sentence_idx (Spiegel von segment.sentences_from_words). */
export interface Sentence {
  idx: number;
  text: string;
  start: number;
  end: number;
  speaker: string;
  /* Wortindizes [von, bis] im Transkript */
  word_range: [number, number];
}

/* Fallback-Segmentierung: Port von dach_nlp.is_sentence_end (Satzzeichen, Abkürzungen, Ordinal- und
 * Dezimalzahlen, Pause ab 0,7 s, Sprecherwechsel). Greift nur, wenn Wörter kein sentence_idx tragen,
 * z. B. bei Transkripten, die nicht durch fuse_and_nlp gelaufen sind. Muss mit dem Worker identisch bleiben. */
const ABBREVIATIONS = new Set([
  "z", "b", "z.b", "zb", "bzw", "ca", "usw", "etc", "vgl", "dr", "prof", "nr", "st", "mio", "mrd", "tsd",
  "u", "a", "d", "h", "u.a", "d.h", "s", "o", "ä", "o.ä", "evtl", "ggf", "inkl", "exkl", "max", "min",
  "mind", "sog", "str", "tel", "hr", "fr", "ing", "mag", "dipl", "med", "jur", "phil", "abs", "art",
  "bsp", "geb", "gest", "jh", "jhd", "kap", "lt", "nachm", "vorm", "ugs", "urspr", "zzgl", "zw",
  "allg", "bes", "bzgl", "ehem", "einschl", "entspr", "erg", "gegr", "hrsg", "i", "e", "v", "chr",
  "mwst", "ust", "gmbh", "ag", "kg", "co", "sept", "okt", "nov", "dez", "jan", "feb", "mär", "apr",
  "jun", "jul", "aug", "mo", "di", "mi", "do", "sa", "so",
]);
const TRAILING = /["'»«“”‘’)\]}…]+$/;
const ORDINAL = /^\d{1,3}\.$/;
const MIN_PAUSE_S = 0.7;

function stripTrailing(text: string): string {
  return text.replace(TRAILING, "");
}

function isAbbreviation(text: string): boolean {
  const t = stripTrailing(text);
  if (!t.endsWith(".")) return false;
  const base = t.slice(0, -1).toLowerCase().replace(/ /g, "");
  if (!base) return false;
  if (ABBREVIATIONS.has(base)) return true;
  const parts = base.split(".").filter(Boolean);
  return parts.length > 0 && parts.every((p) => ABBREVIATIONS.has(p) || p.length === 1);
}

export function isSentenceEnd(words: TranscriptWord[], i: number): boolean {
  const w = words[i];
  const text = w.text.trim();
  const nxt = words[i + 1];
  if (!nxt) return true;
  const longPause = nxt.start - w.end >= MIN_PAUSE_S;
  const speakerChange = Boolean(nxt.speaker) && nxt.speaker !== w.speaker;
  const stripped = stripTrailing(text);
  if (/[!?…]$/.test(stripped)) return true;
  if (stripped.endsWith(".")) {
    const nextText = nxt.text.trim();
    if (ORDINAL.test(stripped) || /^\d/.test(nextText) || isAbbreviation(stripped)) {
      return longPause || speakerChange;
    }
    return true;
  }
  return longPause || speakerChange;
}

function hasSentenceIdx(words: TranscriptWord[]): boolean {
  return words.length > 0 && words.every((w) => typeof w.sentence_idx === "number");
}

export function sentencesFromWords(words: TranscriptWord[]): Sentence[] {
  const out: Sentence[] = [];
  if (!hasSentenceIdx(words)) {
    let start = 0;
    for (let i = 0; i < words.length; i += 1) {
      if (!isSentenceEnd(words, i)) continue;
      const chunk = words.slice(start, i + 1);
      out.push({
        idx: out.length,
        text: chunk.map((w) => w.text).join(" "),
        start: chunk[0].start,
        end: chunk[chunk.length - 1].end,
        speaker: chunk[0].speaker,
        word_range: [start, i],
      });
      start = i + 1;
    }
    return out;
  }
  let current: Sentence | null = null;
  words.forEach((w, i) => {
    if (current && current.idx === w.sentence_idx) {
      current.text += ` ${w.text}`;
      current.end = w.end;
      current.word_range[1] = i;
      return;
    }
    current = {
      idx: w.sentence_idx,
      text: w.text,
      start: w.start,
      end: w.end,
      speaker: w.speaker,
      word_range: [i, i],
    };
    out.push(current);
  });
  return out;
}

export function sentenceByIdx(sentences: Sentence[], idx: number): Sentence | undefined {
  return sentences.find((s) => s.idx === idx);
}

/* Sätze eines Bereichs in Abspielreihenfolge */
export function sentenceRange(sentences: Sentence[], first: number, last: number): Sentence[] {
  return sentences.filter((s) => s.idx >= first && s.idx <= last);
}

export interface SpeakerBlock {
  speaker: string;
  start: number;
  end: number;
  sentences: Sentence[];
}

/* Aufeinanderfolgende Sätze desselben Sprechers zusammenfassen */
export function groupBySpeaker(sentences: Sentence[]): SpeakerBlock[] {
  const blocks: SpeakerBlock[] = [];
  for (const s of sentences) {
    const last = blocks[blocks.length - 1];
    if (last && last.speaker === s.speaker) {
      last.sentences.push(s);
      last.end = s.end;
    } else {
      blocks.push({ speaker: s.speaker, start: s.start, end: s.end, sentences: [s] });
    }
  }
  return blocks;
}

/* Wörtlicher Clip-Text mit Sprechern, wie ihn der Worker in rubric.text schreibt */
export function clipText(sentences: Sentence[]): string {
  return groupBySpeaker(sentences)
    .map((b) => `${b.speaker}: ${b.sentences.map((s) => s.text).join(" ")}`)
    .join("\n");
}
