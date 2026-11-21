/* Lese-API für Performance: Ordnung der Messreihe, abgeleitete Werte und der Plausibilitätshinweis.
 * Rein, ohne Datenbank: die Zeilen kommen so, wie das Repository sie liefert. */

import { describe, expect, it } from "vitest";
import {
  buildClipPerformance,
  buildPublicationMetrics,
  detectAnomaly,
  engagementRate,
  latestSnapshot,
  parseSeriesQuery,
  publicSnapshotError,
  serializeSnapshot,
} from "@/lib/publishing/performance";
import { ENDPOINTS } from "@/lib/api/openapi";
import { serializePublication } from "@/lib/api/serializers";
import type { MetricSnapshot, Publication, WindowFeedback } from "@/lib/repo/types-api";

function snap(over: Partial<MetricSnapshot> = {}): MetricSnapshot {
  return {
    id: "s",
    publication_id: "p1",
    fetched_at: "2026-11-21T10:00:00.000Z",
    age_s: 3600,
    source: "public_api",
    views: 100,
    engaged_views: null,
    likes: 10,
    comments: 2,
    shares: null,
    saves: null,
    follows: null,
    reach: null,
    avg_watch_time_s: null,
    skip_rate: null,
    retention_curve: null,
    error: null,
    ...over,
  };
}

function win(over: Partial<WindowFeedback> = {}): WindowFeedback {
  return {
    publication_id: "p1",
    metric_window: "6h",
    views: 500,
    likes: 20,
    comments: 5,
    shares: 1,
    saves: 4,
    follows: 3,
    follows_per_1k: 6,
    saves_per_1k: 8,
    outlier_score: 1.2,
    reward: 0.9,
    fetched_at: "2026-11-21T16:00:00.000Z",
    ...over,
  };
}

describe("engagementRate", () => {
  it("teilt Interaktionen durch Aufrufe", () => {
    expect(engagementRate({ views: 1000, likes: 40, comments: 5, shares: 3, saves: 2 })).toBe(0.05);
  });
  it("zählt fehlende Anteile als 0", () => {
    expect(engagementRate({ views: 100, likes: 10, comments: null, shares: null, saves: null })).toBe(0.1);
  });
  it("gibt ohne Aufrufe oder ohne Interaktionszahlen null", () => {
    expect(engagementRate({ views: 0, likes: 1, comments: 0, shares: 0, saves: 0 })).toBeNull();
    expect(engagementRate({ views: null, likes: 1, comments: 0, shares: 0, saves: 0 })).toBeNull();
    expect(engagementRate({ views: 100, likes: null, comments: null, shares: null, saves: null })).toBeNull();
  });
});

describe("detectAnomaly", () => {
  it("schlägt an bei mehr als fünffachem Sprung unter 0,2 % Interaktion", () => {
    const series = [snap({ fetched_at: "2026-11-21T10:00:00Z", views: 1000, likes: 50 }), snap({ fetched_at: "2026-11-21T11:00:00Z", views: 10_000, likes: 10, comments: 0 })].map(serializeSnapshot);
    expect(detectAnomaly(series)).toEqual({ flagged: true, rule: "sprung_ohne_interaktion", between: { from: "2026-11-21T10:00:00Z", to: "2026-11-21T11:00:00Z" } });
  });
  it("schweigt bei starkem Wachstum mit normaler Interaktion", () => {
    const series = [snap({ views: 1000 }), snap({ fetched_at: "2026-11-21T11:00:00Z", views: 10_000, likes: 500 })].map(serializeSnapshot);
    expect(detectAnomaly(series).flagged).toBe(false);
  });
  it("übergeht fehlgeschlagene Messungen", () => {
    const series = [snap({ views: 1000 }), snap({ fetched_at: "2026-11-21T10:30:00Z", views: null, likes: null, comments: null, error: "x" }), snap({ fetched_at: "2026-11-21T11:00:00Z", views: 4000, likes: 200 })].map(serializeSnapshot);
    expect(detectAnomaly(series).flagged).toBe(false);
  });
});

describe("latestSnapshot", () => {
  it("nimmt die jüngste Messung mit Zahlen", () => {
    const latest = latestSnapshot([
      snap({ fetched_at: "2026-11-21T10:00:00Z", views: 100 }),
      snap({ fetched_at: "2026-11-21T12:00:00Z", views: 300 }),
      snap({ fetched_at: "2026-11-21T13:00:00Z", views: null, likes: null, comments: null, error: "YouTube ist nicht konfiguriert" }),
    ]);
    expect(latest?.views).toBe(300);
    expect(latest?.engagement_rate).toBe(0.04);
  });
  it("gibt ohne Messung null", () => {
    expect(latestSnapshot([])).toBeNull();
  });
});

describe("parseSeriesQuery", () => {
  it("liest since und limit", () => {
    expect(parseSeriesQuery(new URLSearchParams("since=2026-11-21T00:00:00Z&limit=10"))).toEqual({ since: "2026-11-21T00:00:00.000Z", limit: 10 });
    expect(parseSeriesQuery(new URLSearchParams(""))).toEqual({ since: null, limit: 200 });
  });
  it("meldet ungültige Werte auf Deutsch", () => {
    expect(parseSeriesQuery(new URLSearchParams("since=gestern"))).toEqual({ error: "since muss ein Zeitpunkt nach ISO 8601 sein." });
    expect(parseSeriesQuery(new URLSearchParams("limit=0"))).toHaveProperty("error");
    expect(parseSeriesQuery(new URLSearchParams("limit=1001"))).toHaveProperty("error");
    expect(parseSeriesQuery(new URLSearchParams("limit=2.5"))).toHaveProperty("error");
  });
});

describe("buildPublicationMetrics", () => {
  const snaps = [
    snap({ id: "a", fetched_at: "2026-11-21T12:00:00.000Z", views: 300 }),
    snap({ id: "b", fetched_at: "2026-11-21T10:00:00.000Z", views: 100 }),
    snap({ id: "c", fetched_at: "2026-11-21T11:00:00.000Z", views: 200 }),
  ];
  const fb = [win({ metric_window: "48h" }), win({ metric_window: "6h" }), win({ publication_id: "anders", metric_window: "7d" })];

  it("ordnet die Reihe chronologisch und die Fenster nach Alter", () => {
    const out = buildPublicationMetrics("p1", snaps, fb);
    expect(out.series.map((s) => s.views)).toEqual([100, 200, 300]);
    expect(out.windows.map((w) => w.window)).toEqual(["6h", "48h"]);
    expect(out.windows[0]).toMatchObject({ follows_per_1k: 6, saves_per_1k: 8, outlier_score: 1.2, reward: 0.9, engagement_rate: 0.06 });
    expect(out.latest?.views).toBe(300);
    expect(out.series_total).toBe(3);
    expect(out.anomaly.flagged).toBe(false);
  });

  it("filtert mit since und behält bei limit die jüngsten", () => {
    const out = buildPublicationMetrics("p1", snaps, fb, { since: "2026-11-21T10:30:00.000Z", limit: 1 });
    expect(out.series.map((s) => s.views)).toEqual([300]);
    expect(out.series_total).toBe(2);
    expect(out.latest?.views).toBe(300);
  });
});

describe("buildClipPerformance", () => {
  it("liefert je Publikation die neuesten Zahlen und summiert die Aufrufe", () => {
    const out = buildClipPerformance(
      [{ id: "p1" }, { id: "p2" }, { id: "p3" }],
      [snap({ publication_id: "p1", views: 1000 })],
      [win({ publication_id: "p2", metric_window: "7d", views: 250, reward: 1.4 })],
    );
    expect(out.publications.map((r) => r.latest?.views ?? null)).toEqual([1000, null, null]);
    expect(out.publications[1].reward).toBe(1.4);
    expect(out.totals).toEqual({ publications: 3, views: 1250 });
  });
  it("gibt ohne Zahlen views null statt 0", () => {
    expect(buildClipPerformance([{ id: "p1" }], [], []).totals.views).toBeNull();
  });
});

describe("serializePublication", () => {
  const pub = { id: "p1", clip_id: "c", status: "manual", platform: "youtube", tracking: "link" } as unknown as Publication;
  it("bettet metrics_latest nur auf Wunsch ein", () => {
    expect(serializePublication(pub)).not.toHaveProperty("metrics_latest");
    expect(serializePublication(pub, { metrics_latest: null })).toHaveProperty("metrics_latest", null);
    expect(serializePublication(pub).tracking).toBe("link");
  });
});

describe("OpenAPI", () => {
  it("kennt die Lese-Routen mit Scope read", () => {
    for (const path of ["/publications/{id}/metrics", "/clips/{id}/performance"]) {
      expect(ENDPOINTS.find((e) => e.path === path && e.method === "get")?.scope).toBe("read");
    }
  });
});

describe("publicSnapshotError", () => {
  it("zeigt nur Code und feste Meldung, nie den internen Text", () => {
    const e = publicSnapshotError("plattform_fehler: YouTube hat gerade nicht richtig geantwortet. YouTube antwortete mit 403: quotaExceeded");
    expect(e).toEqual({ code: "plattform_fehler", message: "Die Plattform hat nicht richtig geantwortet." });
    expect(JSON.stringify(serializeSnapshot(snap({ error: "konfiguration: RuntimeError: INTERNAL_API_SECRET ist nicht gesetzt" })).error)).not.toContain("INTERNAL_API_SECRET");
  });

  it("macht aus alten Zeilen ohne Code und aus unbekannten Codes einen allgemeinen Fehler", () => {
    expect(publicSnapshotError("Web-App nicht erreichbar: RuntimeError: INTERNAL_API_SECRET ist nicht gesetzt")).toEqual({ code: "fehler", message: "Die Messung ist fehlgeschlagen." });
    expect(publicSnapshotError("quatsch: x")?.code).toBe("fehler");
    expect(publicSnapshotError(null)).toBeNull();
  });
});
