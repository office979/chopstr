/* „Nicht mehr messen“ (stopTracking): nur verfolgte Links, nichts wird gelöscht, zweimal ist harmlos,
 * und der Vertrag in OpenAPI erlaubt nur { tracking: "off" }. */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestSchema, resolveRef, ENDPOINTS } from "@/lib/api/openapi";
import { validate } from "@/lib/api/validate";
import type { Publication } from "@/lib/repo/types-api";

const ID = "11111111-1111-4111-8111-111111111111";
let current: Publication | null = null;
const audits: { action: string }[] = [];
const stopLinkTracking = vi.fn(async (id: string) => {
  if (!current || current.id !== id || current.tracking !== "link") return null;
  current = { ...current, tracking: "off", next_snapshot_at: null };
  return current;
});

vi.mock("@/lib/repo/api", () => ({ getApiRepo: () => ({ getPublication: async () => current, stopLinkTracking }) }));
vi.mock("@/lib/repo", () => ({ getRepo: () => ({ audit: async (e: { action: string }) => void audits.push(e) }) }));

const { stopTracking } = await import("@/lib/publishing/tracking-server");

function pub(over: Partial<Publication> = {}): Publication {
  return {
    id: ID, workspace_id: "ws", clip_id: "c", connection_id: null, platform: "youtube", status: "manual", scheduled_for: null, caption: null, title: null,
    external_id: "dQw4w9WgXcQ", external_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ", error: null, published_at: null, metrics: null, metrics_fetched_at: null,
    temporal_workflow_id: null, created_by: null, created_at: "2026-11-21T10:00:00Z", tracking: "link", tracking_until: "2026-12-21T10:00:00Z",
    next_snapshot_at: "2026-11-21T11:00:00Z", link_check: null, ...over,
  };
}

beforeEach(() => {
  current = null;
  audits.length = 0;
  stopLinkTracking.mockClear();
});

describe("stopTracking", () => {
  it("schaltet einen verfolgten Link ab, ohne zu löschen, und protokolliert das", async () => {
    current = pub();
    const r = await stopTracking({ publicationId: ID, via: "api", apiKeyId: "k1" });
    expect(r).toMatchObject({ ok: true, changed: true, publication: { tracking: "off", next_snapshot_at: null, external_id: "dQw4w9WgXcQ" } });
    expect(audits.map((a) => a.action)).toEqual(["publication.tracking_stopped"]);
  });

  it("ist beim zweiten Aufruf harmlos", async () => {
    current = pub({ tracking: "off", next_snapshot_at: null });
    const r = await stopTracking({ publicationId: ID, via: "ui" });
    expect(r).toMatchObject({ ok: true, changed: false });
    expect(stopLinkTracking).not.toHaveBeenCalled();
    expect(audits).toEqual([]);
  });

  it("lehnt OAuth-Publikationen mit 409 ab und unbekannte oder ungültige IDs mit 404", async () => {
    current = pub({ tracking: "oauth" });
    expect(await stopTracking({ publicationId: ID, via: "ui" })).toMatchObject({ ok: false, status: 409, code: "tracking_not_link" });
    current = null;
    expect(await stopTracking({ publicationId: ID, via: "ui" })).toMatchObject({ ok: false, status: 404 });
    expect(await stopTracking({ publicationId: "nope", via: "ui" })).toMatchObject({ ok: false, status: 404 });
  });
});

describe("PATCH /publications/{id} im Vertrag", () => {
  const check = (body: unknown) => validate(body, requestSchema("PublicationPatch"), "body", [], resolveRef);
  it("erlaubt nur tracking off", () => {
    expect(check({ tracking: "off" })).toEqual([]);
    expect(check({ tracking: "link" }).length).toBeGreaterThan(0);
    expect(check({}).length).toBeGreaterThan(0);
    expect(check({ tracking: "off", delete: true }).length).toBeGreaterThan(0);
    expect(ENDPOINTS.find((e) => e.method === "patch" && e.path === "/publications/{id}")?.scope).toBe("publish");
  });
});
