import type { CandidateGates, GateKey, GateResult } from "@/lib/repo/types";

/* Deterministische Pflichtkriterien nach Verlängern/Kürzen (Spiegel von dach_nlp.ends_with_open_loop).
 * standalone, fidelity und verb_bracket werden unverändert übernommen; sie stammen aus Stufe 3 des Workers. */

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

export function recomputeGates(previous: CandidateGates, lastSentenceText: string): CandidateGates {
  const loop = endsWithOpenLoop(lastSentenceText);
  const carry = (key: GateKey): GateResult =>
    previous[key] ?? { passed: true, detail: "nicht geprüft" };
  return {
    standalone: carry("standalone"),
    fidelity: carry("fidelity"),
    sentence_boundaries: { passed: true, detail: "Start und Ende an Satzgrenzen" },
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
