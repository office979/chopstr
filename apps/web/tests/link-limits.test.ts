/* Kosten und Missbrauch beim Linktest: eigenes Limit von 30 je Minute und Topf, getrennt vom allgemeinen
 * Limit, und ein Tagesdeckel für echte X-Abrufe (Cache-Treffer zählen nicht). */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { consumeLinkRateLimit, consumeRateLimit, LINK_RATE_LIMIT_PER_MIN, linkRateLimitMessage } from "@/lib/api/rate-limit";
import { clearPublicMetricsCache, readPublicMetrics, X_DAILY_READ_CAP_DEFAULT, xDailyReadCap } from "@/lib/publishing/public-metrics";

beforeEach(() => {
  globalThis.__chopstrApiRateLimit = undefined;
  clearPublicMetricsCache();
});

describe("Linkprüfungen je Minute", () => {
  it("erlaubt 30 je Topf und sperrt danach, ohne andere Töpfe oder das allgemeine Limit zu treffen", () => {
    for (let i = 0; i < LINK_RATE_LIMIT_PER_MIN; i++) expect(consumeLinkRateLimit("key-a").allowed).toBe(true);
    const blocked = consumeLinkRateLimit("key-a");
    expect(blocked).toMatchObject({ allowed: false, limit: 30, remaining: 0 });
    expect(linkRateLimitMessage(blocked)).toMatch(/^Zu viele Linkprüfungen: höchstens 30 pro Minute/);
    expect(consumeLinkRateLimit("ws:ws-1").allowed).toBe(true);
    expect(consumeRateLimit("key-a").allowed).toBe(true);
  });
});

describe("Tagesdeckel für X", () => {
  const tweet = (id: string) => ({ data: { id, author_id: "1", created_at: "2026-11-20T08:00:00Z", public_metrics: { like_count: 1, impression_count: 10 } } });

  it("liest den Deckel aus X_DAILY_READ_CAP, leer oder ungültig gilt 500", () => {
    expect(xDailyReadCap({})).toBe(X_DAILY_READ_CAP_DEFAULT);
    expect(xDailyReadCap({ X_DAILY_READ_CAP: "" })).toBe(500);
    expect(xDailyReadCap({ X_DAILY_READ_CAP: "abc" })).toBe(500);
    expect(xDailyReadCap({ X_DAILY_READ_CAP: "2" })).toBe(2);
  });

  it("stoppt nach dem Deckel echte Abrufe, Cache-Treffer gehen weiter, am nächsten Tag zählt es neu", async () => {
    let now = Date.parse("2026-11-21T10:00:00Z");
    const fetchImpl = vi.fn(async (url: string) => new Response(JSON.stringify(tweet(url.split("/").pop()!.split("?")[0])), { status: 200 }));
    const opts = { env: { X_BEARER_TOKEN: "t", X_DAILY_READ_CAP: "2" }, fetchImpl: fetchImpl as unknown as typeof fetch, now: () => now };
    expect((await readPublicMetrics("x", "1", opts)).ok).toBe(true);
    expect((await readPublicMetrics("x", "2", opts)).ok).toBe(true);
    const third = await readPublicMetrics("x", "3", opts);
    expect(third).toMatchObject({ ok: false, error: "fehler", message: "Für heute sind keine Abrufe bei X mehr frei, morgen geht es weiter." });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect((await readPublicMetrics("x", "1", opts)).ok).toBe(true); // Cache
    now = Date.parse("2026-11-22T00:00:01Z");
    expect((await readPublicMetrics("x", "3", opts)).ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });
});
