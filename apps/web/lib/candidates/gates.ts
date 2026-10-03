import type { CandidateGates, GateKey, GateResult } from "@/lib/repo/types";
import { cutBoundaryKind, type Sentence, type WordLike } from "@/lib/transcript/sentences";

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

/* Nachbarsätze der neuen Grenzen: Satz vor dem Anfang, erster und letzter Satz, Satz nach dem Ende. */
export interface BoundaryContext {
  before?: Sentence;
  first: Sentence;
  last: Sentence;
  after?: Sentence;
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

/* Satzgrenzen-Tor: Satzzeichen oder Sprecherwechsel gelten, ein angenommener Pause-Kandidat mit Hinweis. */
export function sentenceBoundariesGate(ctx: BoundaryContext): GateResult {
  const problems: string[] = [];
  const pauseOnly: string[] = [];
  if (ctx.before) {
    const { kind, word } = boundaryKind(ctx.before, ctx.first);
    if (kind === "none") problems.push(`fängt mitten im Satz an, davor steht „${word}“`);
    else if (kind === "pause_candidate") pauseOnly.push("Anfang");
  }
  const end = boundaryKind(ctx.last, ctx.after);
  if (end.kind === "none") problems.push(`endet mitten im Satz auf „${end.word}“`);
  else if (end.kind === "pause_candidate") pauseOnly.push("Ende");
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
