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

/* Satzende-Entscheidung: Port von dach_nlp.sentence_end_kind (Regel v1 und v2, AP2) samt
 * Verbklammer-Heuristik dach_nlp.bracket_heuristic (AP3). Die gemeinsame Falldatei
 * packages/editorial/parity/sentence_end_v1.json hält Worker und Web gleich (tests/satzende.test.ts).
 * Regel v1: Satzzeichen (Abkürzungen, Ordinal- und Dezimalzahlen), jede Pause ab 0,7 s, Sprecherwechsel.
 * Regel v2: Satzzeichen zuerst (Auslassungspunkte zählen nicht), Sprecherwechsel ist Grenze, eine Pause
 * nur Grenzkandidat mit großgeschriebenem Folgewort und ohne offene Klammer. */
export type SentenceRule = "v1" | "v2";
export type SentenceEndKind = "punct" | "speaker_change" | "pause_candidate" | "end_of_text" | "none";

export interface WordLike {
  text: string;
  start: number;
  end: number;
  speaker?: string | null;
}

const ABBREVIATIONS = new Set([
  "z", "b", "z.b", "zb", "bzw", "ca", "usw", "etc", "vgl", "dr", "prof", "nr", "st", "mio", "mrd", "tsd",
  "u", "a", "d", "h", "u.a", "d.h", "s", "o", "ä", "o.ä", "evtl", "ggf", "inkl", "exkl", "max", "min",
  "mind", "sog", "str", "tel", "hr", "fr", "ing", "mag", "dipl", "med", "jur", "phil", "abs", "art",
  "bsp", "geb", "gest", "jh", "jhd", "kap", "lt", "nachm", "vorm", "ugs", "urspr", "zzgl", "zw",
  "allg", "bes", "bzgl", "ehem", "einschl", "entspr", "erg", "gegr", "hrsg", "i", "e", "v", "chr",
  "mwst", "ust", "gmbh", "ag", "kg", "co", "sept", "okt", "nov", "dez", "jan", "feb", "mär", "apr",
  "jun", "jul", "aug", "mo", "di", "mi", "do", "sa", "so",
]);
/* Regel v2: ohne Wörter, die im gesprochenen Deutsch häufiger einen Satz beenden als abkürzen. */
const ABBREVIATIONS_V2 = new Set([...ABBREVIATIONS].filter((a) => !["so", "i", "mag", "max", "art", "min"].includes(a)));

export const VERB_PARTICLES = [
  "an", "auf", "aus", "ein", "mit", "zu", "ab", "vor", "nach", "zurück", "weg", "her", "hin", "los",
  "fest", "vorbei", "weiter",
];
export const SUBORDINATORS = [
  "dass", "weil", "wenn", "ob", "obwohl", "damit", "nachdem", "bevor", "als", "während", "falls",
  "sofern", "sodass",
];
export const AUXILIARY_FORMS = [
  "hab", "habe", "hast", "hat", "haben", "habt", "hatte", "hattest", "hatten", "hattet",
  "hätte", "hättest", "hätten", "hättet",
  "bin", "bist", "ist", "sind", "seid", "war", "warst", "waren", "wart", "wäre", "wärst", "wären", "wärt",
  "werde", "wirst", "wird", "werden", "werdet", "wurde", "wurdest", "wurden", "wurdet",
  "würde", "würdest", "würden", "würdet",
  "kann", "kannst", "können", "könnt", "konnte", "konntest", "konnten", "konntet",
  "könnte", "könntest", "könnten", "könntet",
  "muss", "musst", "müssen", "müsst", "musste", "musstest", "mussten", "musstet",
  "müsste", "müsstest", "müssten", "müsstet",
  "will", "willst", "wollen", "wollt", "wollte", "wolltest", "wollten", "wolltet",
  "soll", "sollst", "sollen", "sollt", "sollte", "solltest", "sollten", "solltet",
  "darf", "darfst", "dürfen", "dürft", "durfte", "durftest", "durften", "durftet",
  "dürfte", "dürftest", "dürften", "dürftet",
  "mag", "magst", "mögen", "mögt", "mochte", "mochtest", "mochten", "mochtet",
  "möchte", "möchtest", "möchten", "möchtet",
];
const PARTICLE_SET = new Set(VERB_PARTICLES);
const SUBORDINATOR_SET = new Set(SUBORDINATORS);
const AUXILIARY_SET = new Set(AUXILIARY_FORMS);
const PAUSE_OPEN_END_WORDS = new Set([
  "ein", "eine", "einen", "einem", "einer", "eines", "des",
  "bei", "von", "zum", "zur", "für", "gegen", "ohne", "in", "im", "ins", "am", "ans", "beim", "vom",
  "seit", "zwischen", "hinter", "neben", "wegen", "trotz", "aufs", "fürs",
  ...SUBORDINATORS,
]);
const NOT_INFINITIVE = new Set([
  "einen", "keinen", "meinen", "deinen", "seinen", "ihren", "unseren", "euren", "diesen", "jenen",
  "welchen", "allen", "vielen", "wenigen", "anderen", "eben", "neben", "gegen", "wegen", "oben",
  "unten", "morgen", "denen", "deren", "ihnen", "seiten", "trotzdem", "zusammen", "dafür",
  "stattdessen", "indessen", "unterdessen", "währenddessen", "deswegen", "weswegen", "übrigen",
]);
const DETERMINERS_E = new Set([
  "die", "eine", "keine", "meine", "deine", "seine", "ihre", "unsere", "eure", "diese", "jene", "welche",
  "alle", "viele", "manche", "einige", "beide",
]);
const PARTICIPLE = /^(?:[a-zäöüß]*ge[a-zäöüß]{3,}(?:t|en)|(?:be|ver|er|ent|zer|emp|miss)[a-zäöüß]{3,}t|[a-zäöüß]{3,}iert)$/;
const INFINITIVE = /^[a-zäöüß]{2,}(?:en|ern|eln)$/;
const VERB_LIKE = /^[a-zäöüß]{2,}(?:e|st|t|en|ern|eln|te|ten)$/;
const TRAILING_CHARS = "\"'»«“”‘’)]}…";
const CLOSERS = "\"'»«“”‘’)]}";
const LEADING_CHARS = "\"'„»«“”‘’([{";
const TERMINAL = [".", "!", "?"];
const CLAUSE_PUNCT = [".", "!", "?", ",", ";", ":"];
const ORDINAL = /^\d{1,3}\.$/;
const MIN_PAUSE_S = 0.7;
const BRACKET_MAX_WORDS = 40;
const RIGHT_SCAN_WORDS = 10;

function rstripChars(text: string, chars: string): string {
  let end = text.length;
  while (end > 0 && chars.includes(text[end - 1])) end -= 1;
  return text.slice(0, end);
}

function lstripChars(text: string, chars: string): string {
  let start = 0;
  while (start < text.length && chars.includes(text[start])) start += 1;
  return text.slice(start);
}

function stripTrailing(text: string): string {
  return rstripChars(text, TRAILING_CHARS);
}

function endsWithAny(text: string, ends: string[]): boolean {
  return ends.some((e) => text.endsWith(e));
}

export function coreToken(text: string): string {
  return text.toLowerCase().replace(/[^\p{L}\p{N}\p{M}_]/gu, "");
}

function wordText(w: WordLike): string {
  return String(w.text ?? "").trim();
}

function isLowerChar(c: string): boolean {
  return c.length > 0 && c.toLowerCase() === c && c.toUpperCase() !== c;
}

function isUpperChar(c: string): boolean {
  return c.length > 0 && c.toUpperCase() === c && c.toLowerCase() !== c;
}

function isLower(text: string): boolean {
  return isLowerChar(lstripChars(text, LEADING_CHARS).slice(0, 1));
}

function isUpper(text: string): boolean {
  return isUpperChar(lstripChars(text, LEADING_CHARS).slice(0, 1));
}

function isAbbreviation(text: string, rule: SentenceRule = "v1"): boolean {
  const t = stripTrailing(text);
  if (!t.endsWith(".")) return false;
  const base = t.slice(0, -1).toLowerCase().replace(/ /g, "");
  if (!base) return false;
  const abbreviations = rule === "v1" ? ABBREVIATIONS : ABBREVIATIONS_V2;
  if (abbreviations.has(base)) return true;
  const parts = base.split(".").filter(Boolean);
  if (rule !== "v1" && parts.length < 2) return false;
  return parts.length > 0 && parts.every((p) => abbreviations.has(p) || p.length === 1);
}

function isOrdinal(text: string): boolean {
  return ORDINAL.test(stripTrailing(text));
}

function endsWithEllipsis(text: string): boolean {
  const t = rstripChars(text, CLOSERS);
  return t.endsWith("…") || t.endsWith("...");
}

function hasTerminalPunct(text: string, rule: SentenceRule = "v2"): boolean {
  if (endsWithEllipsis(text)) return false;
  const stripped = stripTrailing(text);
  if (stripped.endsWith("!") || stripped.endsWith("?")) return true;
  return stripped.endsWith(".") && !isOrdinal(stripped) && !isAbbreviation(stripped, rule);
}

export function isParticiple(text: string): boolean {
  return isLower(text) && PARTICIPLE.test(coreToken(text));
}

export function isInfinitive(text: string): boolean {
  const tok = coreToken(text);
  return isLower(text) && !NOT_INFINITIVE.has(tok) && INFINITIVE.test(tok);
}

function clause<T extends WordLike>(words: T[], seps: string[]): T[] {
  let start = 0;
  for (let j = 0; j < words.length - 1; j += 1) {
    const t = wordText(words[j]);
    if (endsWithAny(stripTrailing(t), seps) || endsWithAny(t, seps)) start = j + 1;
  }
  return words.slice(start);
}

export interface BracketResult {
  open: boolean;
  signal: "separable_particle" | "subordinate_clause" | "auxiliary_bracket" | null;
  detail: string;
  available: "heuristic";
}

/* Port von dach_nlp.bracket_heuristic: drei Signale (Verbpartikel, Nebensatz, Hilfs- oder Modalverb). */
export function bracketHeuristic(leftWords: WordLike[], rightWords: WordLike[]): BracketResult {
  const left = leftWords.filter((w) => wordText(w));
  const right = rightWords.filter((w) => wordText(w));
  const closed: BracketResult = { open: false, signal: null, detail: "keine offene Klammer erkannt", available: "heuristic" };
  if (left.length === 0 || right.length === 0) return closed;
  const lw = left[left.length - 1];
  const rw = right[0];
  const ls = lw.speaker ?? null;
  const rs = rw.speaker ?? null;
  if (ls !== null && rs !== null && ls !== rs) return closed;
  if (hasTerminalPunct(wordText(lw))) return closed;

  const verbLike = (w: WordLike): boolean => {
    const t = wordText(w);
    const tok = coreToken(t);
    if (DETERMINERS_E.has(tok)) return false;
    return AUXILIARY_SET.has(tok) || isParticiple(t) || (isLower(t) && VERB_LIKE.test(tok));
  };

  const r0 = wordText(rw);
  if (isLower(r0) && PARTICLE_SET.has(coreToken(r0)) && endsWithAny(rstripChars(r0, CLOSERS), CLAUSE_PUNCT)) {
    if (clause(left, TERMINAL).some(verbLike)) {
      return {
        open: true,
        signal: "separable_particle",
        detail: `Verbpartikel „${coreToken(r0)}“ gehört zum Verb davor`,
        available: "heuristic",
      };
    }
  }

  if (!wordText(lw).endsWith(",")) {
    const part = clause(left, CLAUSE_PUNCT);
    const conn = part.map((w) => coreToken(wordText(w))).find((tok) => SUBORDINATOR_SET.has(tok));
    if (conn && !verbLike(lw)) {
      return {
        open: true,
        signal: "subordinate_clause",
        detail: `Nebensatz mit „${conn}“ ohne Verb am Ende`,
        available: "heuristic",
      };
    }
  }

  const sentence = clause(left, TERMINAL);
  let auxAt = -1;
  sentence.forEach((w, k) => {
    if (AUXILIARY_SET.has(coreToken(wordText(w)))) auxAt = k;
  });
  if (auxAt >= 0) {
    const tail = sentence.slice(auxAt + 1);
    const isClosed =
      tail.some((w) => isParticiple(wordText(w))) || (tail.length > 0 && isInfinitive(wordText(tail[tail.length - 1])));
    if (!isClosed) {
      for (const w of right.slice(0, RIGHT_SCAN_WORDS)) {
        const t = wordText(w);
        if (AUXILIARY_SET.has(coreToken(t))) break;
        const final = endsWithAny(rstripChars(t, CLOSERS), CLAUSE_PUNCT);
        if (isParticiple(t) || (isInfinitive(t) && final)) {
          return {
            open: true,
            signal: "auxiliary_bracket",
            detail: `„${wordText(sentence[auxAt])}“ und „${coreToken(t)}“ gehören zusammen`,
            available: "heuristic",
          };
        }
        if (endsWithAny(rstripChars(t, CLOSERS), TERMINAL)) break;
      }
    }
  }
  return closed;
}

function runningSentence<T extends WordLike>(words: T[], i: number, rule: SentenceRule): T[] {
  let a = i;
  while (a > 0 && i - a < BRACKET_MAX_WORDS && !hasTerminalPunct(wordText(words[a - 1]), rule)) a -= 1;
  return words.slice(a, i + 1);
}

/* Komma, Semikolon oder Doppelpunkt am Wort: der Teilsatz geht weiter. */
function endsOpenClause(text: string): boolean {
  return endsWithAny(rstripChars(text, CLOSERS), [",", ";", ":"]);
}

function pauseBoundaryAccepted(words: WordLike[], i: number, rule: SentenceRule): boolean {
  if (!isUpper(wordText(words[i + 1]))) return false;
  if (endsOpenClause(wordText(words[i])) || PAUSE_OPEN_END_WORDS.has(coreToken(wordText(words[i])))) return false;
  const left = runningSentence(words, i, rule);
  const right = words.slice(i + 1, i + 1 + RIGHT_SCAN_WORDS);
  return !bracketHeuristic(left, right).open;
}

/* Port von dach_nlp.sentence_end_kind. */
export function sentenceEndKind(
  words: WordLike[],
  i: number,
  rule: SentenceRule = "v2",
  minPauseS: number = MIN_PAUSE_S,
): SentenceEndKind {
  const w = words[i];
  const text = wordText(w);
  const nxt = words[i + 1];
  if (!nxt) return "end_of_text";
  const pause = Number(nxt.start ?? 0) - Number(w.end ?? 0);
  const speakerChange = nxt.speaker !== undefined && nxt.speaker !== null && nxt.speaker !== w.speaker;
  const stripped = stripTrailing(text);
  if (rule === "v2" && endsWithEllipsis(text)) {
    /* Abbruch, kein Satzzeichen: Sprecherwechsel und Pause entscheiden */
  } else if (/[!?…]$/.test(stripped)) {
    return "punct";
  } else if (stripped.endsWith(".")) {
    const nextText = wordText(nxt);
    if (!(isOrdinal(stripped) || /^\d/.test(nextText) || isAbbreviation(stripped, rule))) return "punct";
  }
  if (speakerChange) return "speaker_change";
  if (pause >= minPauseS && (rule === "v1" || pauseBoundaryAccepted(words, i, rule))) return "pause_candidate";
  return "none";
}

/* Port von dach_nlp.cut_boundary_kind: für Schnitte (Satzgrenzen-Tor). Unter v2 gilt ein Sprecherwechsel
 * nach Komma, Semikolon oder Doppelpunkt nicht als Satzende (Einwurf des Gegenübers mitten im Satz). */
export function cutBoundaryKind(words: WordLike[], i: number, rule: SentenceRule = "v2"): SentenceEndKind {
  const kind = sentenceEndKind(words, i, rule);
  if (rule !== "v1" && kind === "speaker_change" && endsOpenClause(wordText(words[i]))) return "none";
  return kind;
}

export function isSentenceEnd(words: WordLike[], i: number, rule: SentenceRule = "v1"): boolean {
  return sentenceEndKind(words, i, rule) !== "none";
}

function hasSentenceIdx(words: TranscriptWord[]): boolean {
  return words.length > 0 && words.every((w) => typeof w.sentence_idx === "number");
}

/* Sätze aus sentence_idx; ohne sentence_idx Rückfall auf die Satzende-Regel ``rule`` (Standard v1,
 * wie der Worker unter Fassung 1; v2 ist der Port der neuen Regel). */
export function sentencesFromWords(words: TranscriptWord[], rule: SentenceRule = "v1"): Sentence[] {
  const out: Sentence[] = [];
  if (!hasSentenceIdx(words)) {
    let start = 0;
    for (let i = 0; i < words.length; i += 1) {
      if (!isSentenceEnd(words, i, rule)) continue;
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
