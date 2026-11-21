/* Linktest: die Prüfungen hinter POST /api/v1/links/test. Netz und Datenbank sind ersetzt, geprüft wird,
 * was aus welchem Teilergebnis folgt. Die Hinweise sind Oberflächentext: kurz, deutsch, ohne Gedankenstrich. */

import { describe, expect, it, vi } from "vitest";
import { ENDPOINTS, requestSchema, resolveRef } from "@/lib/api/openapi";
import { validate } from "@/lib/api/validate";
import { clipFormatHint, linkCheckSummary, planLinkPublication, probeOembed, runLinkCheck, type LinkCheckDeps } from "@/lib/publishing/link-check";
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
    expect(r.hinweise).toContain("Dieser Beitrag ist schon eingetragen.");
  });

  it("gibt ohne Schlüssel den Hinweis weiter, prüft per oEmbed und plant keine Messung", async () => {
    const probe = vi.fn(async () => true);
    const r = await runLinkCheck(
      "https://youtu.be/dQw4w9WgXcQ",
      deps({ readPublic: async () => ({ ok: false, platform: "youtube", error: "nicht_konfiguriert", message: "Zahlen für YouTube sind noch nicht eingerichtet." }), probe }),
    );
    expect(r.checks).toMatchObject({ parsed: true, reachable: true, metrics_available: false, age_s: null });
    expect(r.metrics).toBeNull();
    expect(r.measurable).toBe(false);
    expect(r.hinweise).toEqual(["Zahlen für YouTube sind noch nicht eingerichtet."]);
    expect(r.hinweise.join(" ")).not.toMatch(/YOUTUBE_API_KEY|nicht bestätigt/);
    expect(probe).toHaveBeenCalledWith("youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    const out = planLinkPublication(r, { now: NOW });
    expect(out.ok && out.plan).toMatchObject({ measurable: false, next_snapshot_at: null });
    if (out.ok) expect(linkCheckSummary(r, out.plan).at(-1)).toBe("Zahlen für YouTube sind noch nicht eingerichtet, gemessen wird, sobald das erledigt ist");
    expect(linkCheckSummary(r).join(" ")).not.toContain("Tage lang gemessen");
  });

  it("lässt reachable ohne Beleg auf null und meldet dann nichts Unbestätigtes", async () => {
    const r = await runLinkCheck(
      "https://www.instagram.com/reel/C1abcDEFghi/",
      deps({ readPublic: async () => ({ ok: false, platform: "instagram", error: "nicht_verbunden", message: "Instagram gibt Messwerte nur über ein verbundenes Konto heraus." }), probe: async () => null }),
    );
    expect(r.checks.reachable).toBeNull();
    expect(r.measurable).toBe(false);
    expect(r.hinweise).toEqual(["Instagram gibt Messwerte nur über ein verbundenes Konto heraus."]);
  });

  it("meldet TikTok ohne Verbindung und sagt, wenn oEmbed den Beitrag nicht kennt", async () => {
    const r = await runLinkCheck(
      "https://www.tiktok.com/@placemedia/video/7301234567890123456",
      deps({ readPublic: async () => ({ ok: false, platform: "tiktok", error: "nicht_verbunden", message: "TikTok gibt Messwerte nur über ein verbundenes Konto heraus." }), probe: async () => false }),
    );
    expect(r.checks.reachable).toBe(false);
    expect(r.hinweise).toEqual(["TikTok gibt Messwerte nur über ein verbundenes Konto heraus.", "TikTok kennt diesen Beitrag nicht oder er ist nicht öffentlich."]);
  });

  it("fragt oEmbed nicht, wenn der Leser geantwortet hat, und gilt dann als messbar", async () => {
    const probe = vi.fn(async () => false);
    const r = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ probe }));
    expect(r.checks.reachable).toBe(true);
    expect(r.measurable).toBe(true);
    expect(probe).not.toHaveBeenCalled();
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

describe("planLinkPublication Messbarkeit und Restdauer", () => {
  it("plant ohne öffentlichen Leser und ohne Verbindung keine Messung", async () => {
    const check = await runLinkCheck(
      "https://www.tiktok.com/@placemedia/video/7301234567890123456",
      deps({ readPublic: async () => ({ ok: false, platform: "tiktok", error: "nicht_verbunden", message: "TikTok nur mit Verbindung." }) }),
    );
    const out = planLinkPublication(check, { now: NOW });
    expect(out.ok && out.plan).toMatchObject({ measurable: false, next_snapshot_at: null });
    if (out.ok) expect(linkCheckSummary(check, out.plan).at(-1)).toBe("Wird nicht gemessen: TikTok braucht ein verbundenes Konto");
  });

  it("sagt bei alten Beiträgen, wie lange wirklich noch gemessen wird", async () => {
    const old = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ readPublic: async () => youtubeOk({ published_at: "2026-10-01T12:00:00Z" }) }));
    const out = planLinkPublication(old, { now: NOW });
    expect(out.ok && out.plan.remaining_days).toBe(0);
    if (out.ok) expect(linkCheckSummary(old, out.plan).at(-1)).toBe("Wird einmal gemessen, der Beitrag ist älter als 30 Tage");
    const mid = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps({ readPublic: async () => youtubeOk({ published_at: "2026-11-11T12:00:00Z" }) }));
    const outMid = planLinkPublication(mid, { now: NOW });
    if (outMid.ok) expect(linkCheckSummary(mid, outMid.plan).at(-1)).toBe("Wird noch 20 Tage lang gemessen");
  });

  it("misst frische Beiträge die volle Dauer", async () => {
    const check = await runLinkCheck("https://youtu.be/dQw4w9WgXcQ", deps());
    const out = planLinkPublication(check, { now: NOW });
    if (out.ok) expect(linkCheckSummary(check, out.plan).at(-1)).toBe("Wird 30 Tage lang gemessen");
    expect(out.ok && out.plan.measurable).toBe(true);
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

describe("probeOembed", () => {
  const answering = (status: number) => vi.fn(async () => new Response("{}", { status }));

  it("belegt Existenz nur über oEmbed bei YouTube und TikTok", async () => {
    const ok = answering(200);
    expect(await probeOembed("youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", ok as unknown as typeof fetch)).toBe(true);
    expect(String((ok.mock.calls[0] as unknown[])[0])).toMatch(/^https:\/\/www\.youtube\.com\/oembed\?url=/);
    expect(await probeOembed("tiktok", "https://www.tiktok.com/@a/video/1", answering(404) as unknown as typeof fetch)).toBe(false);
    expect(await probeOembed("tiktok", "https://www.tiktok.com/@a/video/1", answering(400) as unknown as typeof fetch)).toBe(false);
  });

  it("gibt null für andere Antworten, Netzfehler und Plattformen ohne oEmbed", async () => {
    expect(await probeOembed("youtube", "https://www.youtube.com/watch?v=x", answering(401) as unknown as typeof fetch)).toBeNull();
    expect(await probeOembed("youtube", "https://www.youtube.com/watch?v=x", (async () => { throw new Error("weg"); }) as unknown as typeof fetch)).toBeNull();
    const never = vi.fn();
    expect(await probeOembed("instagram", "https://www.instagram.com/reel/x/", never as unknown as typeof fetch)).toBeNull();
    expect(never).not.toHaveBeenCalled();
  });
});
