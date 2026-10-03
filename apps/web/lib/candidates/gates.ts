import type { CandidateGates, GateKey, GateResult } from "@/lib/repo/types";
import {
  cutBoundaryKind,
  resolveSentenceRule,
  type Sentence,
  type SentenceEndKind,
  type SentenceRule,
  type WordLike,
} from "@/lib/transcript/sentences";

/* Deterministische Pflichtkriterien nach Verlängern/Kürzen (Spiegel von dach_nlp.ends_with_open_loop und
 * story_engine._satzgrenzen_gate unter Regel v2). standalone, fidelity und verb_bracket werden unverändert
 * übernommen; sie stammen aus Stufe 3 des Workers. */

export const OPEN_LOOP_END = new Set([
  "aber",
  "deshalb",
  "deswegen",
  "nämlich",
  "und",
  "weil",
  "denn",
  "sondern",
  "also",
  "dass",
  "wobei",
  "trotzdem",
  "und zwar",
  "obwohl",
  "oder",
  "das heißt",
  "beziehungsweise",
  "bzw.",
]);

export function endsWithOpenLoop(lastSentence: string): string | null {
  const tail = lastSentence
    .toLowerCase()
    .replace(/[^\wäöüß. ]/g, "")
    .replace(/\./g, "")
    .split(/\s+/)
    .filter(Boolean);
  if (tail.length === 0) return null;
  const two = tail.slice(-2).join(" ");
  if (OPEN_LOOP_END.has(two)) return two;
  const one = tail[tail.length - 1];
  if (OPEN_LOOP_END.has(one)) return one;
  return null;
}

export const GATE_ORDER: GateKey[] = ["standalone", "fidelity", "sentence_boundaries", "verb_bracket", "no_open_loop"];

export const GATE_LABELS: Record<GateKey, string> = {
  standalone: "Eigenständig",
  fidelity: "Sinntreu",
  sentence_boundaries: "Satzgrenzen",
  verb_bracket: "Verbklammer",
  no_open_loop: "Kein offener Satz",
};

/* Nachbarsätze der neuen Grenzen: Satz vor dem Anfang, erster und letzter Satz, Satz nach dem Ende.
 * Mit ``words`` (Wortliste der Transkriptversion) entscheidet das Tor an den echten Wörtern und Zeiten,
 * nach ``rule`` (aus stats.sentence_rule der Transkriptversion, ohne Angabe v2). */
export interface BoundaryContext {
  before?: Sentence;
  first: Sentence;
  last: Sentence;
  after?: Sentence;
  words?: WordLike[];
  rule?: SentenceRule;
}

/* Spiegel von story_engine._endet_satz (Tor unter Fassung 1): nur Satzzeichen, Auslassungspunkte nicht. */
const V1_SENTENCE_END_CHARS = ".!?\"'»)";

function endsSentenceV1(text: string): boolean {
  const t = (text || "").trim();
  if (!t || t.endsWith("…") || t.endsWith("...")) return false;
  return V1_SENTENCE_END_CHARS.includes(t[t.length - 1]);
}

function sentenceBoundariesGateV1(ctx: BoundaryContext, words: WordLike[]): GateResult {
  const a = ctx.first.word_range[0];
  const b = ctx.last.word_range[1];
  const problems: string[] = [];
  const before = a > 0 ? (words[a - 1]?.text ?? "") : "";
  if (a > 0 && !endsSentenceV1(before)) problems.push(`faengt mitten im Satz an, davor steht „${before}“`);
  const lastWord = words[b]?.text ?? "";
  if (!endsSentenceV1(lastWord)) problems.push(`endet mitten im Satz auf „${lastWord}“`);
  if (problems.length > 0) return { passed: false, detail: problems.join("; ") };
  return { passed: true, detail: "Start und Ende an Satzgrenzen" };
}

function sentenceWords(s: Sentence): WordLike[] {
  /* Wortzeiten kennt die Satzliste nur an den Rändern; für die Pause zählen genau diese. */
  return s.text
    .split(/\s+/)
    .filter(Boolean)
    .map((text) => ({ text, start: s.start, end: s.end, speaker: s.speaker }));
}

/* Endet ``left`` dort, wo ``right`` beginnt, ein Satz? Gleiche Entscheidung wie der Worker (Regel v2). */
function boundaryKind(left: Sentence, right: Sentence | undefined) {
  const lw = sentenceWords(left);
  const words = right ? [...lw, ...sentenceWords(right)] : lw;
  return { kind: cutBoundaryKind(words, lw.length - 1, "v2"), word: lw[lw.length - 1]?.text ?? "" };
}

const PAUSE_KINDS: SentenceEndKind[] = ["pause_candidate", "length_cap"];

/* Satzgrenzen-Tor: Satzzeichen oder Sprecherwechsel gelten, ein angenommener Pause-Kandidat mit Hinweis.
 * Mit Wortliste und Regel v1 wie das Tor des Workers unter Fassung 1 (nur Satzzeichen). */
export function sentenceBoundariesGate(ctx: BoundaryContext): GateResult {
  const problems: string[] = [];
  const pauseOnly: string[] = [];
  let start: { kind: SentenceEndKind; word: string } | null = null;
  let end: { kind: SentenceEndKind; word: string };
  if (ctx.words && ctx.words.length > 0) {
    const words = ctx.words;
    const rule = ctx.rule ?? "v2";
    if (rule === "v1") return sentenceBoundariesGateV1(ctx, words);
    const resolved = resolveSentenceRule(words, rule);
    const a = ctx.first.word_range[0];
    const b = ctx.last.word_range[1];
    if (a > 0) start = { kind: cutBoundaryKind(words, a - 1, resolved), word: words[a - 1]?.text ?? "" };
    end = { kind: cutBoundaryKind(words, b, resolved), word: words[b]?.text ?? "" };
  } else {
    if (ctx.before) start = boundaryKind(ctx.before, ctx.first);
    end = boundaryKind(ctx.last, ctx.after);
  }
  if (start) {
    if (start.kind === "none") problems.push(`fängt mitten im Satz an, davor steht „${start.word}“`);
    else if (PAUSE_KINDS.includes(start.kind)) pauseOnly.push("Anfang");
  }
  if (end.kind === "none") problems.push(`endet mitten im Satz auf „${end.word}“`);
  else if (PAUSE_KINDS.includes(end.kind)) pauseOnly.push("Ende");
  if (problems.length > 0) return { passed: false, detail: problems.join("; ") };
  if (pauseOnly.length > 0) {
    return { passed: true, detail: `Start und Ende an Satzgrenzen, Grenze nur aus Pause (${pauseOnly.join(" und ")})` };
  }
  return { passed: true, detail: "Start und Ende an Satzgrenzen" };
}

export function recomputeGates(
  previous: CandidateGates,
  lastSentenceText: string,
  boundaries?: BoundaryContext,
): CandidateGates {
  const loop = endsWithOpenLoop(lastSentenceText);
  const carry = (key: GateKey): GateResult =>
    previous[key] ?? { passed: true, detail: "nicht geprüft" };
  return {
    standalone: carry("standalone"),
    fidelity: carry("fidelity"),
    /* Ohne Nachbarsätze lässt sich die Grenze nicht prüfen; dann bleibt das vorige Ergebnis stehen. */
    sentence_boundaries: boundaries ? sentenceBoundariesGate(boundaries) : carry("sentence_boundaries"),
    verb_bracket: carry("verb_bracket"),
    no_open_loop: loop
      ? { passed: false, detail: `endet auf „${loop}“` }
      : { passed: true, detail: "endet mit abgeschlossenem Satz" },
  };
}

export function allGatesPassed(gates: CandidateGates): boolean {
  return GATE_ORDER.every((k) => gates[k]?.passed !== false);
}

export function countGates(gates: CandidateGates): { passed: number; total: number } {
  const total = GATE_ORDER.length;
  const passed = GATE_ORDER.filter((k) => gates[k]?.passed !== false).length;
  return { passed, total };
}
