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
 * nur Grenzkandidat mit großgeschriebenem Folgewort und ohne offene Klammer; ab 25 s oder 40 Wörtern
 * die nächste Pause ohne offene Klammer, sonst die längste Pause bis zur doppelten Grenze.
 * v1_fallback_no_punct: Regel v2 bei kaum Satzzeichen, entscheidet wie v1 mit der Längengrenze. */
export type SentenceRule = "v1" | "v2" | "v1_fallback_no_punct";
export type SentenceEndKind = "punct" | "speaker_change" | "pause_candidate" | "length_cap" | "end_of_text" | "none";

export interface WordLike {
  text: string;
  start: number;
  end: number;
  speaker?: string | null;
}

export const FALLBACK_NO_PUNCT = "v1_fallback_no_punct";
export const MAX_SENTENCE_S = 25;
export const MAX_SENTENCE_WORDS = 40;
const WORDS_PER_PUNCT_MIN = 40;

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
  "ein", "eine", "einen", "einem", "einer", "eines", "des", "der", "dem", "den",
  "bei", "von", "zum", "zur", "für", "gegen", "ohne", "in", "im", "ins", "am", "ans", "beim", "vom",
  "seit", "zwischen", "hinter", "neben", "wegen", "trotz", "aufs", "fürs", "bis",
  ...SUBORDINATORS,
]);
const NOT_PARTICIPLE = new Set([
  "insgesamt", "bestimmt", "bereit", "bekannt", "gestern", "überhaupt", "derzeit", "beliebt", "verschieden",
]);
const NOT_INFINITIVE = new Set([
  "einen", "keinen", "meinen", "deinen", "seinen", "ihren", "unseren", "euren", "diesen", "jenen",
  "welchen", "allen", "vielen", "wenigen", "anderen", "eben", "neben", "gegen", "wegen", "oben",
  "unten", "morgen", "denen", "deren", "ihnen", "seiten", "trotzdem", "zusammen", "dafür",
  "stattdessen", "indessen", "unterdessen", "währenddessen", "deswegen", "weswegen", "übrigen",
  "gestern", "selten", "innen", "außen", "hinten", "vorn", "vorne", "drinnen", "draußen",
]);
const DETERMINERS_E = new Set([
  "die", "eine", "keine", "meine", "deine", "seine", "ihre", "unsere", "eure", "diese", "jene", "welche",
  "alle", "viele", "manche", "einige", "beide",
]);
const NEW_SENTENCE_STARTERS = new Set([
  "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "aber",
  "oder", "denn", "doch", "jetzt", "dann", "heute", "jeder", "jede", "jedes", "ich", "du", "er", "sie",
  "es", "wir", "man", "so", "also", "deshalb", "deswegen", "da", "hier", "dort", "was", "wer", "wie",
  "wo", "warum", "seitdem", "danach", "außerdem", "trotzdem", "allerdings", "wobei", "nein", "ja",
  "genau", "okay", "gut", "dieser", "diese", "dieses", "unser", "unsere", "mein", "meine", "kein",
  "keine", "niemand", "alle", "viele",
]);
const PERSONAL_PRONOUNS = new Set(["ich", "du", "er", "sie", "es", "wir", "ihr", "man"]);
const PARTICIPLE = new RegExp(
  "^(?:" +
    "[a-zäöüß]*ge[a-zäöüß]{3,}(?:t|en)" +
    "|(?:vor|an|zu|auf|ab|aus|ein|nach|mit)?(?:be|ver|er|ent|zer|emp|miss)[a-zäöüß]{3,}(?:t|en)" +
    "|(?:über|unter|wider|hinter|voll)[a-zäöüß]{3,}(?:t|en)" +
    "|[a-zäöüß]{3,}iert" +
    "|getan" +
    ")$",
);
const INFINITIVE = /^[a-zäöüß]{2,}(?:en|ern|eln)$/;
const VERB_LIKE = /^[a-zäöüß]{2,}(?:e|st|t|en|ern|eln|te|ten)$/;
const TRAILING_CHARS = "\"'»«“”‘’)]}…";
const CLOSERS = "\"'»«“”‘’)]}";
const LEADING_CHARS = "\"'„»«“”‘’([{";
const OPEN_CLAUSE = [",", ";", ":"];
const CLAUSE_END = [",", ";", ":", ".", "!", "?"];
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

function baseRule(rule: SentenceRule): "v1" | "v2" {
  return rule === "v2" ? "v2" : "v1";
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
  const abbreviations = rule === "v2" ? ABBREVIATIONS_V2 : ABBREVIATIONS;
  if (abbreviations.has(base)) return true;
  const parts = base.split(".").filter(Boolean);
  if (rule === "v2" && parts.length < 2) return false;
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
  return stripped.endsWith(".") && !isOrdinal(stripped) && !isAbbreviation(stripped, baseRule(rule));
}

function endsOpenClause(text: string): boolean {
  return endsWithAny(rstripChars(text, CLOSERS), OPEN_CLAUSE);
}

function endsClause(text: string): boolean {
  return endsWithAny(rstripChars(text, CLOSERS), CLAUSE_END);
}

function isNounLike(w: WordLike): boolean {
  const t = wordText(w);
  return isUpper(t) && !NEW_SENTENCE_STARTERS.has(coreToken(t));
}

export function isParticiple(text: string): boolean {
  const tok = coreToken(text);
  return isLower(text) && !NOT_PARTICIPLE.has(tok) && PARTICIPLE.test(tok);
}

export function isInfinitive(text: string): boolean {
  const tok = coreToken(text);
  return isLower(text) && !NOT_INFINITIVE.has(tok) && INFINITIVE.test(tok);
}

function adjectiveBeforeNoun(seq: WordLike[], k: number): boolean {
  if (k + 1 >= seq.length || endsClause(wordText(seq[k]))) return false;
  const tok = coreToken(wordText(seq[k]));
  return ["e", "en", "er", "es", "em"].some((e) => tok.endsWith(e)) && isNounLike(seq[k + 1]);
}

function clause<T extends WordLike>(words: T[], clauseLevel: boolean): T[] {
  let start = 0;
  for (let j = 0; j < words.length - 1; j += 1) {
    const t = wordText(words[j]);
    if (hasTerminalPunct(t) || (clauseLevel && endsOpenClause(t))) start = j + 1;
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

  const verbLike = (seq: WordLike[], k: number): boolean => {
    const t = wordText(seq[k]);
    const tok = coreToken(t);
    if (DETERMINERS_E.has(tok) || adjectiveBeforeNoun(seq, k)) return false;
    return AUXILIARY_SET.has(tok) || isParticiple(t) || (isLower(t) && VERB_LIKE.test(tok));
  };

  const r0 = wordText(rw);
  if (isLower(r0) && PARTICLE_SET.has(coreToken(r0)) && endsWithAny(rstripChars(r0, CLOSERS), CLAUSE_END)) {
    const sentence = clause(left, false);
    if (sentence.some((_w, k) => verbLike(sentence, k))) {
      return {
        open: true,
        signal: "separable_particle",
        detail: `Verbpartikel „${coreToken(r0)}“ gehört zum Verb davor`,
        available: "heuristic",
      };
    }
  }

  if (!endsOpenClause(wordText(lw))) {
    const part = clause(left, true);
    const at = part.findIndex((w) => SUBORDINATOR_SET.has(coreToken(wordText(w))));
    if (at >= 0) {
      let verbAfter = false;
      for (let k = at + 1; k < part.length; k += 1) if (verbLike(part, k)) verbAfter = true;
      if (!verbAfter) {
        return {
          open: true,
          signal: "subordinate_clause",
          detail: `Nebensatz mit „${coreToken(wordText(part[at]))}“ ohne Verb am Ende`,
          available: "heuristic",
        };
      }
    }
  }

  if (isUpper(r0) && NEW_SENTENCE_STARTERS.has(coreToken(r0))) return closed;
  const sentence = clause(left, false);
  let auxAt = -1;
  sentence.forEach((w, k) => {
    if (AUXILIARY_SET.has(coreToken(wordText(w)))) auxAt = k;
  });
  if (auxAt < 0) return closed;
  const joined = [...sentence, ...right.slice(0, 1)];
  let isClosed = false;
  for (let k = auxAt + 1; k < sentence.length; k += 1) {
    if (isParticiple(wordText(sentence[k])) && !adjectiveBeforeNoun(joined, k)) isClosed = true;
  }
  const lastK = sentence.length - 1;
  if (sentence.length > auxAt + 1 && isInfinitive(wordText(sentence[lastK])) && !adjectiveBeforeNoun(joined, lastK)) {
    isClosed = true;
  }
  if (isClosed) return closed;
  const scan = right.slice(0, RIGHT_SCAN_WORDS);
  for (let k = 0; k < scan.length; k += 1) {
    const t = wordText(scan[k]);
    const tok = coreToken(t);
    if (AUXILIARY_SET.has(tok)) break;
    if (PERSONAL_PRONOUNS.has(tok) && k + 1 < scan.length && verbLike(scan, k + 1)) break;
    if (!adjectiveBeforeNoun(scan, k)) {
      const final = endsWithAny(rstripChars(t, CLOSERS), CLAUSE_END);
      if (isParticiple(t) || (isInfinitive(t) && final)) {
        return {
          open: true,
          signal: "auxiliary_bracket",
          detail: `„${wordText(sentence[auxAt])}“ und „${tok}“ gehören zusammen`,
          available: "heuristic",
        };
      }
    }
    if (hasTerminalPunct(t)) break;
  }
  return closed;
}

/* Port von dach_nlp.resolve_sentence_rule: unter v2 mit weniger als einem Satzzeichen je 40 Wörtern
 * gilt v1 (v1_fallback_no_punct). */
export function resolveSentenceRule(words: WordLike[], rule: SentenceRule): SentenceRule {
  if (rule !== "v2" || words.length === 0) return rule;
  const punct = words.filter((w) => hasTerminalPunct(wordText(w))).length;
  return punct * WORDS_PER_PUNCT_MIN >= words.length ? "v2" : FALLBACK_NO_PUNCT;
}

/* Die Satzregel einer Transkriptversion aus stats.sentence_rule; ohne Angabe v1 (Stand vor AP2). */
export function sentenceRuleFromStats(stats: { sentence_rule?: string | null } | null | undefined): SentenceRule {
  const rule = stats?.sentence_rule;
  return rule === "v2" || rule === FALLBACK_NO_PUNCT ? rule : "v1";
}

function runningSentence<T extends WordLike>(words: T[], i: number, rule: SentenceRule): T[] {
  let a = i;
  while (a > 0 && i - a < BRACKET_MAX_WORDS && !hasTerminalPunct(wordText(words[a - 1]), rule)) a -= 1;
  return words.slice(a, i + 1);
}

function endsOpen(sentence: WordLike[]): boolean {
  const tok = coreToken(wordText(sentence[sentence.length - 1]));
  if (!PAUSE_OPEN_END_WORDS.has(tok)) return false;
  if (tok === "ein") {
    return !sentence.slice(0, -1).some((w) => {
      const t = wordText(w);
      const c = coreToken(t);
      return !AUXILIARY_SET.has(c) && !DETERMINERS_E.has(c) && isLower(t) && VERB_LIKE.test(c);
    });
  }
  return true;
}

function pauseBoundaryAccepted(words: WordLike[], i: number, rule: SentenceRule): boolean {
  if (!isUpper(wordText(words[i + 1])) || endsOpenClause(wordText(words[i]))) return false;
  const left = runningSentence(words, i, rule);
  if (endsOpen(left)) return false;
  return !bracketHeuristic(left, words.slice(i + 1, i + 1 + RIGHT_SCAN_WORDS)).open;
}

function gap(words: WordLike[], j: number): number {
  return Number(words[j + 1].start ?? 0) - Number(words[j].end ?? 0);
}

/* Port von dach_nlp._mag_title: „Mag." (Magister) unter v2 nur vor großgeschriebenem Wort, ohne Pause,
 * ohne Sprecherwechsel und nicht nach einem Personalpronomen („Ich mag." bleibt Satzende). */
function magTitle(words: WordLike[], i: number, minPauseS: number): boolean {
  if (lstripChars(wordText(words[i]), LEADING_CHARS).toLowerCase() !== "mag." || i + 1 >= words.length) return false;
  const nxt = words[i + 1];
  if (!isUpper(wordText(nxt)) || gap(words, i) >= minPauseS) return false;
  if (nxt.speaker !== undefined && nxt.speaker !== null && nxt.speaker !== words[i].speaker) return false;
  return !(i > 0 && PERSONAL_PRONOUNS.has(coreToken(wordText(words[i - 1]))));
}

function baseKind(words: WordLike[], i: number, rule: "v1" | "v2", minPauseS: number): SentenceEndKind {
  const w = words[i];
  const text = wordText(w);
  const nxt = words[i + 1];
  if (!nxt) return "end_of_text";
  const speakerChange = nxt.speaker !== undefined && nxt.speaker !== null && nxt.speaker !== w.speaker;
  const stripped = stripTrailing(text);
  if (rule === "v2" && endsWithEllipsis(text)) {
    /* Abbruch, kein Satzzeichen: Sprecherwechsel und Pause entscheiden */
  } else if (/[!?…]$/.test(stripped)) {
    return "punct";
  } else if (stripped.endsWith(".")) {
    const nextText = wordText(nxt);
    const title = rule === "v2" && magTitle(words, i, minPauseS);
    if (!(isOrdinal(stripped) || /^\d/.test(nextText) || isAbbreviation(stripped, rule) || title)) return "punct";
  }
  if (speakerChange) return "speaker_change";
  if (gap(words, i) >= minPauseS && (rule === "v1" || pauseBoundaryAccepted(words, i, rule))) return "pause_candidate";
  return "none";
}

function tooLong(words: WordLike[], start: number, j: number, maxS: number, maxWords: number): boolean {
  return j - start + 1 >= maxWords || Number(words[j].end ?? 0) - Number(words[start].start ?? 0) >= maxS;
}

function softCandidate(words: WordLike[], start: number, j: number, minPauseS: number): boolean {
  if (gap(words, j) < minPauseS) return false;
  const left = words.slice(Math.max(start, j - BRACKET_MAX_WORDS + 1), j + 1);
  if (endsOpen(left)) return false;
  return !bracketHeuristic(left, words.slice(j + 1, j + 1 + RIGHT_SCAN_WORDS)).open;
}

/* Python rundet mit round(x, 2) (Banker-Rundung nur bei exakten Hälften, die bei Lücken praktisch nicht vorkommen). */
function round2(x: number): number {
  return Math.round(x * 100) / 100;
}

function lengthBreaks(
  words: WordLike[],
  h: number,
  stop: number,
  minPauseS: number,
  maxS: number,
  maxWords: number,
): Map<number, SentenceEndKind> {
  const out = new Map<number, SentenceEndKind>();
  let start = h;
  while (start < stop) {
    let cap = -1;
    for (let c = start; c <= stop; c += 1) {
      if (tooLong(words, start, c, maxS, maxWords)) {
        cap = c;
        break;
      }
    }
    if (cap < 0 || cap >= stop) break;
    let windowEnd = stop;
    for (let e = cap; e <= stop; e += 1) {
      if (tooLong(words, start, e, 2 * maxS, 2 * maxWords)) {
        windowEnd = e;
        break;
      }
    }
    const last = Math.min(windowEnd, stop - 1);
    let k = -1;
    for (let j = cap; j <= last; j += 1) {
      if (softCandidate(words, start, j, minPauseS)) {
        k = j;
        break;
      }
    }
    if (k >= 0) {
      out.set(k, "pause_candidate");
    } else if (windowEnd >= stop) {
      break;
    } else {
      k = cap;
      for (let j = cap + 1; j <= last; j += 1) if (round2(gap(words, j)) > round2(gap(words, k))) k = j;
      out.set(k, "length_cap");
    }
    start = k + 1;
  }
  return out;
}

export interface SentenceLimits {
  maxS?: number;
  maxWords?: number;
  minPauseS?: number;
}

/* Port von dach_nlp.sentence_end_kinds: alle Wörter in einem Durchgang. */
export function sentenceEndKinds(words: WordLike[], rule: SentenceRule = "v2", limits: SentenceLimits = {}): SentenceEndKind[] {
  const minPauseS = limits.minPauseS ?? MIN_PAUSE_S;
  const base = baseRule(rule);
  const kinds = words.map((_w, i) => baseKind(words, i, base, minPauseS));
  if (rule === "v1") return kinds;
  const maxS = limits.maxS ?? MAX_SENTENCE_S;
  const maxWords = limits.maxWords ?? MAX_SENTENCE_WORDS;
  let h = 0;
  for (let i = 0; i < kinds.length; i += 1) {
    if (kinds[i] === "none") continue;
    for (const [j, kind] of lengthBreaks(words, h, i, minPauseS, maxS, maxWords)) kinds[j] = kind;
    h = i + 1;
  }
  return kinds;
}

/* Port von dach_nlp.sentence_end_kind. */
export function sentenceEndKind(
  words: WordLike[],
  i: number,
  rule: SentenceRule = "v2",
  limits: SentenceLimits = {},
): SentenceEndKind {
  const minPauseS = limits.minPauseS ?? MIN_PAUSE_S;
  const base = baseRule(rule);
  const kind = baseKind(words, i, base, minPauseS);
  if (rule === "v1" || kind !== "none") return kind;
  let h = i;
  while (h > 0 && baseKind(words, h - 1, base, minPauseS) === "none") h -= 1;
  let stop = i + 1;
  while (baseKind(words, stop, base, minPauseS) === "none") stop += 1;
  const breaks = lengthBreaks(words, h, stop, minPauseS, limits.maxS ?? MAX_SENTENCE_S, limits.maxWords ?? MAX_SENTENCE_WORDS);
  return breaks.get(i) ?? "none";
}

/* Port von dach_nlp.cut_boundary_kind: für Schnitte (Satzgrenzen-Tor). Unter v2 gilt ein Sprecherwechsel
 * nach Komma, Semikolon oder Doppelpunkt nicht als Satzende (Einwurf des Gegenübers mitten im Satz). */
export function cutBoundaryKind(
  words: WordLike[],
  i: number,
  rule: SentenceRule = "v2",
  limits: SentenceLimits = {},
): SentenceEndKind {
  const kind = sentenceEndKind(words, i, rule, limits);
  if (rule === "v2" && kind === "speaker_change" && endsOpenClause(wordText(words[i]))) return "none";
  return kind;
}

export function isSentenceEnd(words: WordLike[], i: number, rule: SentenceRule = "v1"): boolean {
  return sentenceEndKind(words, i, rule) !== "none";
}

function hasSentenceIdx(words: TranscriptWord[]): boolean {
  return words.length > 0 && words.every((w) => typeof w.sentence_idx === "number");
}

/* Sätze aus sentence_idx, fortlaufend ab 0 nummeriert wie segment.sentences_from_annotated im Worker;
 * ohne sentence_idx Rückfall auf die Satzende-Regel ``rule`` (Standard v1 wie unter Fassung 1; die Regel
 * der Transkriptversion liefert sentenceRuleFromStats). */
export function sentencesFromWords(words: TranscriptWord[], rule: SentenceRule = "v1"): Sentence[] {
  const out: Sentence[] = [];
  const push = (start: number, i: number) => {
    const chunk = words.slice(start, i + 1);
    out.push({
      idx: out.length,
      text: chunk.map((w) => w.text).join(" "),
      start: chunk[0].start,
      end: chunk[chunk.length - 1].end,
      speaker: chunk[0].speaker,
      word_range: [start, i],
    });
  };
  if (!hasSentenceIdx(words)) {
    const kinds = sentenceEndKinds(words, rule);
    let start = 0;
    for (let i = 0; i < words.length; i += 1) {
      if (kinds[i] === "none") continue;
      push(start, i);
      start = i + 1;
    }
    return out;
  }
  let start = 0;
  for (let i = 0; i < words.length; i += 1) {
    if (i + 1 < words.length && words[i + 1].sentence_idx === words[i].sentence_idx) continue;
    push(start, i);
    start = i + 1;
  }
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
