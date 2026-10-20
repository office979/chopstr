import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";
import type { Candidate, Clip, Platform, Source } from "@/lib/repo/types";

/* Kandidatenliste als Freigabe (docs/decisions/051-kandidatenliste-freigabe.md, 052): Ergebnisklasse
 * mit Rückfall, eine Qualitätszahl, Belegstellen, Sortierung, Urteil an der Karte, und die
 * Verdict-Route mit „Flag an Redaktion“ und der Pflichtbegründung bei nicht freigabefähigen
 * Kandidaten. */

const h = vi.hoisted(() => ({
  repo: null as unknown,
  signals: [] as unknown[],
  decisions: [] as Record<string, unknown>[],
}));

vi.mock("@/lib/repo", () => ({ getRepo: () => h.repo }));
vi.mock("@/lib/auth/guard", () => ({ requireApiRole: async () => ({ userId: "user-1", role: "editor" }) }));
vi.mock("@/lib/temporal", () => ({
  signalApprove: async (args: unknown) => {
    h.signals.push(args);
    return false;
  },
}));
vi.mock("@/lib/decision-log", () => ({
  recordDecision: async (input: Record<string, unknown>) => {
    h.decisions.push(input);
    return null;
  },
  candidateFeatures: () => ({}),
}));

import { POST as verdictPost } from "@/app/api/projects/[id]/candidates/[cid]/verdict/route";
import {
  EDITORIAL_FLAG_PREFIX,
  OVERRIDE_REASON_PREFIX,
  clipOffset,
  compareForReview,
  editorialFlagReason,
  evidenceSpans,
  holdText,
  qualityScore,
  readSpan,
  reviewState,
  riskWords,
  spanText,
  titleCardRepair,
  verdictView,
} from "@/lib/candidates/review";
import { AUTO_HOLD_REASON_PREFIX } from "@/lib/clips/acceptance";
import { verdictReason } from "@/lib/publishing/gates";

const SOURCE_ID = "src-1";

function cand(id: string, patch: Partial<Candidate> = {}, rubric: Record<string, unknown> = {}): Candidate {
  return {
    id,
    source_id: SOURCE_ID,
    version: 1,
    segments: [{ start: 60, end: 100, role: "body" }],
    start_s: 60,
    end_s: 100,
    total: 8.4,
    gate_passed: true,
    gates: {
      standalone: { passed: true, detail: "keine offenen Verweise" },
      fidelity: { passed: true, detail: "ok" },
      sentence_boundaries: { passed: true, detail: "ok" },
      verb_bracket: { passed: true, detail: "ok" },
      no_open_loop: { passed: true, detail: "ok" },
    },
    story_graph_flags: [],
    risk_flags: [],
    why: "Kernaussage in 40 Sekunden vollständig.",
    human_verdict: "accepted",
    verdict_reason: "automatisch angenommen (ohne Auswahlschritt)",
    verdict_by: null,
    verdict_at: null,
    rubric: { text: "Satz.", ...rubric },
    ...patch,
  } as Candidate;
}

const HELD = `${AUTO_HOLD_REASON_PREFIX}humor, claim, menschliche Prüfung nötig`;

describe("reviewState", () => {
  it("liest rubric.review_state, wenn der Worker es schreibt", () => {
    const c = cand("a", {}, {
      review_state: {
        state: "uncertain",
        reasons: [
          { code: "speaker_uncertain", text: "Sprecher bei der Antwort unsicher", source_span: { start_s: 70, end_s: 72.5 }, origin: "model" },
          { code: "leer", text: "  " },
        ],
        repair: { attempted: true, kind: "title_card", result: "passed" },
      },
    });
    const r = reviewState(c);
    expect(r.state).toBe("uncertain");
    expect(r.derived).toBe(false);
    expect(r.reasons).toEqual([
      { code: "speaker_uncertain", text: "Sprecher bei der Antwort unsicher", source_span: { start_s: 70, end_s: 72.5 }, origin: "model" },
    ]);
    expect(r.repair).toEqual({ attempted: true, kind: "title_card", result: "passed" });
  });

  it("fällt ohne review_state auf bestanden zurück, wenn nichts dagegen spricht", () => {
    const r = reviewState(cand("a", { risk_flags: ["claim", "heuristic_only"] }));
    expect(r).toMatchObject({ state: "passed", reasons: [], derived: true });
  });

  it("ein unlesbares review_state zählt wie ein fehlendes", () => {
    expect(reviewState(cand("a", {}, { review_state: { state: "gut" } })).derived).toBe(true);
  });

  it("Haltegrund der Automatik macht unsicher, mit Klartext und Quellstelle", () => {
    const r = reviewState(cand("a", { human_verdict: null, verdict_reason: HELD, risk_flags: ["humor", "claim"] }));
    expect(r.state).toBe("uncertain");
    expect(r.reasons).toHaveLength(1);
    expect(r.reasons[0]).toMatchObject({
      code: "auto_hold",
      text: "Automatische Freigabe ausgesetzt: Humor, Behauptung, die geprüft werden muss. Ein Mensch entscheidet.",
      source_span: { start_s: 60, end_s: 100 },
    });
  });

  it("Humor und heikles Thema machen unsicher, auch nach der Annahme (Regel 11)", () => {
    const r = reviewState(cand("a", { risk_flags: ["sensitive_topic"] }));
    expect(r.state).toBe("uncertain");
    expect(r.reasons.map((x) => x.code)).toEqual(["sensitive_topic"]);
  });

  it("eine spätere Relativierung steht mit ihrer Stelle im Video da", () => {
    const r = reviewState(
      cand("a", {
        story_graph_flags: [
          { sentence_idx: 9, seconds_after: 21.5, marker: "aber", text: "Das gilt nicht überall.", overlap: 0.3, confirmed: null, reason: "", repair: "extend", suggestion: "" },
        ],
      }),
    );
    expect(r.state).toBe("uncertain");
    expect(r.reasons[0]).toMatchObject({ code: "later_qualification", source_span: { start_s: 121.5, end_s: 121.5 }, origin: "rule" });
    expect(r.reasons[0].text).toBe("Mögliche spätere Relativierung 0:21 nach dem Ende: „Das gilt nicht überall.“");
  });

  it("ein gerissenes Tor macht nicht freigabefähig, mit dem Grund des Tors", () => {
    const c = cand("a", { gate_passed: false });
    c.gates.no_open_loop = { passed: false, detail: "endet auf „aber“" };
    const r = reviewState(c);
    expect(r.state).toBe("blocked");
    expect(r.reasons).toEqual([{ code: "gate_no_open_loop", text: "endet auf „aber“", source_span: { start_s: 60, end_s: 100 }, origin: "rule" }]);
  });
});

describe("qualityScore", () => {
  it("zeigt total auf der Skala bis 14, ohne Klanganteil", () => {
    expect(qualityScore(cand("a", { total: 8.44 }))).toEqual({ value: 8.44, max: 14, text: "Qualität 8,4 von 14" });
  });

  it("mit Klanganteil reicht die Skala bis 16,1", () => {
    expect(qualityScore(cand("a", { total: 15.2 }, { klang: 0.8 }))?.text).toBe("Qualität 15,2 von 16,1");
  });

  it("ein ausdrückliches rubric.policy_total_max gewinnt", () => {
    expect(qualityScore(cand("a", { total: 5 }, { klang: 0.8, policy_total_max: 14 }))?.max).toBe(14);
  });

  it("ohne total keine Zahl", () => {
    expect(qualityScore(cand("a", { total: null }))).toBeNull();
  });
});

describe("Belegstellen", () => {
  it("Einstieg und Pointe aus dem ClipCandidate, in beiden Spannenformen", () => {
    const c = cand("a", {}, {
      opening_source_span: { source_in: 60.2, source_out: 64, word_range: [1, 9] },
      payoff_source_span: { start_s: 92, end_s: 99.5 },
    });
    expect(evidenceSpans(c)).toEqual([
      { kind: "opening", label: "Einstieg", span: { start_s: 60.2, end_s: 64 } },
      { kind: "payoff", label: "Pointe", span: { start_s: 92, end_s: 99.5 } },
    ]);
  });

  it("ohne Spannen der ganze Clip aus start_s und end_s", () => {
    expect(evidenceSpans(cand("a"))).toEqual([{ kind: "clip", label: "Clip", span: { start_s: 60, end_s: 100 } }]);
  });

  it("verwirft unsinnige Spannen", () => {
    expect(readSpan({ start_s: 5, end_s: 2 })).toBeNull();
    expect(readSpan({ start_s: "1", end_s: 2 })).toBeNull();
    expect(readSpan(null)).toBeNull();
  });

  it("schreibt Bereiche und Punkte", () => {
    expect(spanText({ start_s: 62, end_s: 75.4 })).toBe("1:02 bis 1:15");
    expect(spanText({ start_s: 121.5, end_s: 121.5 })).toBe("bei 2:01");
  });

  it("rechnet eine Quellstelle in die Zeit des fertigen Clips um, auch mit Teaser vorn", () => {
    const segs = [
      { start: 90, end: 94 },
      { start: 60, end: 100 },
    ];
    expect(clipOffset(segs, 92)).toBe(2);
    expect(clipOffset([{ start: 60, end: 100 }], 75)).toBe(15);
    expect(clipOffset(segs, 10)).toBe(0);
  });
});

describe("Urteil, Flags, Reparatur", () => {
  it("zeigt den Haltegrund wie P27 verlangt", () => {
    expect(verdictView({ human_verdict: null, verdict_reason: HELD, verdict_by: null })).toEqual({
      status: "held",
      label: "Zurückgehalten",
      reason: "Automatische Freigabe ausgesetzt: Humor, Behauptung, die geprüft werden muss. Ein Mensch entscheidet.",
    });
    expect(holdText("etwas anderes")).toBeNull();
  });

  it("unterscheidet automatische und menschliche Annahme, Flag und Ablehnung", () => {
    expect(verdictView({ human_verdict: "accepted", verdict_reason: "automatisch angenommen", verdict_by: null }).status).toBe("auto_accepted");
    expect(verdictView({ human_verdict: "accepted", verdict_reason: `${OVERRIDE_REASON_PREFIX}abgesprochen`, verdict_by: "u" })).toEqual({
      status: "accepted",
      label: "Angenommen",
      reason: "Trotz Befund: abgesprochen",
    });
    expect(verdictView({ human_verdict: null, verdict_reason: editorialFlagReason("Zahl prüfen", 12), verdict_by: "u" })).toEqual({
      status: "flagged",
      label: "An Redaktion",
      reason: "Zahl prüfen (bei 0:12 im Clip)",
    });
    expect(verdictView({ human_verdict: "rejected", verdict_reason: "zu allgemein", verdict_by: "u" })).toMatchObject({ status: "rejected", reason: "zu allgemein" });
  });

  it("Flags als Wörter mit dem Satz als Erklärung", () => {
    expect(riskWords({ risk_flags: ["humor", "heuristic_only"] })).toEqual([
      { key: "humor", word: "Humor", title: "Ist Witz, bitte selbst prüfen" },
      { key: "heuristic_only", word: "Ohne Sprachmodell", title: "Ohne KI gefunden" },
    ]);
  });

  it("erkennt eine Titelkarten-Reparatur nur mit kind title_card", () => {
    expect(titleCardRepair({ repair: { rounds: 1, expanded_front: 0, expanded_back: 0, failed: false } })).toBeNull();
    expect(titleCardRepair({ repair_applied: { kind: "title_card", text: "Gilt nur für Neukunden", source_span: { start_s: 101, end_s: 103 } } })).toEqual({
      text: "Gilt nur für Neukunden",
      source_span: { start_s: 101, end_s: 103 },
    });
  });
});

describe("Sortierung der Liste", () => {
  it("bestanden vor unsicher vor nicht freigabefähig, darin nach Qualität, Abgelehnte ans Ende", () => {
    const passedLow = cand("passed-low", { total: 6 });
    const passedHigh = cand("passed-high", { total: 11 });
    const uncertain = cand("uncertain", { total: 13, risk_flags: ["humor"] });
    const blocked = cand("blocked", { total: 14, gate_passed: false });
    const rejected = cand("rejected", { total: 12.5, human_verdict: "rejected", verdict_reason: "nein" });
    const noTotal = cand("no-total", { total: null });
    const sorted = [blocked, rejected, uncertain, noTotal, passedLow, passedHigh].sort(compareForReview);
    expect(sorted.map((c) => c.id)).toEqual(["passed-high", "passed-low", "no-total", "uncertain", "blocked", "rejected"]);
  });

  it("Clips ohne Kandidat stehen hinten", () => {
    expect(compareForReview(null, cand("a"))).toBe(1);
    expect(compareForReview(cand("a"), null)).toBe(-1);
  });
});

/* Ein Repository im Speicher, gerade genug für die Verdict-Route. */
class MemoryRepo {
  kind = "postgres" as const;
  candidates = new Map<string, Candidate>();
  clips: Clip[] = [];
  audits: { action: string; entity_id: string | null; payload?: Record<string, unknown> }[] = [];
  source = { id: SOURCE_ID, brand_profile_id: null, brief: {} } as unknown as Source;

  async getSource(id: string) {
    return id === SOURCE_ID ? this.source : null;
  }
  async getBrandProfile() {
    return null;
  }
  async getCandidate(id: string) {
    const c = this.candidates.get(id);
    return c ? { ...c } : null;
  }
  async setCandidateVerdict(id: string, verdict: "accepted" | "rejected" | null, reason?: string) {
    const c = this.candidates.get(id);
    if (!c) return null;
    Object.assign(c, { human_verdict: verdict, verdict_reason: reason?.trim() || null, verdict_by: "user-1", verdict_at: "jetzt" });
    return { ...c };
  }
  async listClips() {
    return this.clips;
  }
  async createClips(candidateId: string, platforms: Platform[]) {
    return platforms.map((platform) => {
      const clip = { id: `clip-${candidateId}-${platform}`, candidate_id: candidateId, platform, source_id: SOURCE_ID, status: "draft" } as Clip;
      this.clips.push(clip);
      return clip;
    });
  }
  async updateClip() {
    return null;
  }
  async audit(entry: { action: string; entity_id: string | null; payload?: Record<string, unknown> }) {
    this.audits.push(entry);
  }
}

let repo: MemoryRepo;

beforeEach(() => {
  repo = new MemoryRepo();
  h.repo = repo;
  h.signals.length = 0;
  h.decisions.length = 0;
});

function verdict(cid: string, body: Record<string, unknown>) {
  const request = new Request("http://localhost/api", { method: "POST", body: JSON.stringify(body) }) as unknown as NextRequest;
  return verdictPost(request, { params: Promise.resolve({ id: SOURCE_ID, cid }) });
}

describe("Verdict-Route: Flag an Redaktion (revise)", () => {
  it("speichert Kommentar und Sekunde als offenes Urteil mit Präfix, Audit und Decision Log mit revise", async () => {
    repo.candidates.set("c1", cand("c1"));
    const res = await verdict("c1", { verdict: "revise", reason: "Stimmt die Zahl?", at_s: "12.34" });
    expect(res.status).toBe(200);
    const stored = repo.candidates.get("c1")!;
    expect(stored.human_verdict).toBeNull();
    expect(stored.verdict_reason).toBe(`${EDITORIAL_FLAG_PREFIX}Stimmt die Zahl? (bei 0:12 im Clip)`);
    expect(stored.verdict_by).toBe("user-1");
    expect(repo.audits).toEqual([
      expect.objectContaining({
        action: "candidate.flagged",
        entity_id: "c1",
        payload: expect.objectContaining({ comment: "Stimmt die Zahl?", at_s: 12.3, previous_verdict: "accepted" }),
      }),
    ]);
    expect(h.decisions[0]).toMatchObject({ decision_type: "candidate_verdict", chosen: { verdict: "revise", at_s: 12.3, comment: "Stimmt die Zahl?" } });
    expect(repo.clips).toEqual([]);
    expect(h.signals).toEqual([]);
  });

  it("ein geflaggter Kandidat ist nicht veröffentlichbar", async () => {
    repo.candidates.set("c1", cand("c1"));
    await verdict("c1", { verdict: "revise", reason: "Bitte prüfen" });
    expect(verdictReason("c1", repo.candidates.get("c1")!)?.code).toBe("candidate_not_accepted");
  });

  it("ohne Kommentar 400, nichts gespeichert", async () => {
    repo.candidates.set("c1", cand("c1"));
    const res = await verdict("c1", { verdict: "revise", reason: "  " });
    expect(res.status).toBe(400);
    expect(repo.candidates.get("c1")!.human_verdict).toBe("accepted");
    expect(repo.audits).toEqual([]);
  });

  it("eine unsinnige Sekunde ist ein Fehler", async () => {
    repo.candidates.set("c1", cand("c1"));
    expect((await verdict("c1", { verdict: "revise", reason: "x", at_s: -1 })).status).toBe(400);
    expect((await verdict("c1", { verdict: "revise", reason: "x", at_s: "abc" })).status).toBe(400);
  });

  it("unbekanntes Urteil: 400", async () => {
    repo.candidates.set("c1", cand("c1"));
    expect((await verdict("c1", { verdict: "vielleicht" })).status).toBe(400);
  });
});

describe("Verdict-Route: nicht freigabefähig annehmen nur mit Begründung", () => {
  const blockedRubric = {
    review_state: {
      state: "blocked",
      reasons: [{ code: "speaker_wrong", text: "Antwort dem falschen Sprecher zugeordnet", source_span: { start_s: 70, end_s: 75 }, origin: "confirmed" }],
      repair: { attempted: true, kind: null, result: "failed" },
    },
  };

  it("ohne override_reason 400, kein Clip, kein Urteil", async () => {
    repo.candidates.set("c1", cand("c1", { human_verdict: null, verdict_reason: null }, blockedRubric));
    const res = await verdict("c1", { verdict: "accepted" });
    expect(res.status).toBe(400);
    expect(await res.json()).toMatchObject({ code: "override_reason_required" });
    expect(repo.candidates.get("c1")!.human_verdict).toBeNull();
    expect(repo.clips).toEqual([]);
  });

  it("mit Begründung: angenommen, Begründung im Urteil, im Audit und im Decision Log", async () => {
    repo.candidates.set("c1", cand("c1", { human_verdict: null, verdict_reason: null }, blockedRubric));
    const res = await verdict("c1", { verdict: "accepted", override_reason: "Mit dem Gast abgesprochen" });
    expect(res.status).toBe(200);
    const stored = repo.candidates.get("c1")!;
    expect(stored.human_verdict).toBe("accepted");
    expect(stored.verdict_reason).toBe(`${OVERRIDE_REASON_PREFIX}Mit dem Gast abgesprochen`);
    const audit = repo.audits.find((a) => a.action === "candidate.accepted");
    expect(audit?.payload).toMatchObject({ override_reason: "Mit dem Gast abgesprochen", review_state: "blocked", review_reasons: ["speaker_wrong"] });
    expect(h.decisions[0]).toMatchObject({ chosen: { verdict: "accepted", override_reason: "Mit dem Gast abgesprochen" } });
  });

  it("auch der Rückfall (gerissenes Tor) verlangt die Begründung", async () => {
    repo.candidates.set("c1", cand("c1", { gate_passed: false, human_verdict: null, verdict_reason: null }));
    expect((await verdict("c1", { verdict: "accepted" })).status).toBe(400);
  });

  it("ein unsicherer Kandidat lässt sich ohne Zusatz annehmen", async () => {
    repo.candidates.set("c1", cand("c1", { human_verdict: null, verdict_reason: HELD, risk_flags: ["humor"] }));
    const res = await verdict("c1", { verdict: "accepted" });
    expect(res.status).toBe(200);
    expect(repo.candidates.get("c1")!.human_verdict).toBe("accepted");
    expect(repo.candidates.get("c1")!.verdict_reason).toBeNull();
  });

  it("Ablehnen eines nicht freigabefähigen Kandidaten braucht nur den normalen Grund", async () => {
    repo.candidates.set("c1", cand("c1", { human_verdict: null, verdict_reason: null }, blockedRubric));
    const res = await verdict("c1", { verdict: "rejected", reason: "falscher Sprecher" });
    expect(res.status).toBe(200);
    expect(repo.candidates.get("c1")!.verdict_reason).toBe("falscher Sprecher");
  });
});
