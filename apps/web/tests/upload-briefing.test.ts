import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Source } from "@/lib/repo/types";

/* Briefing beim Upload (Master-Prompt Phase 5): drei Felder und die Plattform, freiwillig, mit
 * Vorbelegung aus dem Markenprofil, gespeichert in `sources.brief` über die vorhandenen Wege
 * (tus-Metadaten und direkter Upload über finalize, Testmodus über upload/actions). */

const h = vi.hoisted(() => ({ created: [] as Partial<Source>[] }));

const repo = {
  getSource: async () => null,
  createSource: async (input: Partial<Source>) => {
    h.created.push(input);
    return { ...input, id: input.id ?? "neu" } as Source;
  },
  audit: async () => undefined,
  updateSource: async () => null,
};

vi.mock("@/lib/repo", () => ({ getRepo: () => repo }));
vi.mock("@/lib/repo/api", () => ({ getApiRepo: () => ({}) }));
vi.mock("@/lib/temporal", () => ({ startClipProjectWorkflow: async () => null }));
vi.mock("@/lib/session", () => ({
  withSessionContext: async (_s: unknown, fn: () => Promise<unknown>) => fn(),
  requireRole: async () => ({ workspaceId: "ws-1", userId: "user-1", role: "editor" }),
}));
vi.mock("@/lib/env", () => ({ isDemoMode: () => true }));

import { BRIEF_MAX_CHARS, briefDefaults, briefMetadata } from "@/lib/uploads/brief";
import { finalizeUpload } from "@/lib/uploads/finalize";
import { createDemoProject } from "@/app/upload/actions";

beforeEach(() => {
  h.created.length = 0;
});

describe("lib/uploads/brief", () => {
  it("belegt die Plattform aus dem Markenprofil vor, die Texte bleiben leer", () => {
    expect(briefDefaults({ platform: "linkedin" })).toEqual({ audience: "", wanted: "", exclude: "", platform: "linkedin" });
    expect(briefDefaults(null).platform).toBe("");
  });

  it("schickt nur Ausgefülltes, getrimmt und gekürzt", () => {
    expect(briefMetadata({ audience: "  Gründerinnen   in Wien ", wanted: "", exclude: " ", platform: "" })).toEqual({
      brief_audience: "Gründerinnen in Wien",
    });
    const lang = "x".repeat(BRIEF_MAX_CHARS + 50);
    expect(briefMetadata({ audience: "", wanted: lang, exclude: "Werbeblock", platform: "tiktok" })).toEqual({
      brief_wanted: "x".repeat(BRIEF_MAX_CHARS),
      brief_exclude: "Werbeblock",
      platform: "tiktok",
    });
  });

  it("verwirft eine unbekannte Plattform", () => {
    expect(briefMetadata({ audience: "", wanted: "", exclude: "", platform: "myspace" as never })).toEqual({});
  });
});

describe("Briefing landet in sources.brief", () => {
  it("über die Upload-Metadaten (tus und direkt)", async () => {
    const meta = {
      title: "Folge 13",
      filename: "folge13.mp4",
      rights_status: "own",
      ...briefMetadata({ audience: "Steuerberater", wanted: "konkrete Fristen", exclude: "Sponsoring", platform: "linkedin" }),
    };
    await finalizeUpload({
      session: { workspaceId: "ws-1", userId: "user-1", role: "editor" } as never,
      brandProfileId: null,
      meta,
      storageKey: "sources/ws-1/x/folge13.mp4",
      storageBucket: null,
      sizeBytes: 10,
      via: "direct",
    });
    expect(h.created[0]?.brief).toEqual({ audience: "Steuerberater", wanted: "konkrete Fristen", exclude: "Sponsoring", platform: "linkedin" });
  });

  it("ohne Angaben bleibt das Briefing leer", async () => {
    await finalizeUpload({
      session: { workspaceId: "ws-1", userId: "user-1", role: "editor" } as never,
      brandProfileId: null,
      meta: { title: "Folge 14", filename: "f.mp4", ...briefMetadata(briefDefaults(null)) },
      storageKey: "k",
      storageBucket: null,
      sizeBytes: 1,
      via: "direct",
    });
    expect(h.created[0]?.brief).toEqual({ audience: undefined, wanted: undefined, exclude: undefined, platform: undefined });
  });

  it("über den Testmodus (upload/actions)", async () => {
    const meta = briefMetadata({ audience: "Lehrkräfte", wanted: "", exclude: "Namen von Schülern", platform: "reels" });
    const result = await createDemoProject({
      title: "Vortrag",
      brand_profile_id: null,
      filename: "v.mp4",
      filetype: "video/mp4",
      size_bytes: 1,
      rights_status: "own",
      rights_confirmed: true,
      brief_audience: meta.brief_audience,
      brief_wanted: meta.brief_wanted,
      brief_exclude: meta.brief_exclude,
      platform: "reels",
    });
    expect("id" in result).toBe(true);
    expect(h.created[0]?.brief).toEqual({ audience: "Lehrkräfte", wanted: undefined, exclude: "Namen von Schülern", platform: "reels" });
  });
});
