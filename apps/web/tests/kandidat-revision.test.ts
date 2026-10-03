/* Die Revision eines Kandidaten prüft die Satzgrenzen wirklich (AP2).
 *
 * Vorher stand sentence_boundaries nach jeder Grenzänderung fest auf bestanden. Wer im Review den
 * Anfang auf einen Satz legte, der mitten im Gedanken beginnt, bekam trotzdem „Satzgrenzen: ok“.
 */

import { describe, expect, it } from "vitest";
import { buildRevision, isRevisionError } from "@/lib/candidates/revise";
import { recomputeGates, sentenceBoundariesGate } from "@/lib/candidates/gates";
import type { Candidate, CandidateGates } from "@/lib/repo/types";
import type { Sentence } from "@/lib/transcript/sentences";

function satz(idx: number, text: string, start: number, end: number, speaker = "SPEAKER_00"): Sentence {
  return { idx, text, start, end, speaker, word_range: [idx * 10, idx * 10 + 9] };
}

/* Satz 1 endet ohne Satzzeichen auf „uns“, kurz danach (keine lange Pause) geht es klein weiter. */
const SAETZE: Sentence[] = [
  satz(0, "Viele Händler machen zum Jahresende große Rabattaktionen.", 0, 4),
  satz(1, "Ehrlich gesagt, Rabatte zum Jahresende, das bringt bei uns", 4.2, 8),
  satz(2, "nicht viel.", 8.1, 9),
  satz(3, "Wir haben das zwei Jahre lang gemacht.", 9.2, 12),
  satz(4, "Am Ende hatten wir mehr Retouren.", 12.2, 15),
];

const BESTANDEN: CandidateGates = {
  standalone: { passed: true, detail: "keine offenen Verweise" },
  fidelity: { passed: true, detail: "keine entfernte Verneinung oder Einschränkung" },
  sentence_boundaries: { passed: true, detail: "Start und Ende an Satzgrenzen" },
  verb_bracket: { passed: true, detail: "kein Schnitt in einer Verbklammer", available: true },
  no_open_loop: { passed: true, detail: "endet mit abgeschlossenem Satz" },
};

function kandidat(first: number, last: number): Candidate {
  return {
    id: "c1",
    source_id: "s1",
    version: 1,
    segments: [{ start: SAETZE[first].start, end: SAETZE[last].end, role: "body" }],
    start_s: SAETZE[first].start,
    end_s: SAETZE[last].end,
    first_sent: first,
    last_sent: last,
    structure: "hook_build_payoff",
    rubric: {
      contract: "candidates_v1",
      text: "",
      speakers: ["SPEAKER_00"],
      duration_s: 0,
      scores: {} as Candidate["rubric"]["scores"],
      unresolved_references: [],
      needs_earlier_context: false,
      ends_before_answer: false,
      is_humor: false,
      sensitive_topic: false,
      suggested_title_card: "",
      repair: { rounds: 0, expanded_front: 0, expanded_back: 0, failed: false },
      proposal_why: "",
      parent_id: null,
    },
    gates: BESTANDEN,
    story_graph_flags: [],
    risk_flags: [],
    total: 10,
    gate_passed: true,
    why: null,
    model_id: null,
    prompt_version: null,
    human_verdict: null,
    verdict_reason: null,
    verdict_by: null,
    verdict_at: null,
    created_at: "2026-10-03T00:00:00Z",
  };
}

describe("recomputeGates prüft sentence_boundaries", () => {
  it("meldet ein Ende mitten im Satz", () => {
    const g = recomputeGates(BESTANDEN, SAETZE[1].text, { before: SAETZE[0], first: SAETZE[1], last: SAETZE[1], after: SAETZE[2] });
    expect(g.sentence_boundaries.passed).toBe(false);
    expect(g.sentence_boundaries.detail).toContain("endet mitten im Satz auf „uns“");
  });

  it("meldet einen Anfang mitten im Satz", () => {
    const g = sentenceBoundariesGate({ before: SAETZE[1], first: SAETZE[2], last: SAETZE[3], after: SAETZE[4] });
    expect(g.passed).toBe(false);
    expect(g.detail).toContain("fängt mitten im Satz an, davor steht „uns“");
  });

  it("lässt saubere Grenzen durch, auch am Rand des Transkripts", () => {
    expect(sentenceBoundariesGate({ first: SAETZE[3], last: SAETZE[4] }).passed).toBe(true);
    expect(sentenceBoundariesGate({ before: SAETZE[2], first: SAETZE[3], last: SAETZE[3], after: SAETZE[4] }).passed).toBe(true);
  });

  it("nimmt einen Einwurf des Gegenübers nach Komma nicht als Satzende", () => {
    const sprecher = satz(0, "Ich bin da ganz ehrlich,", 0, 2);
    const einwurf = satz(1, "Okay.", 2.1, 2.5, "SPEAKER_01");
    const g = sentenceBoundariesGate({ first: sprecher, last: sprecher, after: einwurf });
    expect(g.passed).toBe(false);
    expect(g.detail).toContain("endet mitten im Satz auf „ehrlich,“");
  });

  it("nimmt einen Sprecherwechsel als Grenze", () => {
    const frage = satz(0, "Lohnt sich das für euch", 0, 2, "SPEAKER_01");
    const antwort = satz(1, "Ehrlich gesagt nicht.", 2.1, 4);
    expect(sentenceBoundariesGate({ before: frage, first: antwort, last: antwort }).passed).toBe(true);
  });
});

describe("buildRevision", () => {
  it("setzt gate_passed auf false, wenn die neue Grenze mitten im Satz liegt", () => {
    const rev = buildRevision(kandidat(3, 4), SAETZE, { first_sent: 2, last_sent: 4 });
    if (isRevisionError(rev)) throw new Error(rev.error);
    expect(rev.gates.sentence_boundaries.passed).toBe(false);
    expect(rev.gate_passed).toBe(false);
  });

  it("bleibt bestanden bei sauberen Grenzen", () => {
    const rev = buildRevision(kandidat(3, 4), SAETZE, { first_sent: 0, last_sent: 0 });
    if (isRevisionError(rev)) throw new Error(rev.error);
    expect(rev.gates.sentence_boundaries.passed).toBe(true);
  });
});
