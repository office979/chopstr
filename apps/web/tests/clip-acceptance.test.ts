import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";
import type { BrandProfile, Candidate, Clip, Platform, Source } from "@/lib/repo/types";

/* Annahmeweg für zurückgehaltene Clips (H1), Plattform bei der Annahme (M3), Urteil beim
 * Veröffentlichen (M5). Die Routen laufen gegen ein kleines Repository im Speicher; Temporal,
 * Anmeldung und Decision Log sind ersetzt. */

const h = vi.hoisted(() => ({
  repo: null as unknown,
  temporal: false,
  order: [] as string[],
  signals: [] as { sourceId: string; candidateId: string; destination: string }[],
  decisions: [] as Record<string, unknown>[],
}));

vi.mock("@/lib/repo", () => ({ getRepo: () => h.repo }));
vi.mock("@/lib/auth/guard", () => ({ requireApiRole: async () => ({ userId: "user-1", role: "editor" }) }));
vi.mock("@/lib/temporal", () => ({
  signalApprove: async (args: { sourceId: string; candidateId: string; destination: string }) => {
    h.order.push("signal");
    h.signals.push(args);
    return h.temporal;
  },
}));
vi.mock("@/lib/decision-log", () => ({
  recordDecision: async (input: Record<string, unknown>) => {
    h.decisions.push(input);
    return null;
  },
  candidateFeatures: () => ({}),
}));

import { POST as renderPost } from "@/app/api/projects/[id]/clips/[clipId]/render/route";
import { POST as verdictPost } from "@/app/api/projects/[id]/candidates/[cid]/verdict/route";
import {
  AUTO_HOLD_REASON_PREFIX,
  acceptancePlatform,
  defaultClipPlatform,
  isHeldCandidate,
  renderAcceptance,
} from "@/lib/clips/acceptance";
import { verdictReason } from "@/lib/publishing/gates";
import { ROLES, can } from "@/lib/auth/permissions";

const SOURCE_ID = "src-1";
const HELD_REASON = `${AUTO_HOLD_REASON_PREFIX}claim, menschliche Prüfung nötig`;

type Audit = { action: string; entity: string; entity_id: string; payload: Record<string, unknown> };

function makeCandidate(id: string, patch: Partial<Candidate> = {}): Candidate {
  return {
    id,
    source_id: SOURCE_ID,
    version: 1,
    total: 6,
    gate_passed: true,
    risk_flags: ["claim", "heuristic_only"],
    human_verdict: null,
    verdict_reason: HELD_REASON,
    verdict_by: null,
    verdict_at: null,
    ...patch,
  } as Candidate;
}

function makeClip(id: string, candidateId: string, platform: Platform, patch: Partial<Clip> = {}): Clip {
  return {
    id,
    source_id: SOURCE_ID,
    candidate_id: candidateId,
    platform,
    destination: platform,
    aspect: "9:16",
    status: "draft",
    render_error: null,
    created_at: "2026-10-03T10:00:00Z",
    created_by: null,
    ...patch,
  } as Clip;
}

class MemoryRepo {
  kind = "postgres" as const;
  candidates = new Map<string, Candidate>();
  clips = new Map<string, Clip>();
  audits: Audit[] = [];
  source: Source = { id: SOURCE_ID, brand_profile_id: "brand-1", brief: { platform: "linkedin" } } as Source;
  brand: BrandProfile | null = { id: "brand-1", default_platform: "shorts" } as BrandProfile;
  private seq = 0;

  async getSource(id: string) {
    return id === SOURCE_ID ? { ...this.source } : null;
  }
  async getBrandProfile() {
    return this.brand ? { ...this.brand } : null;
  }
  async getCandidate(id: string) {
    await Promise.resolve(); /* wie eine Datenbankrunde: gleichzeitige Anfragen lesen beide vor dem Schreiben */
    const c = this.candidates.get(id);
    return c ? { ...c } : null;
  }
  async setCandidateVerdict(id: string, verdict: "accepted" | "rejected", reason?: string) {
    h.order.push("verdict");
    const c = this.candidates.get(id);
    if (!c) return null;
    Object.assign(c, { human_verdict: verdict, verdict_reason: reason?.trim() || null, verdict_by: "user-1", verdict_at: "jetzt" });
    return { ...c };
  }
  /* Wie postgres: update ... where id = $1 and human_verdict is null returning * */
  async setCandidateVerdictIfOpen(id: string, verdict: "accepted" | "rejected", reason?: string) {
    const c = this.candidates.get(id);
    if (!c || c.human_verdict != null) return null;
    return this.setCandidateVerdict(id, verdict, reason);
  }
  async updateClip(id: string, patch: Partial<Clip>) {
    const c = this.clips.get(id);
    if (!c) return null;
    Object.assign(c, patch);
    return { ...c };
  }
  async getClip(id: string) {
    const c = this.clips.get(id);
    return c && c.status !== "deleted" ? { ...c } : null;
  }
  async listClips(sourceId: string) {
    return [...this.clips.values()].filter((c) => c.source_id === sourceId && c.status !== "deleted").map((c) => ({ ...c }));
  }
  /* Wie postgres.createClips: eine Zeile je (Kandidat, Plattform) wird wiederverwendet. */
  async createClips(candidateId: string, platforms: Platform[]) {
    return platforms.map((platform) => {
      const existing = [...this.clips.values()].find((c) => c.candidate_id === candidateId && c.platform === platform);
      if (existing) return { ...existing };
      const clip = makeClip(`clip-new-${++this.seq}`, candidateId, platform, { created_by: "user-1" });
      this.clips.set(clip.id, clip);
      return { ...clip };
    });
  }
  async requestClipRender(id: string, signaled = false) {
    h.order.push("queue");
    const c = this.clips.get(id);
    if (!c) return null;
    c.render_error = null;
    if (!signaled) c.status = "draft";
    return { ...c };
  }
  async audit(entry: Audit) {
    this.audits.push(entry);
  }
}

/* Spiegel von local_worker.SQL_PENDING_CLIPS: Entwurf mit angenommenem Kandidaten. */
function pendingForLocalWorker(repo: MemoryRepo): string[] {
  return [...repo.clips.values()]
    .filter((c) => c.status === "draft" && repo.candidates.get(c.candidate_id ?? "")?.human_verdict === "accepted")
    .map((c) => c.id);
}

let repo: MemoryRepo;

beforeEach(() => {
  repo = new MemoryRepo();
  h.repo = repo;
  h.temporal = false;
  h.order.length = 0;
  h.signals.length = 0;
  h.decisions.length = 0;
});

function render(clipId: string) {
  return renderPost({} as NextRequest, { params: Promise.resolve({ id: SOURCE_ID, clipId }) });
}

function verdict(cid: string, body: Record<string, unknown>) {
  const request = new Request("http://localhost/api", { method: "POST", body: JSON.stringify(body) }) as unknown as NextRequest;
  return verdictPost(request, { params: Promise.resolve({ id: SOURCE_ID, cid }) });
}

describe("lib/clips/acceptance", () => {
  it("erkennt zurückgehaltene Kandidaten am Präfix der Analyse", () => {
    expect(isHeldCandidate({ human_verdict: null, verdict_reason: HELD_REASON })).toBe(true);
    expect(isHeldCandidate({ human_verdict: null, verdict_reason: null })).toBe(false);
    expect(isHeldCandidate({ human_verdict: "accepted", verdict_reason: HELD_REASON })).toBe(false);
  });

  it("Rückfall der Plattform wie im Worker: Markenprofil, Briefing, reels", () => {
    expect(defaultClipPlatform({ default_platform: "tiktok" }, { brief: { platform: "linkedin" } })).toBe("tiktok");
    expect(defaultClipPlatform(null, { brief: { platform: "linkedin" } })).toBe("linkedin");
    expect(defaultClipPlatform(null, { brief: {} })).toBe("reels");
  });

  it("nimmt die Plattform des ältesten vorhandenen Clips des Kandidaten", () => {
    const clips = [
      makeClip("b", "cand-1", "linkedin", { created_at: "2026-10-03T11:00:00Z" }),
      makeClip("a", "cand-1", "tiktok", { created_at: "2026-10-03T10:00:00Z" }),
      makeClip("x", "cand-1", "shorts", { created_at: "2026-10-03T09:00:00Z", status: "deleted" }),
      makeClip("o", "cand-2", "reels", { created_at: "2026-10-03T08:00:00Z" }),
    ];
    expect(acceptancePlatform("cand-1", clips, { default_platform: "shorts" }, { brief: {} })).toBe("tiktok");
    expect(acceptancePlatform("cand-3", clips, null, { brief: {} })).toBe("reels");
  });

  it("verweigert bei Ablehnung, nimmt ohne Urteil an, rendert sonst", () => {
    expect(renderAcceptance({ human_verdict: "rejected", verdict_reason: "zu allgemein" })).toEqual({
      kind: "refuse",
      error: "Dieser Vorschlag ist abgelehnt: zu allgemein",
    });
    expect(renderAcceptance({ human_verdict: null, verdict_reason: HELD_REASON })).toEqual({
      kind: "accept",
      reason: `angenommen beim Clippen, vorher ${HELD_REASON}`,
    });
    expect(renderAcceptance({ human_verdict: "accepted", verdict_reason: null })).toEqual({ kind: "render" });
    expect(renderAcceptance({ human_verdict: "edited", verdict_reason: null })).toEqual({
      kind: "refuse",
      error: "Dieser Kandidat wurde durch eine neue Version ersetzt",
    });
  });
});

describe("Render-Route: Video clippen an einem zurückgehaltenen Clip (H1)", () => {
  beforeEach(() => {
    repo.candidates.set("cand-1", makeCandidate("cand-1"));
    repo.clips.set("clip-1", makeClip("clip-1", "cand-1", "tiktok"));
  });

  it("ohne Temporal: Urteil durch den Nutzer, Audit, danach steht der Clip in der Warteschlange des lokalen Workers", async () => {
    expect(pendingForLocalWorker(repo)).toEqual([]);

    const res = await render("clip-1");
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json).toMatchObject({ ok: true, signaled: false, accepted: true });

    const cand = repo.candidates.get("cand-1")!;
    expect(cand.human_verdict).toBe("accepted");
    expect(cand.verdict_by).toBe("user-1");
    expect(cand.verdict_reason).toBe(`angenommen beim Clippen, vorher ${HELD_REASON}`);
    expect(h.order).toEqual(["verdict", "signal", "queue"]);
    expect(pendingForLocalWorker(repo)).toEqual(["clip-1"]);

    const accepted = repo.audits.find((a) => a.action === "candidate.accepted");
    expect(accepted).toMatchObject({
      entity: "candidates",
      entity_id: "cand-1",
      payload: { source_id: SOURCE_ID, version: 1, total: 6, gate_passed: true, platforms: ["tiktok"], clip_ids: ["clip-1"], via: "render" },
    });
    expect(repo.audits.map((a) => a.action)).toEqual(["candidate.accepted", "clip.render_requested"]);
    expect(h.decisions).toHaveLength(1);
    expect(h.decisions[0]).toMatchObject({ decision_type: "candidate_verdict", actor_type: "user", candidate_id: "cand-1" });
  });

  it("mit Temporal: das Signal geht erst nach dem Urteil hinaus", async () => {
    h.temporal = true;
    const res = await render("clip-1");
    expect(res.status).toBe(200);
    expect(h.order.indexOf("verdict")).toBeLessThan(h.order.indexOf("signal"));
    expect(h.signals).toEqual([{ sourceId: SOURCE_ID, candidateId: "cand-1", destination: "tiktok:clip-1" }]);
    expect(repo.candidates.get("cand-1")!.human_verdict).toBe("accepted");
    expect(repo.audits.find((a) => a.action === "clip.render_requested")?.payload.signaled).toBe(true);
  });

  it("zwei gleichzeitige Klicks: genau eine Annahme, ein Audit, ein Decision-Log-Eintrag, beide rendern", async () => {
    let attempts = 0;
    const original = repo.setCandidateVerdictIfOpen.bind(repo);
    repo.setCandidateVerdictIfOpen = async (id, verdict, reason) => {
      attempts += 1;
      return original(id, verdict, reason);
    };
    const [a, b] = await Promise.all([render("clip-1"), render("clip-1")]);
    expect(attempts).toBe(2); /* beide haben den Kandidaten ohne Urteil gelesen, die Bedingung entscheidet */
    expect([a.status, b.status]).toEqual([200, 200]);
    const accepted = [(await a.json()).accepted, (await b.json()).accepted].sort();
    expect(accepted).toEqual([false, true]);
    expect(h.order.filter((x) => x === "verdict")).toHaveLength(1);
    expect(repo.audits.filter((x) => x.action === "candidate.accepted")).toHaveLength(1);
    expect(h.decisions).toHaveLength(1);
    expect(repo.candidates.get("cand-1")!.verdict_by).toBe("user-1");
  });

  it("wird der Kandidat zwischen Lesen und Annehmen abgelehnt, antwortet die Route 409 und rendert nicht", async () => {
    const original = repo.setCandidateVerdictIfOpen.bind(repo);
    repo.setCandidateVerdictIfOpen = async (id, verdict, reason) => {
      Object.assign(repo.candidates.get(id)!, { human_verdict: "rejected", verdict_reason: "doch nicht", verdict_by: "user-2" });
      return original(id, verdict, reason);
    };
    const res = await render("clip-1");
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "Dieser Vorschlag ist abgelehnt: doch nicht" });
    expect(h.order).toEqual([]);
    expect(h.decisions).toHaveLength(0);
    expect(repo.audits).toEqual([]);
  });

  it("ersetzter Kandidat (edited): 409 wie in der Verdict-Route", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1", { human_verdict: "edited", verdict_reason: null, verdict_by: "user-2" }));
    const res = await render("clip-1");
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "Dieser Kandidat wurde durch eine neue Version ersetzt" });
    expect(h.order).toEqual([]);
  });

  it("das Audit der Annahme steht vor Signal und Warteschlange", async () => {
    const auditOrder: string[] = [];
    const audit = repo.audit.bind(repo);
    repo.audit = async (entry) => {
      auditOrder.push(`${entry.action}@${h.order.length}`);
      return audit(entry);
    };
    await render("clip-1");
    expect(auditOrder).toEqual(["candidate.accepted@1", "clip.render_requested@3"]);
  });

  it("ein schon angenommener Kandidat wird nicht noch einmal beurteilt", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1", { human_verdict: "accepted", verdict_reason: "automatisch angenommen (ohne Auswahlschritt)" }));
    const res = await render("clip-1");
    expect(res.status).toBe(200);
    expect((await res.json()).accepted).toBe(false);
    expect(h.order).toEqual(["signal", "queue"]);
    expect(repo.audits.map((a) => a.action)).toEqual(["clip.render_requested"]);
    expect(h.decisions).toHaveLength(0);
  });

  it("abgelehnter Kandidat: 409 mit dem Grund, kein Signal, keine Warteschlange (L3)", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1", { human_verdict: "rejected", verdict_reason: "Zahl stimmt nicht", verdict_by: "user-2" }));
    const res = await render("clip-1");
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "Dieser Vorschlag ist abgelehnt: Zahl stimmt nicht" });
    expect(h.order).toEqual([]);
    expect(repo.candidates.get("cand-1")!.human_verdict).toBe("rejected");
    expect(repo.audits).toEqual([]);
    expect(pendingForLocalWorker(repo)).toEqual([]);
  });
});

describe("Verdict-Route: Plattform bei der Annahme (M3, L11)", () => {
  it("ohne platforms übernimmt sie die Plattform des Auto-Clips und verwendet ihn wieder", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1"));
    repo.clips.set("clip-auto", makeClip("clip-auto", "cand-1", "tiktok"));

    const res = await verdict("cand-1", { verdict: "accepted" });
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.platforms).toEqual(["tiktok"]);
    expect(json.clips.map((c: Clip) => c.id)).toEqual(["clip-auto"]);
    expect(repo.clips.size).toBe(1);
    expect(h.signals).toEqual([{ sourceId: SOURCE_ID, candidateId: "cand-1", destination: "tiktok" }]);
    expect(repo.candidates.get("cand-1")!).toMatchObject({ human_verdict: "accepted", verdict_by: "user-1" });
    expect(pendingForLocalWorker(repo)).toEqual(["clip-auto"]);
  });

  it("ohne vorhandenen Clip gilt Markenprofil, dann Briefing, dann reels", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1"));
    expect((await (await verdict("cand-1", { verdict: "accepted" })).json()).platforms).toEqual(["shorts"]);

    repo.brand = null;
    repo.candidates.set("cand-2", makeCandidate("cand-2"));
    expect((await (await verdict("cand-2", { verdict: "accepted" })).json()).platforms).toEqual(["linkedin"]);

    repo.source = { ...repo.source, brief: {} };
    repo.candidates.set("cand-3", makeCandidate("cand-3"));
    expect((await (await verdict("cand-3", { verdict: "accepted" })).json()).platforms).toEqual(["reels"]);
  });

  it("genannte platforms gelten; nicht gewählte Automatik-Entwürfe fallen weg und werden nicht gerendert (H1b)", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1"));
    repo.clips.set("clip-auto", makeClip("clip-auto", "cand-1", "tiktok"));
    /* Ein von Hand angelegter Entwurf und ein schon gerenderter Automatik-Clip bleiben unberührt. */
    repo.clips.set("clip-hand", makeClip("clip-hand", "cand-1", "shorts", { created_by: "user-3" }));
    repo.clips.set("clip-done", makeClip("clip-done", "cand-1", "reels", { status: "rendered" }));

    const json = await (await verdict("cand-1", { verdict: "accepted", platforms: ["linkedin"] })).json();
    expect(json.platforms).toEqual(["linkedin"]);
    const created = json.clips[0].id as string;
    expect(repo.clips.get("clip-auto")!.status).toBe("deleted");
    expect(repo.clips.get("clip-hand")!.status).toBe("draft");
    expect(repo.clips.get("clip-done")!.status).toBe("rendered");
    expect(pendingForLocalWorker(repo).sort()).toEqual(["clip-hand", created].sort());
    expect(repo.audits.find((a) => a.action === "clip.auto_draft_dropped")).toMatchObject({
      entity_id: "clip-auto",
      payload: { candidate_id: "cand-1", platform: "tiktok", chosen: ["linkedin"] },
    });
  });

  it("ohne platforms bleibt der Automatik-Entwurf erhalten", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1"));
    repo.clips.set("clip-auto", makeClip("clip-auto", "cand-1", "tiktok"));
    await verdict("cand-1", { verdict: "accepted" });
    expect(repo.clips.get("clip-auto")!.status).toBe("draft");
    expect(repo.audits.some((a) => a.action === "clip.auto_draft_dropped")).toBe(false);
  });

  it("ersetzter Kandidat: 409 mit demselben Text wie die Render-Route", async () => {
    repo.candidates.set("cand-1", makeCandidate("cand-1", { human_verdict: "edited" }));
    const res = await verdict("cand-1", { verdict: "accepted" });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "Dieser Kandidat wurde durch eine neue Version ersetzt" });
  });
});

describe("Urteil beim Veröffentlichen (M5)", () => {
  it("sperrt ohne angenommenen Kandidaten mit demselben Text wie /api/v1 und der Worker", () => {
    expect(verdictReason("cand-1", { human_verdict: "accepted" })).toBeNull();
    expect(verdictReason("cand-1", { human_verdict: null })).toEqual({
      code: "candidate_not_accepted",
      message: "Kandidat ist nicht angenommen (Urteil offen)",
    });
    expect(verdictReason("cand-1", { human_verdict: "rejected" })?.message).toBe("Kandidat ist nicht angenommen (Urteil abgelehnt)");
    /* Ein ersetzter Kandidat sperrt auch in der Oberfläche (clip-context nutzt dieselbe Funktion). */
    expect(verdictReason("cand-1", { human_verdict: "edited" })?.message).toBe(
      "Kandidat ist nicht angenommen (Urteil durch eine neue Version ersetzt)",
    );
    expect(verdictReason(null, null)).toEqual({ code: "candidate_missing", message: "Clip hat keinen Kandidaten" });
  });
});

describe("Rollen", () => {
  it("wer rendern darf, darf auch beurteilen (der Render-Klick nimmt zurückgehaltene Kandidaten an)", () => {
    const render = ROLES.filter((r) => can(r, "clip.render"));
    expect(render.length).toBeGreaterThan(0);
    for (const role of render) expect(can(role, "candidate.verdict")).toBe(true);
  });
});
