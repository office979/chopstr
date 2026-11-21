/* Eine Messung für die Zeitreihe: welche Quelle bei welcher Publikation gefragt wird. Leser und Provider
 * sind ersetzt; geprüft wird die Weiche zwischen öffentlichem Leser und Verbindung. */

import { describe, expect, it, vi } from "vitest";
import { linkPlatformOf, takeSnapshot, type SnapshotDeps } from "@/lib/publishing/snapshot";
import { emptyPublicMetrics } from "@/lib/publishing/public-metrics";

function deps(over: Partial<SnapshotDeps> = {}): SnapshotDeps {
  return {
    readPublic: vi.fn(async () => ({ ok: true as const, platform: "youtube" as const, metrics: { ...emptyPublicMetrics(), views: 100 }, source: "public_api" as const, published_at: null, author_id: null, author_label: null, raw: { id: "v" } })),
    viaConnection: vi.fn(async () => ({ metrics: { views: 200, follows: 3 } })),
    ...over,
  };
}

describe("takeSnapshot", () => {
  it("fragt bei tracking oauth die Verbindung", async () => {
    const d = deps();
    const r = await takeSnapshot({ platform: "youtube", external_id: "v", connection_id: "c", tracking: "oauth" }, "48h", d);
    expect(r).toMatchObject({ source: "oauth", error: null });
    expect(r.metrics).toMatchObject({ views: 200, follows: 3, engaged_views: null });
    expect(d.viaConnection).toHaveBeenCalledWith("48h");
    expect(d.readPublic).not.toHaveBeenCalled();
  });

  it("behandelt Zeilen ohne tracking wie oauth", async () => {
    const r = await takeSnapshot({ platform: "youtube", external_id: "v", connection_id: "c" }, "7d", deps());
    expect(r.source).toBe("oauth");
  });

  it("liest bei tracking link öffentlich", async () => {
    const d = deps();
    const r = await takeSnapshot({ platform: "youtube", external_id: "v", connection_id: null, tracking: "link" }, "7d", d);
    expect(r).toMatchObject({ source: "public_api", error: null, raw: { id: "v" } });
    expect(r.metrics.views).toBe(100);
    expect(d.viaConnection).not.toHaveBeenCalled();
  });

  it("fällt bei eigener Verbindung auf die Verbindung zurück, wenn öffentlich nichts kommt", async () => {
    const d = deps({ readPublic: async () => ({ ok: false, platform: "tiktok", error: "nicht_verbunden", message: "TikTok nur über Verbindung." }) });
    const r = await takeSnapshot({ platform: "tiktok", external_id: "7301234567890123456", connection_id: "c", tracking: "link" }, "7d", d);
    expect(r).toMatchObject({ source: "oauth", error: null });
    expect(r.metrics.views).toBe(200);
  });

  it("meldet den Grund, wenn öffentlich nichts kommt und keine Verbindung da ist", async () => {
    const r = await takeSnapshot(
      { platform: "youtube", external_id: "v", connection_id: null, tracking: "link" },
      "7d",
      deps({ readPublic: async () => ({ ok: false, platform: "youtube", error: "nicht_konfiguriert", message: "YouTube ist nicht konfiguriert: YOUTUBE_API_KEY fehlt." }) }),
    );
    expect(r.error).toContain("nicht konfiguriert");
    expect(r.metrics.views).toBeNull();
  });

  it("wirft nicht, wenn die Verbindung wirft", async () => {
    const r = await takeSnapshot(
      { platform: "youtube", external_id: "v", connection_id: "c", tracking: "oauth" },
      "7d",
      deps({
        viaConnection: async () => {
          throw new Error("Token abgelaufen");
        },
      }),
    );
    expect(r.error).toBe("Token abgelaufen");
  });

  it("misst nicht bei tracking off", async () => {
    const d = deps();
    const r = await takeSnapshot({ platform: "youtube", external_id: "v", connection_id: "c", tracking: "off" }, "7d", d);
    expect(r.error).toContain("abgeschaltet");
    expect(d.viaConnection).not.toHaveBeenCalled();
  });

  it("verlangt eine externe ID für Links", async () => {
    const r = await takeSnapshot({ platform: "youtube", external_id: null, connection_id: null, tracking: "link" }, "7d", deps());
    expect(r.error).toContain("externe ID");
  });
});

describe("linkPlatformOf", () => {
  it("bildet Schnittformate auf Plattformen ab", () => {
    expect(linkPlatformOf("shorts")).toBe("youtube");
    expect(linkPlatformOf("reels")).toBe("instagram");
    expect(linkPlatformOf("x")).toBe("x");
    expect(linkPlatformOf("manual")).toBeNull();
  });
});
