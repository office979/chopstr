/* „Als gepostet eintragen“ (POST /api/projects/{id}/clips/{clipId}/publish) mit einer manuellen Verbindung:
 * steht ein Link dabei, läuft derselbe Weg wie „Link verfolgen“ (registerLinkForClip), sonst ein Eintrag
 * ohne Link und ohne Messung wie bisher. */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

const h = vi.hoisted(() => ({
  register: vi.fn(),
  createPublication: vi.fn(),
  decisions: [] as unknown[],
}));

vi.mock("@/lib/publishing/auth", () => ({ requirePublishingApi: async () => ({ userId: "u", workspaceId: "ws", role: "owner" }) }));
vi.mock("@/lib/publishing/clip-context", () => ({
  loadClipContext: async () => ({
    clip: { id: "clip-1", platform: "shorts", source_id: "src-1", candidate_id: "cand-1" },
    source: { id: "src-1", brand_profile_id: null },
    hook: null,
    gates: [],
    eintragen: { gruende: [] },
    extras: {},
  }),
}));
vi.mock("@/lib/repo/publishing", () => ({
  getPublishingRepo: () => ({
    getConnection: async () => ({ id: "conn-manual", platform: "manual", status: "connected" }),
    createPublication: h.createPublication,
    getPublication: async (id: string) => ({ id }),
  }),
}));
vi.mock("@/lib/publishing/link-check-server", () => ({ registerLinkForClip: h.register }));
vi.mock("@/lib/decision-log", () => ({ clipFeatures: () => ({}), recordDecision: async (d: unknown) => void h.decisions.push(d) }));
vi.mock("@/lib/temporal", () => ({ startPublishWorkflow: async () => false }));
vi.mock("@/lib/repo", () => ({ getRepo: () => ({ audit: async () => undefined }) }));

const { POST } = await import("@/app/api/projects/[id]/clips/[clipId]/publish/route");

function call(body: Record<string, unknown>) {
  const req = new Request("http://x/api/projects/src-1/clips/clip-1/publish", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return POST(req as unknown as NextRequest, { params: Promise.resolve({ id: "src-1", clipId: "clip-1" }) });
}

beforeEach(() => {
  h.register.mockReset();
  h.createPublication.mockReset();
  h.decisions.length = 0;
});

describe("Als gepostet eintragen", () => {
  it("trägt einen Link über registerLinkForClip ein, nicht als bloße URL", async () => {
    h.register.mockResolvedValue({ ok: true, publication: { id: "pub-1", tracking: "link" }, check: { measurable: true }, summary: ["Link erkannt: YouTube", "Kein verbundenes Konto", "Wird 30 Tage lang gemessen"] });
    const res = await call({ confirm: true, connection_id: "conn-manual", external_url: " https://youtu.be/dQw4w9WgXcQ " });
    expect(res.status).toBe(200);
    expect(h.register).toHaveBeenCalledWith(expect.objectContaining({ url: "https://youtu.be/dQw4w9WgXcQ", via: "ui", clip: expect.objectContaining({ id: "clip-1" }) }));
    expect(h.createPublication).not.toHaveBeenCalled();
    const body = (await res.json()) as { publication: { id: string }; summary: string[] };
    expect(body.publication.id).toBe("pub-1");
    expect(body.summary.at(-1)).toBe("Wird 30 Tage lang gemessen");
    expect(h.decisions).toHaveLength(1);
  });

  it("gibt Dubletten und ungültige Links mit derselben Antwort wie „Link verfolgen“ zurück", async () => {
    h.register.mockResolvedValue({ ok: false, status: 409, code: "link_duplicate", message: "Dieser Beitrag ist schon eingetragen.", check: {} });
    const res = await call({ confirm: true, connection_id: "conn-manual", external_url: "https://youtu.be/dQw4w9WgXcQ" });
    expect(res.status).toBe(409);
    expect(await res.json()).toMatchObject({ error: "Dieser Beitrag ist schon eingetragen.", code: "link_duplicate" });
    expect(h.createPublication).not.toHaveBeenCalled();
    expect(h.decisions).toHaveLength(0);
  });

  it("legt ohne Link wie bisher einen Eintrag ohne Messung an", async () => {
    h.createPublication.mockResolvedValue({ id: "pub-2" });
    const res = await call({ confirm: true, connection_id: "conn-manual" });
    expect(res.status).toBe(200);
    expect(h.register).not.toHaveBeenCalled();
    expect(h.createPublication).toHaveBeenCalledWith(expect.objectContaining({ status: "manual", external_url: null, published_at: null }));
  });
});
