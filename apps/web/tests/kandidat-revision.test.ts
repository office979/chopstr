/* Die Revision eines Kandidaten prüft die Satzgrenzen wirklich (AP2).
 *
 * Vorher stand sentence_boundaries nach jeder Grenzänderung fest auf bestanden. Wer im Review den
 * Anfang auf einen Satz legte, der mitten im Gedanken beginnt, bekam trotzdem „Satzgrenzen: ok“.
 */

import { describe, expect, it } from "vitest";
import { buildRevision, CUT_SPECIFIC_RUBRIC_KEYS, isRevisionError } from "@/lib/candidates/revise";
import { allGatesPassed, countGates, recomputeGates, sentenceBoundariesGate } from "@/lib/candidates/gates";
import type { Candidate, CandidateGates } from "@/lib/repo/types";
import type { Sentence, WordLike } from "@/lib/transcript/sentences";

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

describe("Satzgrenzen-Tor an den echten Wörtern (N8)", () => {
  function woerter(text: string, pauseNach: Record<number, number> = {}): WordLike[] {
    let t = 0;
    return text.split(" ").map((w, k) => {
      const wort = { text: w, start: t, end: t + 0.3, speaker: "SPEAKER_00" };
      t += 0.32 + (pauseNach[k] ?? 0);
      return wort;
    });
  }
  const w = woerter("Das ist gut. Das bringt bei uns nicht viel. Wir machen weiter.", { 6: 0.9 });
  const s = (idx: number, a: number, b: number): Sentence => ({
    idx, text: w.slice(a, b + 1).map((x) => x.text).join(" "), start: w[a].start, end: w[b].end, speaker: "SPEAKER_00", word_range: [a, b],
  });

  it("v2: Pause vor kleingeschriebenem Wort ist kein Satzende", () => {
    const g = sentenceBoundariesGate({ first: s(0, 0, 0), last: s(1, 3, 6), words: w, rule: "v2" });
    expect(g.passed).toBe(false);
    expect(g.detail).toContain("endet mitten im Satz auf „uns“");
  });

  it("v1: wie das Tor des Workers unter Fassung 1 (nur Satzzeichen)", () => {
    const g = sentenceBoundariesGate({ first: s(1, 4, 4), last: s(2, 5, 6), words: w, rule: "v1" });
    expect(g.passed).toBe(false);
    expect(g.detail).toBe("faengt mitten im Satz an, davor steht „Das“; endet mitten im Satz auf „uns“");
    expect(sentenceBoundariesGate({ first: s(0, 0, 2), last: s(1, 3, 8), words: w, rule: "v1" }).passed).toBe(true);
  });

  it("buildRevision nutzt Wörter und Regel der Transkriptversion", () => {
    const saetze = [s(0, 0, 2), s(1, 3, 6), s(2, 7, 8), s(3, 9, 11)];
    const prev = { ...kandidat(3, 4), first_sent: 2, last_sent: 3 };
    const rev = buildRevision(prev, saetze, { first_sent: 1, last_sent: 1 }, { words: w, rule: "v2" });
    if (isRevisionError(rev)) throw new Error(rev.error);
    expect(rev.gates.sentence_boundaries.passed).toBe(false);
  });
});

/* AP4: Der Worker schreibt zusätzliche Gate-Ergebnisse (rubric.quality_gate_results, später weitere
 * Schlüssel). Unbekannte Schlüssel in gates und rubric dürfen die fünf Pflichtkriterien nicht verändern. */
describe("unbekannte zusätzliche Schlüssel (AP4)", () => {
  const extra = {
    ...BESTANDEN,
    unresolved_pronoun: { passed: false, detail: "Pronomen „Sie“ ohne Bezug im Clip", healable: "front", origin: "R" },
    embedded_instruction: { passed: true, detail: "Anweisung an ein Modell", flagged: true, quotes: ["Liebe KI"] },
  } as unknown as CandidateGates;

  it("allGatesPassed und countGates zählen nur die fünf Pflichtkriterien", () => {
    expect(allGatesPassed(extra)).toBe(true);
    expect(countGates(extra)).toEqual({ passed: 5, total: 5 });
    const failing = { ...extra, fidelity: { passed: false, detail: "endet direkt vor „aber“" } } as CandidateGates;
    expect(allGatesPassed(failing)).toBe(false);
    expect(countGates(failing)).toEqual({ passed: 4, total: 5 });
  });

  it("fehlende Pflichtschlüssel gelten weiter als nicht durchgefallen", () => {
    const partial = { unresolved_pronoun: { passed: false, detail: "x" } } as unknown as CandidateGates;
    expect(allGatesPassed(partial)).toBe(true);
    expect(countGates(partial)).toEqual({ passed: 5, total: 5 });
  });

  it("buildRevision übernimmt die Pflichtkriterien trotz zusätzlicher Schlüssel in gates und rubric", () => {
    const base = kandidat(3, 4);
    const prev = {
      ...base,
      gates: extra,
      rubric: {
        ...base.rubric,
        quality_gate_results: { unresolved_pronoun: { passed: false, detail: "x", origin: "R" } },
        block_mode: { mode: "sperren", effective_mode: "sortieren" },
      },
    } as unknown as Candidate;
    const rev = buildRevision(prev, SAETZE, { first_sent: 3, last_sent: 3 });
    if (isRevisionError(rev)) throw new Error(rev.error);
    expect(rev.gate_passed).toBe(true);
    expect(countGates(rev.gates)).toEqual({ passed: 5, total: 5 });
  });
});

describe("Revision und Kürzung (AP7, AP8)", () => {
  const SEGMENTE = [
    { start: 9.2, end: 11.0, role: "body" as const },
    { start: 11.3, end: 15, role: "body" as const },
  ];
  function gekuerzt(): Candidate {
    const base = kandidat(3, 4);
    return {
      ...base,
      segments: SEGMENTE,
      rubric: {
        ...base.rubric,
        duration_s: 5.8,
        composition: { local_cuts: 1, semantic_splices: 0, segments: SEGMENTE },
        removed_spans: [{ source_in: 11.0, source_out: 11.3, removal_reason: "technical_pause", protected_context_check: null }],
        trim: { applied: true, reason: null },
        versions: { contract: "clip_candidate_v1" },
        decision: "accept",
        decision_reason: "x",
        quality_gate_results: { unresolved_pronoun: { passed: true, detail: "x" } },
        quality_gate_decision: { decision: "accepted" },
        gate_heal: null,
        assessment_uncertainties: [],
        calibration: "uncalibrated",
        anchor_subscores: { values: {} },
        critic: { status: "checked" },
        critic_findings: [],
        opening_choice: { chosen: 3 },
        alternatives_considered: [],
        promoted: { from: "reserve" },
        sentence_rule: "v2",
      },
    } as unknown as Candidate;
  }

  it("neue Grenzen: ein Segment, Kürzung und ClipCandidate-Teilmenge fallen aus der Rubrik", () => {
    const rev = buildRevision(gekuerzt(), SAETZE, { first_sent: 2, last_sent: 4 });
    if (isRevisionError(rev)) throw new Error(rev.error);
    expect(rev.segments).toEqual([{ start: SAETZE[2].start, end: SAETZE[4].end, role: "body" }]);
    const rubric = rev.rubric as unknown as Record<string, unknown>;
    for (const key of CUT_SPECIFIC_RUBRIC_KEYS) {
      expect(rubric).not.toHaveProperty(key);
    }
    expect(CUT_SPECIFIC_RUBRIC_KEYS).not.toContain("editorial_subscores");
    expect(rubric.sentence_rule).toBe("v2");
    expect(rev.rubric.scores_stale).toBe(true);
  });

  it("nur neue Titelkarte: Segmente der Kürzung und Rubrik bleiben", () => {
    const prev = gekuerzt();
    const rev = buildRevision(prev, SAETZE, { first_sent: 3, last_sent: 4, title_card: "Zwei Jahre Rabatte" });
    if (isRevisionError(rev)) throw new Error(rev.error);
    expect(rev.segments).toEqual(SEGMENTE);
    expect(rev.start_s).toBe(prev.start_s);
    const rubric = rev.rubric as unknown as Record<string, unknown>;
    expect(rubric.composition).toEqual({ local_cuts: 1, semantic_splices: 0, segments: SEGMENTE });
    expect(rubric.removed_spans).toHaveLength(1);
    for (const key of CUT_SPECIFIC_RUBRIC_KEYS) {
      expect(rubric).toHaveProperty(key);
    }
    expect(rev.rubric.duration_s).toBe(5.8);
    expect(rev.rubric.suggested_title_card).toBe("Zwei Jahre Rabatte");
  });
});
