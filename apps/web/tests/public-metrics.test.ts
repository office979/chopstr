/* Öffentliche Messwerte für YouTube und X, ohne Netz: fetch ist gemockt. Wichtig sind drei Dinge:
 * fehlende Schlüssel werfen nie, die Felder landen am richtigen Platz, und X wird je ID nur einmal
 * pro Stunde abgefragt (Abrechnung je gelesenem Beitrag). */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearPublicMetricsCache, configuredReaderPlatforms, publicMetricsCacheSize, publicReaderConfigured, readPublicMetrics, X_CACHE_MAX, X_CACHE_TTL_MS } from "@/lib/publishing/public-metrics";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function fetchReturning(body: unknown, status = 200) {
  return vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(body, status));
}

beforeEach(() => clearPublicMetricsCache());

describe("readPublicMetrics YouTube", () => {
  it("meldet nicht konfiguriert ohne YOUTUBE_API_KEY und ruft kein Netz auf", async () => {
    const fetchImpl = vi.fn();
    const r = await readPublicMetrics("youtube", "dQw4w9WgXcQ", { env: {}, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(r).toMatchObject({ ok: false, error: "nicht_konfiguriert" });
    expect(!r.ok && r.message).toBe("Zahlen für YouTube sind noch nicht eingerichtet.");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("liest Statistik, Kanal und Veröffentlichungszeit", async () => {
    const fetchImpl = fetchReturning({
      items: [{ id: "dQw4w9WgXcQ", snippet: { publishedAt: "2026-11-20T10:00:00Z", channelId: "UC123", channelTitle: "PLACEMedia" }, statistics: { viewCount: "1234", likeCount: "56", commentCount: "7" } }],
    });
    const r = await readPublicMetrics("youtube", "dQw4w9WgXcQ", { env: { YOUTUBE_API_KEY: "k" }, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.metrics).toMatchObject({ views: 1234, likes: 56, comments: 7, shares: null, saves: null });
    expect(r).toMatchObject({ source: "public_api", published_at: "2026-11-20T10:00:00Z", author_id: "UC123", author_label: "PLACEMedia" });
    const url = String(fetchImpl.mock.calls[0][0]);
    expect(url).toContain("part=statistics%2Csnippet%2CcontentDetails");
    expect(url).toContain("id=dQw4w9WgXcQ");
  });

  it("meldet nicht gefunden bei leerer Liste", async () => {
    const r = await readPublicMetrics("youtube", "dQw4w9WgXcQ", { env: { YOUTUBE_API_KEY: "k" }, fetchImpl: fetchReturning({ items: [] }) as unknown as typeof fetch });
    expect(r).toMatchObject({ ok: false, error: "nicht_gefunden" });
  });

  it("gibt den Schlüssel in Fehlermeldungen nie preis", async () => {
    const fetchImpl = vi.fn(async () => new Response("bad request for key=geheim123", { status: 400 }));
    const r = await readPublicMetrics("youtube", "dQw4w9WgXcQ", { env: { YOUTUBE_API_KEY: "geheim123" }, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(r.ok).toBe(false);
    expect(!r.ok && r.message).not.toContain("geheim123");
  });

  it("wirft nicht, wenn das Netz ausfällt", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("offline");
    });
    const r = await readPublicMetrics("youtube", "dQw4w9WgXcQ", { env: { YOUTUBE_API_KEY: "k" }, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(r).toMatchObject({ ok: false, error: "fehler" });
  });
});

const X_BODY = {
  data: {
    id: "1856789012345678901",
    author_id: "42",
    created_at: "2026-11-20T08:00:00.000Z",
    public_metrics: { retweet_count: 3, reply_count: 4, like_count: 50, quote_count: 2, bookmark_count: 6, impression_count: 9000 },
    attachments: { media_keys: ["7_1"] },
  },
  includes: { media: [{ media_key: "7_1", type: "video", public_metrics: { view_count: 4200 } }], users: [{ id: "42", username: "placemedia" }] },
};

describe("readPublicMetrics X", () => {
  it("meldet nicht konfiguriert ohne X_BEARER_TOKEN", async () => {
    const r = await readPublicMetrics("x", "1856789012345678901", { env: {} });
    expect(r).toMatchObject({ ok: false, error: "nicht_konfiguriert", message: "Zahlen für X sind noch nicht eingerichtet." });
  });

  it("nimmt Videoaufrufe vom Medium und Impressionen als Reichweite", async () => {
    const fetchImpl = fetchReturning(X_BODY);
    const r = await readPublicMetrics("x", "1856789012345678901", { env: { X_BEARER_TOKEN: "t" }, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.metrics).toMatchObject({ views: 4200, reach: 9000, likes: 50, comments: 4, shares: 5, saves: 6 });
    expect(r).toMatchObject({ author_id: "42", author_label: "@placemedia", published_at: "2026-11-20T08:00:00.000Z" });
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer t");
  });

  it("fällt ohne Video auf Impressionen zurück", async () => {
    const body = { data: { ...X_BODY.data, attachments: undefined }, includes: {} };
    const r = await readPublicMetrics("x", "1856789012345678901", { env: { X_BEARER_TOKEN: "t" }, fetchImpl: fetchReturning(body) as unknown as typeof fetch });
    expect(r.ok && r.metrics.views).toBe(9000);
  });

  it("fragt dieselbe ID innerhalb einer Stunde nur einmal ab", async () => {
    let now = 1_000_000;
    const fetchImpl = fetchReturning(X_BODY);
    const opts = { env: { X_BEARER_TOKEN: "t" }, fetchImpl: fetchImpl as unknown as typeof fetch, now: () => now };
    await readPublicMetrics("x", "1856789012345678901", opts);
    const second = await readPublicMetrics("x", "1856789012345678901", opts);
    expect(second.ok && second.cached).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    now += X_CACHE_TTL_MS + 1;
    await readPublicMetrics("x", "1856789012345678901", opts);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("meldet nicht gefunden bei 404", async () => {
    const r = await readPublicMetrics("x", "1", { env: { X_BEARER_TOKEN: "t" }, fetchImpl: fetchReturning({}, 404) as unknown as typeof fetch });
    expect(r).toMatchObject({ ok: false, error: "nicht_gefunden" });
  });

  it("meldet nicht gefunden, wenn X nur errors liefert", async () => {
    const r = await readPublicMetrics("x", "1", { env: { X_BEARER_TOKEN: "t" }, fetchImpl: fetchReturning({ errors: [{ title: "Not Found Error" }] }) as unknown as typeof fetch });
    expect(r).toMatchObject({ ok: false, error: "nicht_gefunden" });
  });
});

describe("readPublicMetrics ohne öffentliche Schnittstelle", () => {
  it.each(["tiktok", "instagram", "linkedin"] as const)("%s braucht ein verbundenes Konto", async (platform) => {
    const fetchImpl = vi.fn();
    const r = await readPublicMetrics(platform, "abc", { env: {}, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(r).toMatchObject({ ok: false, error: "nicht_verbunden" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("X-Cache (R1-20)", () => {
  it("hält höchstens X_CACHE_MAX IDs und wirft die am längsten ungelesene zuerst hinaus", async () => {
    clearPublicMetricsCache();
    const fetchImpl = vi.fn(async (url: string) => {
      const id = url.split("/").pop()!.split("?")[0];
      return new Response(JSON.stringify({ data: { id, author_id: "1", public_metrics: { like_count: 1 } } }), { status: 200 });
    });
    const opts = { env: { X_BEARER_TOKEN: "t", X_DAILY_READ_CAP: "100000" }, fetchImpl: fetchImpl as unknown as typeof fetch, now: () => 1_000 };
    for (let i = 1; i <= X_CACHE_MAX; i++) await readPublicMetrics("x", String(i), opts);
    expect(publicMetricsCacheSize()).toBe(X_CACHE_MAX);
    const hit = await readPublicMetrics("x", "1", opts);
    expect(hit.ok && hit.cached).toBe(true); // Treffer: 1 rückt ans Ende, 2 ist jetzt die älteste
    await readPublicMetrics("x", String(X_CACHE_MAX + 1), opts);
    expect(publicMetricsCacheSize()).toBe(X_CACHE_MAX);
    const calls = fetchImpl.mock.calls.length;
    const one = await readPublicMetrics("x", "1", opts);
    expect(one.ok && one.cached).toBe(true); // zuletzt gelesen, also noch da
    await readPublicMetrics("x", "2", opts); // war die älteste, ist herausgefallen
    expect(fetchImpl.mock.calls.length).toBe(calls + 1);
  });
});

describe("publicReaderConfigured", () => {
  it("kennt nur YouTube und X und verlangt einen nicht leeren Schlüssel", () => {
    expect(publicReaderConfigured("youtube", { YOUTUBE_API_KEY: "k" })).toBe(true);
    expect(publicReaderConfigured("youtube", { YOUTUBE_API_KEY: "  " })).toBe(false);
    expect(publicReaderConfigured("x", {})).toBe(false);
    expect(publicReaderConfigured("tiktok", { YOUTUBE_API_KEY: "k", X_BEARER_TOKEN: "t" })).toBe(false);
    expect(configuredReaderPlatforms({ X_BEARER_TOKEN: "t" })).toEqual(["x"]);
    expect(configuredReaderPlatforms({})).toEqual([]);
  });
});
