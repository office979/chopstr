/* Linkparser für Plattform-URLs: aus einem eingefügten Link werden Plattform, ID und eine saubere URL.
 * Tracking-Parameter dürfen nie in der gespeicherten URL landen, sonst gilt derselbe Beitrag beim
 * nächsten Einfügen als neuer. */

import { describe, expect, it, vi } from "vitest";
import { isLinkError, parsePostUrl, resolvePostUrl, type ParseResult } from "@/lib/publishing/links";

function ok(r: ParseResult) {
  if (isLinkError(r)) throw new Error(`erwartet Treffer, bekam ${r.error}`);
  return r;
}

describe("parsePostUrl YouTube", () => {
  it("erkennt Shorts", () => {
    expect(ok(parsePostUrl("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share"))).toEqual({
      platform: "youtube",
      externalId: "dQw4w9WgXcQ",
      normalizedUrl: "https://www.youtube.com/shorts/dQw4w9WgXcQ",
      kind: "short",
    });
  });
  it("erkennt youtu.be mit si-Parameter", () => {
    const r = ok(parsePostUrl("https://youtu.be/dQw4w9WgXcQ?si=abcDEF123"));
    expect(r.externalId).toBe("dQw4w9WgXcQ");
    expect(r.normalizedUrl).toBe("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
  });
  it("erkennt watch?v= zwischen anderen Parametern", () => {
    const r = ok(parsePostUrl("https://m.youtube.com/watch?list=PL1&v=dQw4w9WgXcQ&t=42s&utm_source=x"));
    expect(r.externalId).toBe("dQw4w9WgXcQ");
    expect(r.normalizedUrl).not.toContain("utm_");
  });
  it("nimmt Links ohne Schema an", () => {
    expect(ok(parsePostUrl("youtube.com/shorts/dQw4w9WgXcQ")).kind).toBe("short");
  });
  it("lehnt Kanal-Links ab", () => {
    expect(parsePostUrl("https://www.youtube.com/@chopstr")).toMatchObject({ error: "keine_id" });
  });
  it("lehnt zu kurze IDs ab", () => {
    expect(parsePostUrl("https://youtu.be/abc")).toMatchObject({ error: "keine_id" });
  });
});

describe("parsePostUrl TikTok", () => {
  it("erkennt @user/video/ID", () => {
    expect(ok(parsePostUrl("https://www.tiktok.com/@placemedia/video/7301234567890123456?is_from_webapp=1&sender_device=pc"))).toEqual({
      platform: "tiktok",
      externalId: "7301234567890123456",
      normalizedUrl: "https://www.tiktok.com/@placemedia/video/7301234567890123456",
      kind: "video",
    });
  });
  it("erkennt mobile Links", () => {
    expect(ok(parsePostUrl("https://m.tiktok.com/@user.name/video/7301234567890123456")).externalId).toBe("7301234567890123456");
  });
  it("erkennt vm.tiktok.com als Kurzlink", () => {
    expect(ok(parsePostUrl("https://vm.tiktok.com/ZMabc123/")).kind).toBe("short_link");
  });
  it("erkennt vt.tiktok.com als Kurzlink", () => {
    expect(ok(parsePostUrl("https://vt.tiktok.com/ZSxyz789/")).kind).toBe("short_link");
  });
  it("lehnt Profil-Links ab", () => {
    expect(parsePostUrl("https://www.tiktok.com/@placemedia")).toMatchObject({ error: "keine_id" });
  });
});

describe("parsePostUrl Instagram", () => {
  it("erkennt Reels", () => {
    expect(ok(parsePostUrl("https://www.instagram.com/reel/C1a2B3c4D5e/?igsh=MTIzNDU2"))).toEqual({
      platform: "instagram",
      externalId: "C1a2B3c4D5e",
      normalizedUrl: "https://www.instagram.com/reel/C1a2B3c4D5e/",
      kind: "reel",
    });
  });
  it("erkennt Beiträge unter /p/", () => {
    expect(ok(parsePostUrl("https://instagram.com/p/C1a2B3c4D5e")).kind).toBe("post");
  });
  it("erkennt Reels mit Profil-Präfix und /reels/", () => {
    expect(ok(parsePostUrl("https://www.instagram.com/placemedia/reels/C1a2B3c4D5e/")).externalId).toBe("C1a2B3c4D5e");
  });
  it("lehnt Profil-Links ab", () => {
    expect(parsePostUrl("https://www.instagram.com/placemedia/")).toMatchObject({ error: "keine_id" });
  });
});

describe("parsePostUrl X", () => {
  it("erkennt x.com/user/status/ID", () => {
    expect(ok(parsePostUrl("https://x.com/placemedia/status/1856789012345678901?s=20&t=abc"))).toEqual({
      platform: "x",
      externalId: "1856789012345678901",
      normalizedUrl: "https://x.com/placemedia/status/1856789012345678901",
      kind: "status",
    });
  });
  it("erkennt twitter.com", () => {
    expect(ok(parsePostUrl("https://twitter.com/placemedia/status/1856789012345678901")).platform).toBe("x");
  });
  it("erkennt mobile.twitter.com und /i/web/status", () => {
    expect(ok(parsePostUrl("https://mobile.twitter.com/i/web/status/1856789012345678901")).externalId).toBe("1856789012345678901");
  });
  it("erkennt den Zusatz /video/1", () => {
    expect(ok(parsePostUrl("https://x.com/placemedia/status/1856789012345678901/video/1")).externalId).toBe("1856789012345678901");
  });
  it("lehnt Profil-Links ab", () => {
    expect(parsePostUrl("https://x.com/placemedia")).toMatchObject({ error: "keine_id" });
  });
});

describe("parsePostUrl LinkedIn", () => {
  it("erkennt /posts/ mit Aktivitäts-ID", () => {
    const r = ok(parsePostUrl("https://www.linkedin.com/posts/placemedia_clip-activity-7261234567890123456-AbCd?utm_source=share"));
    expect(r.externalId).toBe("urn:li:activity:7261234567890123456");
    expect(r.normalizedUrl).not.toContain("utm_");
  });
  it("erkennt feed/update mit URN", () => {
    expect(ok(parsePostUrl("https://www.linkedin.com/feed/update/urn:li:activity:7261234567890123456/")).externalId).toBe("urn:li:activity:7261234567890123456");
  });
  it("erkennt feed/update mit kodierter URN", () => {
    expect(ok(parsePostUrl("https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A7261234567890123456")).externalId).toBe("urn:li:share:7261234567890123456");
  });
  it("lehnt Profil-Links ab", () => {
    expect(parsePostUrl("https://www.linkedin.com/in/ferdinand")).toMatchObject({ error: "keine_id" });
  });
});

describe("parsePostUrl ungültige Eingaben", () => {
  it.each([
    ["", "leer"],
    ["   ", "leer"],
    ["kein link", "keine_url"],
    ["ftp://youtube.com/shorts/dQw4w9WgXcQ", "keine_url"],
    ["https://vimeo.com/123456", "unbekannte_plattform"],
    ["https://example.com/youtube.com/shorts/dQw4w9WgXcQ", "unbekannte_plattform"],
  ])("%j gibt %s", (input, code) => {
    expect(parsePostUrl(input)).toMatchObject({ error: code });
  });
  it("liefert bei null eine deutsche Meldung", () => {
    const r = parsePostUrl(null);
    expect(isLinkError(r) && r.message).toBe("Kein Link angegeben.");
  });
});

describe("resolvePostUrl", () => {
  it("folgt einer Weiterleitung bei TikTok-Kurzlinks", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 301, headers: { location: "https://www.tiktok.com/@placemedia/video/7301234567890123456?_r=1" } }));
    const r = ok(await resolvePostUrl("https://vm.tiktok.com/ZMabc123/", fetchImpl as unknown as typeof fetch));
    expect(r).toMatchObject({ kind: "video", externalId: "7301234567890123456" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("gibt den Kurzlink zurück, wenn die Auflösung scheitert", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("offline");
    });
    expect(ok(await resolvePostUrl("https://vm.tiktok.com/ZMabc123/", fetchImpl as unknown as typeof fetch)).kind).toBe("short_link");
  });
  it("ruft für normale Links kein Netz auf", async () => {
    const fetchImpl = vi.fn();
    await resolvePostUrl("https://youtu.be/dQw4w9WgXcQ", fetchImpl as unknown as typeof fetch);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("Runde 2 (R1-19)", () => {
  it("bildet fxtwitter, vxtwitter und fixupx auf x.com ab", () => {
    for (const host of ["fxtwitter.com", "vxtwitter.com", "fixupx.com", "www.fixvx.com"]) {
      const r = ok(parsePostUrl(`https://${host}/jack/status/1234567890123456789?s=20`));
      expect(r).toMatchObject({ platform: "x", externalId: "1234567890123456789", normalizedUrl: "https://x.com/jack/status/1234567890123456789" });
    }
  });
  it("nimmt X-IDs ab einer Ziffer", () => {
    expect(ok(parsePostUrl("https://x.com/jack/status/20")).externalId).toBe("20");
    expect(parsePostUrl("https://x.com/jack/status/12345678901234567890123456")).toMatchObject({ error: "keine_id" });
  });
  it("lehnt LinkedIn-Beiträge ohne Aktivitäts-ID ab, statt den Slug zu speichern", () => {
    expect(parsePostUrl("https://www.linkedin.com/posts/placemedia_ein-schoener-beitrag")).toMatchObject({ error: "keine_id" });
  });
});
