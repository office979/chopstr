/* Linktest: die Prüfungen hinter POST /api/v1/links/test. Netz und Datenbank sind ersetzt, geprüft wird,
 * was aus welchem Teilergebnis folgt. Die Hinweise sind Oberflächentext: kurz, deutsch, ohne Gedankenstrich. */

import { describe, expect, it, vi } from "vitest";
import { ENDPOINTS, requestSchema, resolveRef } from "@/lib/api/openapi";
import { validate } from "@/lib/api/validate";
import { clipFormatHint, linkCheckSummary, planLinkPublication, runLinkCheck, type LinkCheckDeps } from "@/lib/publishing/link-check";
import { parsePostUrl } from "@/lib/publishing/links";
import { emptyPublicMetrics, type PublicMetricsResult } from "@/lib/publishing/public-metrics";

const NOW = Date.parse("2026-11-21T12:00:00Z");

function youtubeOk(over: Partial<Extract<PublicMetricsResult, { ok: true }>> = {}): PublicMetricsResult {
  return {
    ok: true,
    platform: "youtube",
    metrics: { ...emptyPublicMetrics(), views: 1234, likes: 56, comments: 7 },
    source: "public_api",
    published_at: "2026-11-21T10:30:00Z",
    author_id: "UC123",
    author_label: "PLACEMedia",
    raw: {},
    ...over,
  };
}

function deps(over: Partial<LinkCheckDeps> = {}): LinkCheckDeps {
  return {
    resolve: async (url) => parsePostUrl(url),
    readPublic: async () => youtubeOk(),
    listConnections: async () => [],
    findDuplicate: async () => null,
    probe: async () => true,
    now: () => NOW,
    ...over,
  };
}

const DASHES = /[–—]| - /;

describe("runLinkCheck", () => {
  it("liefert Prüfungen, Zahlen und Alter für ein öffentliches Short", async () => {
    const r = await runLinkCheck("https://youtube.com/shorts/dQw4w9WgXcQ", deps());
    expect(r).toMatchObject({ platform: "youtube", external_id: "dQw4w9WgXcQ", normalized_url: "https://www.youtube.com/shorts/dQw4w9WgXcQ" });
    expect(r.checks).toEqual({ parsed: true, reachable: true, owned_by_connection: false, duplicate_publication_id: null, age_s: 5400, metrics_available: true });
    expect(r.metrics).toMatchObject({ views: 1234, likes: 56, comments: 7, shares: null, source: "public_api" });
    expect(r.hinweise).toContain("Kein verbundenes Konto, Messwerte kommen aus öffentlichen Daten.");
  });

  it("erkennt den Besitz über die Kanal-ID einer verbundenen Verbindung", async () => {
    const r = await runLinkCheck(
      "https://youtu.be/dQw4w9WgXcQ",
      deps({ listConnections: async () => [{ id: "conn-1", platform: "youtube", account_label: "PLACEMedia Kanal", external_account_id: "UC123", status: "connected" }] }),
    );
    expect(r.checks.owned_by_connection).toBe(true);
    expect(r.connection_id).toBe("conn-1");
    expect(r.hinweise[0]).toContain("PLACEMedia Kanal");
  });

  it("zählt getrennte Verbindungen nicht als Besitz", async () => {
    const r = await runLinkCheck(
      "https://youtu.be/dQw4w9WgXcQ",
      deps({ listConnections: async () => [{ id: "conn-1", platform: "youtube", account_label: "Alt", external_account_id: "UC123", status: "revoked" }] }),
    );
    expect(r.checks.owned_by_connection).toBe(false);
  });

  it("meldet Dubletten mit der vorhandenen Publikation", async () => {
    const r = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ findDuplicate: async () => ({ id: "pub-9" }) }));
    expect(r.checks.duplicate_publication_id).toBe("pub-9");
    expect(r.hinweise).toContain("Dieser Beitrag wird schon verfolgt.");
  });

  it("gibt ohne Schlüssel den Hinweis weiter und prüft die Erreichbarkeit per Aufruf", async () => {
    const probe = vi.fn(async () => true);
    const r = await runLinkCheck(
      "https://youtu.be/dQw4w9WgXcQ",
      deps({ readPublic: async () => ({ ok: false, platform: "youtube", error: "nicht_konfiguriert", message: "YouTube ist nicht konfiguriert: YOUTUBE_API_KEY fehlt." }), probe }),
    );
    expect(r.checks).toMatchObject({ parsed: true, reachable: true, metrics_available: false, age_s: null });
    expect(r.metrics).toBeNull();
    expect(r.hinweise[0]).toContain("nicht konfiguriert");
    expect(probe).toHaveBeenCalledWith("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
  });

  it("meldet TikTok ohne Verbindung und fragt nach, ob der Beitrag öffentlich ist", async () => {
    const r = await runLinkCheck(
      "https://www.tiktok.com/@placemedia/video/7301234567890123456",
      deps({ readPublic: async () => ({ ok: false, platform: "tiktok", error: "nicht_verbunden", message: "TikTok gibt Messwerte nur über ein verbundenes Konto heraus." }), probe: async () => false }),
    );
    expect(r.checks.reachable).toBe(false);
    expect(r.hinweise).toEqual(["TikTok gibt Messwerte nur über ein verbundenes Konto heraus.", "TikTok hat den Link nicht bestätigt. Ist der Beitrag öffentlich?"]);
  });

  it("ruft bei nicht gefundenen Beiträgen keinen zweiten Aufruf ab", async () => {
    const probe = vi.fn(async () => true);
    const r = await runLinkCheck("https://x.com/a/status/1856789012345678901", deps({ readPublic: async () => ({ ok: false, platform: "x", error: "nicht_gefunden", message: "X kennt diesen Beitrag nicht." }), probe }));
    expect(r.checks.reachable).toBe(false);
    expect(probe).not.toHaveBeenCalled();
  });

  it("gibt bei ungültigen Links nur parsed false und die Meldung zurück", async () => {
    const readPublic = vi.fn();
    const r = await runLinkCheck("https://vimeo.com/1", deps({ readPublic }));
    expect(r.checks.parsed).toBe(false);
    expect(r.platform).toBeNull();
    expect(r.hinweise[0]).toContain("nicht unterstützt");
    expect(readPublic).not.toHaveBeenCalled();
  });

  it("bittet bei nicht aufgelösten Kurzlinks um den vollständigen Link", async () => {
    const r = await runLinkCheck("https://vm.tiktok.com/ZMabc123/", deps());
    expect(r.kind).toBe("short_link");
    expect(r.hinweise[0]).toContain("vollständigen Link");
  });

  it("übersteht ausfallende Datenbankabfragen", async () => {
    const r = await runLinkCheck(
      "https://youtu.be/dQw4w9WgXcQ",
      deps({
        listConnections: async () => {
          throw new Error("db weg");
        },
        findDuplicate: async () => {
          throw new Error("db weg");
        },
      }),
    );
    expect(r.checks.parsed).toBe(true);
    expect(r.checks.duplicate_publication_id).toBeNull();
  });

  it("schreibt Hinweise ohne Gedankenstriche", async () => {
    const results = await Promise.all([
      runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps()),
      runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ findDuplicate: async () => ({ id: "p" }) })),
      runLinkCheck("https://vm.tiktok.com/ZMabc123/", deps()),
      runLinkCheck("kein link", deps()),
    ]);
    for (const r of results) for (const h of r.hinweise) expect(h).not.toMatch(DASHES);
  });
});

describe("Body-Schema LinkTest", () => {
  const check = (body: unknown) => validate(body, requestSchema("LinkTest"), "body", [], resolveRef);
  it("verlangt url", () => {
    expect(check({}).map((i) => i.path)).toContain("body.url");
  });
  it("lässt clip_id als UUID oder null zu", () => {
    expect(check({ url: "https://youtu.be/dQw4w9WgXcQ", clip_id: null })).toEqual([]);
    expect(check({ url: "https://youtu.be/dQw4w9WgXcQ", clip_id: "nein" })).not.toEqual([]);
  });
  it("lehnt unbekannte Felder ab", () => {
    expect(check({ url: "x", extra: 1 })).not.toEqual([]);
  });
  it("ist im OpenAPI-Dokument eingetragen", () => {
    expect(ENDPOINTS.some((e) => e.path === "/links/test" && e.method === "post" && e.requestBody === "LinkTest")).toBe(true);
  });
});

describe("planLinkPublication", () => {
  it("misst 30 Tage ab der Veröffentlichung laut Plattform, erste Messung sofort", async () => {
    const check = await runLinkCheck("https://youtube.com/shorts/dQw4w9WgXcQ", deps());
    const out = planLinkPublication(check, { now: NOW });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.plan).toMatchObject({
      platform: "youtube",
      external_id: "dQw4w9WgXcQ",
      external_url: "https://www.youtube.com/shorts/dQw4w9WgXcQ",
      published_at: "2026-11-21T10:30:00.000Z",
      tracking_until: "2026-12-21T10:30:00.000Z",
      tracking_days: 30,
      next_snapshot_at: "2026-11-21T12:00:00.000Z",
      connection_id: null,
    });
    expect(out.plan.link_check.checks.parsed).toBe(true);
  });

  it("nimmt jetzt, wenn die Plattform keinen Zeitpunkt nennt", async () => {
    const check = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ readPublic: async () => ({ ok: false, platform: "youtube", error: "nicht_konfiguriert", message: "x" }) }));
    const out = planLinkPublication(check, { now: NOW, trackDays: 7 });
    expect(out.ok && out.plan.published_at).toBe("2026-11-21T12:00:00.000Z");
    expect(out.ok && out.plan.tracking_until).toBe("2026-11-28T12:00:00.000Z");
  });

  it("begrenzt track_days auf 1 bis 90", async () => {
    const check = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps());
    expect(planLinkPublication(check, { now: NOW, trackDays: 500 }).ok && (planLinkPublication(check, { now: NOW, trackDays: 500 }) as { plan: { tracking_days: number } }).plan.tracking_days).toBe(90);
    expect((planLinkPublication(check, { now: NOW, trackDays: 0 }) as { plan: { tracking_days: number } }).plan.tracking_days).toBe(1);
  });

  it("lehnt Dubletten mit 409 ab", async () => {
    const check = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ findDuplicate: async () => ({ id: "pub-1" }) }));
    expect(planLinkPublication(check, { now: NOW })).toMatchObject({ ok: false, status: 409, code: "link_duplicate", duplicate_publication_id: "pub-1" });
  });

  it("lehnt ungültige Links und Kurzlinks mit 400 ab", async () => {
    expect(planLinkPublication(await runLinkCheck("kein link", deps()), { now: NOW })).toMatchObject({ ok: false, status: 400, code: "link_invalid" });
    expect(planLinkPublication(await runLinkCheck("https://vm.tiktok.com/ZMabc123/", deps()), { now: NOW })).toMatchObject({ ok: false, status: 400, code: "link_unresolved" });
  });

  it("übernimmt die Verbindung, wenn der Beitrag ihr gehört", async () => {
    const check = await runLinkCheck(
      "https://youtu.be/dQw4w9WgXcQ",
      deps({ listConnections: async () => [{ id: "conn-1", platform: "youtube", account_label: "K", external_account_id: "UC123", status: "connected" }] }),
    );
    const out = planLinkPublication(check, { now: NOW });
    expect(out.ok && out.plan.connection_id).toBe("conn-1");
  });
});

describe("linkCheckSummary", () => {
  it("fasst das Ergebnis in Sätzen ohne Gedankenstrich zusammen", async () => {
    const lines = linkCheckSummary(await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps()));
    expect(lines).toEqual(["Link erkannt: YouTube", "Kein verbundenes Konto", "Wird 30 Tage lang gemessen"]);
    for (const l of lines) expect(l).not.toMatch(DASHES);
  });
  it("nennt bei ungültigen Links nur den Grund", async () => {
    expect(linkCheckSummary(await runLinkCheck("kein link", deps()))).toEqual(["Das ist kein gültiger Link."]);
  });
});

describe("Body-Schema LinkRegister", () => {
  const check = (body: unknown) => validate(body, requestSchema("LinkRegister"), "body", [], resolveRef);
  it("lässt track_days zwischen 1 und 90 zu", () => {
    expect(check({ url: "https://youtu.be/dQw4w9WgXcQ", track_days: 30 })).toEqual([]);
    expect(check({ url: "https://youtu.be/dQw4w9WgXcQ", track_days: 91 })).not.toEqual([]);
    expect(check({ url: "https://youtu.be/dQw4w9WgXcQ", track_days: 1.5 })).not.toEqual([]);
  });
  it("ist im OpenAPI-Dokument eingetragen", () => {
    expect(ENDPOINTS.some((e) => e.path === "/clips/{id}/links" && e.scope === "publish")).toBe(true);
  });
});

describe("clipFormatHint", () => {
  it("schweigt, wenn Format und Link passen", () => {
    expect(clipFormatHint("youtube", "shorts")).toBeNull();
    expect(clipFormatHint("instagram", "reels")).toBeNull();
  });
  it("weist auf ein anderes Format hin", () => {
    expect(clipFormatHint("tiktok", "shorts")).toBe("Der Clip ist für YouTube Shorts geschnitten, der Link führt zu TikTok.");
  });
  it("lässt X zu jedem Format zu", () => {
    expect(clipFormatHint("x", "tiktok")).toBeNull();
  });
});
