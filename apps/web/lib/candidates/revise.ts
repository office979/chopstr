import type { Candidate, ReviseCandidateInput, StoryGraphFlag } from "@/lib/repo/types";
import { clipText, sentenceRange, type Sentence } from "@/lib/transcript/sentences";
import { allGatesPassed, recomputeGates } from "@/lib/candidates/gates";

export const TITLE_CARD_MAX_WORDS = 8;

export function titleCardWords(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean);
}

export interface RevisionError {
  error: string;
}

export type Revision = Omit<Candidate, "id" | "created_at">;

/* Neue Kandidaten-Version aus geänderten Grenzen oder Titelkarte (gemeinsam für Demo und Postgres).
 * Scores bleiben, rubric.scores_stale = true, Gates deterministisch neu; Story-Graph-Flags, die jetzt
 * im Clip liegen, gelten als repariert. */
export function buildRevision(
  prev: Candidate,
  sentences: Sentence[],
  input: ReviseCandidateInput,
): Revision | RevisionError {
  const { first_sent, last_sent } = input;
  if (!Number.isInteger(first_sent) || !Number.isInteger(last_sent)) return { error: "Satzindizes fehlen" };
  if (first_sent > last_sent) return { error: "first_sent darf nicht nach last_sent liegen" };
  const range = sentenceRange(sentences, first_sent, last_sent);
  if (range.length === 0 || range[0].idx !== first_sent || range[range.length - 1].idx !== last_sent) {
    return { error: "Satzindizes existieren im aktuellen Transkript nicht" };
  }

  let titleCard = prev.rubric.suggested_title_card ?? "";
  if (input.title_card !== undefined) {
    const words = titleCardWords(input.title_card);
    if (words.length > TITLE_CARD_MAX_WORDS) return { error: `Titelkarte: höchstens ${TITLE_CARD_MAX_WORDS} Wörter` };
    titleCard = words.join(" ");
  }

  const boundariesChanged = prev.first_sent !== first_sent || prev.last_sent !== last_sent;
  if (!boundariesChanged && titleCard === (prev.rubric.suggested_title_card ?? "")) {
    return { error: "Keine Änderung" };
  }

  const start = range[0].start;
  const end = range[range.length - 1].end;
  const gates = boundariesChanged ? recomputeGates(prev.gates, range[range.length - 1].text) : prev.gates;
  const flags: StoryGraphFlag[] = prev.story_graph_flags
    .filter((f) => f.sentence_idx > last_sent)
    .map((f) => {
      const sent = sentences.find((s) => s.idx === f.sentence_idx);
      return sent ? { ...f, seconds_after: Number((sent.start - end).toFixed(1)) } : f;
    });

  return {
    source_id: prev.source_id,
    version: prev.version + 1,
    segments: [{ start, end, role: "body" }],
    start_s: start,
    end_s: end,
    first_sent,
    last_sent,
    structure: prev.structure,
    rubric: {
      ...prev.rubric,
      text: clipText(range),
      speakers: [...new Set(range.map((s) => s.speaker))],
      duration_s: Number((end - start).toFixed(1)),
      suggested_title_card: titleCard,
      parent_id: prev.id,
      scores_stale: boundariesChanged ? true : (prev.rubric.scores_stale ?? false),
    },
    gates,
    story_graph_flags: flags,
    risk_flags: prev.risk_flags,
    total: prev.total,
    gate_passed: allGatesPassed(gates),
    why: prev.why,
    model_id: prev.model_id,
    prompt_version: prev.prompt_version,
    human_verdict: null,
    verdict_reason: null,
    verdict_by: null,
    verdict_at: null,
  };
}

export function isRevisionError(r: Revision | RevisionError): r is RevisionError {
  return "error" in r;
}
