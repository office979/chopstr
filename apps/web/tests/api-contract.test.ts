/* Vertrag der Link- und Performance-API: ungültige IDs geben 404 in der v1-Fehlerform, und die
 * tatsächlichen Antworten passen zu den Schemas in OpenAPI (Linktest, 409 bei Dubletten). */

import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { ENDPOINTS, SCHEMAS, resolveRef } from "@/lib/api/openapi";
import { validate, type JsonSchema } from "@/lib/api/validate";
import { runLinkCheck } from "@/lib/publishing/link-check";
import { parsePostUrl } from "@/lib/publishing/links";

const getPublication = vi.fn(async () => null);
const getClip = vi.fn(async () => null);
vi.mock("@/lib/repo/api", () => ({ getApiRepo: () => ({ getPublication }) }));
vi.mock("@/lib/repo", () => ({ getRepo: () => ({ getClip, getSource: async () => null, getCandidate: async () => null }) }));

const { isUuidShape, loadClip, loadPublication, loadSource } = await import("@/lib/api/lookup");

describe("ungültige IDs", () => {
  it("erkennt die Form einer UUID", () => {
    expect(isUuidShape("11111111-1111-4111-8111-111111111111")).toBe(true);
    expect(isUuidShape("not-a-uuid")).toBe(false);
    expect(isUuidShape("11111111-1111-4111-8111-11111111111")).toBe(false);
  });

  it("geben 404 not_found statt einer Datenbankabfrage", async () => {
    for (const load of [() => loadPublication("not-a-uuid"), () => loadClip("not-a-uuid"), () => loadSource("x'; drop")]) {
      const err = await load().then(
        () => null,
        (e: unknown) => e,
      );
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
      expect((err as ApiError).code).toBe("not_found");
    }
    expect(getPublication).not.toHaveBeenCalled();
    expect(getClip).not.toHaveBeenCalled();
  });

  it("fragt bei gültiger Form das Repository und gibt 404, wenn nichts da ist", async () => {
    await expect(loadPublication("11111111-1111-4111-8111-111111111111")).rejects.toMatchObject({ status: 404 });
    expect(getPublication).toHaveBeenCalledOnce();
  });
});

describe("OpenAPI passt zu den Antworten", () => {
  const schema = (name: string) => SCHEMAS[name] as JsonSchema;

  it("beschreibt das Ergebnis des Linktests samt measurable und reachable null", async () => {
    const result = await runLinkCheck("https://www.instagram.com/reel/C1abcDEFghi/", {
      resolve: async (u) => parsePostUrl(u),
      readPublic: async () => ({ ok: false, platform: "instagram", error: "nicht_verbunden", message: "Instagram nur mit Verbindung." }),
      listConnections: async () => [],
      findDuplicate: async () => null,
      probe: async () => null,
      now: () => Date.parse("2026-11-21T12:00:00Z"),
    });
    expect(result.checks.reachable).toBeNull();
    expect(validate({ ...result, clip_id: null }, schema("LinkTestResult"), "body", [], resolveRef)).toEqual([]);
    expect(Object.keys(schema("LinkTestResult").properties ?? {})).toEqual(expect.arrayContaining(["measurable", "notes"]));
  });

  it("beschreibt die 409 bei Dubletten mit duplicate_publication_id und check", async () => {
    const ep = ENDPOINTS.find((e) => e.path === "/clips/{id}/links" && e.method === "post");
    const conflict = ep?.responses?.["409"] as { schema?: JsonSchema } | undefined;
    expect(conflict?.schema).toEqual({ $ref: "#/components/schemas/LinkConflict" });
    const check = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", {
      resolve: async (u) => parsePostUrl(u),
      readPublic: async () => ({ ok: false, platform: "youtube", error: "nicht_konfiguriert", message: "Zahlen für YouTube sind noch nicht eingerichtet." }),
      listConnections: async () => [],
      findDuplicate: async () => ({ id: "11111111-1111-4111-8111-111111111111" }),
      probe: async () => true,
      now: () => Date.parse("2026-11-21T12:00:00Z"),
    });
    const body = { error: { code: "link_duplicate", message: "Dieser Beitrag ist schon eingetragen." }, duplicate_publication_id: check.checks.duplicate_publication_id, check };
    expect(validate(body, schema("LinkConflict"), "body", [], resolveRef)).toEqual([]);
    expect(ep?.description).not.toContain("ab sofort: stündlich bis 6 h, alle 6 h bis 48 h, danach täglich. Gleicher");
    expect(ep?.description).toContain("keinen Messtermin");
  });
});
