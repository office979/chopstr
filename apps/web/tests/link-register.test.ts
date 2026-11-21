/* Link am Clip eintragen (registerLinkForClip): Dubletten auch bei gleichzeitigen Anfragen.
 *
 * Das Repository ist durch einen Speicher mit derselben Eindeutigkeit wie publications_link_unique_idx
 * (0021) ersetzt: (workspace, platform, external_id) bei tracking link. Die lesende Prüfung sieht in
 * diesem Test bewusst nichts, wie bei vier Anfragen, die alle vor dem ersten Einfügen lesen. */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LinkPublicationCreateInput, LinkPublicationCreateResult, Publication } from "@/lib/repo/types-api";

const store: Publication[] = [];
const audits: unknown[] = [];
let readSideDuplicate: { id: string; platform: string } | null = null;
const lookups: string[][] = [];

function publicationFrom(input: LinkPublicationCreateInput): Publication {
  return {
    id: `pub-${store.length + 1}`,
    workspace_id: "ws-1",
    clip_id: input.clip_id,
    connection_id: input.connection_id,
    platform: input.platform,
    status: "manual",
    scheduled_for: null,
    caption: null,
    title: null,
    external_id: input.external_id,
    external_url: input.external_url,
    error: null,
    published_at: input.published_at,
    metrics: null,
    metrics_fetched_at: null,
    temporal_workflow_id: null,
    created_by: "user-1",
    created_at: new Date().toISOString(),
    tracking: "link",
    tracking_until: input.tracking_until,
    next_snapshot_at: input.next_snapshot_at,
    link_check: input.link_check,
  };
}

vi.mock("@/lib/repo/api", () => ({
  getApiRepo: () => ({
    listPlatformConnections: async () => [],
    findPublicationByExternal: async (platforms: string[]) => {
      lookups.push(platforms);
      return readSideDuplicate && platforms.includes(readSideDuplicate.platform) ? { id: readSideDuplicate.id } : null;
    },
    createLinkPublication: async (input: LinkPublicationCreateInput): Promise<LinkPublicationCreateResult> => {
      await new Promise((r) => setTimeout(r, 5));
      const existing = store.find((p) => p.tracking === "link" && p.platform === input.platform && p.external_id === input.external_id);
      if (existing) return { created: false, existing_id: existing.id };
      const publication = publicationFrom(input);
      store.push(publication);
      return { created: true, publication };
    },
  }),
}));
vi.mock("@/lib/repo", () => ({ getRepo: () => ({ audit: async (entry: unknown) => void audits.push(entry) }) }));
vi.mock("@/lib/publishing/public-metrics", () => ({
  readPublicMetrics: async () => ({ ok: false, platform: "youtube", error: "nicht_konfiguriert", message: "Zahlen für YouTube sind noch nicht eingerichtet." }),
}));
vi.mock("@/lib/publishing/link-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/publishing/link-check")>()),
  probeUrl: async () => true,
}));

const { registerLinkForClip } = await import("@/lib/publishing/link-check-server");

const clip = { id: "clip-1", platform: "shorts", source_id: "src-1" };

beforeEach(() => {
  store.length = 0;
  audits.length = 0;
  lookups.length = 0;
  readSideDuplicate = null;
});

describe("registerLinkForClip", () => {
  it("legt bei vier gleichzeitigen Anfragen genau eine Publikation an, die übrigen bekommen 409 mit deren ID", async () => {
    const results = await Promise.all(
      Array.from({ length: 4 }, () => registerLinkForClip({ clip, url: "https://youtube.com/shorts/raceRACE001", via: "api" })),
    );
    expect(store).toHaveLength(1);
    const ok = results.filter((r) => r.ok);
    const dup = results.filter((r) => !r.ok);
    expect(ok).toHaveLength(1);
    expect(dup).toHaveLength(3);
    for (const r of dup) {
      expect(r.ok).toBe(false);
      if (r.ok) continue;
      expect(r.status).toBe(409);
      expect(r.code).toBe("link_duplicate");
      expect(r.duplicate_publication_id).toBe(store[0].id);
      expect(r.check.checks.duplicate_publication_id).toBe(store[0].id);
    }
    expect(audits).toHaveLength(1);
  });

  it("erkennt eine OAuth-Publikation mit derselben ID unter dem Schnittformat (shorts) als Dublette", async () => {
    readSideDuplicate = { id: "pub-oauth", platform: "shorts" };
    const r = await registerLinkForClip({ clip, url: "https://youtu.be/dQw4w9WgXcQ", via: "ui" });
    expect(lookups[0]).toEqual(["youtube", "shorts"]);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.status).toBe(409);
    expect(r.duplicate_publication_id).toBe("pub-oauth");
    expect(store).toHaveLength(0);
  });
});
