/* Zeilen in „Gepostet“: Plattform, Link, letzte Zahl mit Zeitpunkt und Status in Klartext. Die Texte sind
 * Oberfläche: deutsch, ohne Gedankenstrich, ohne Variablennamen. */

import { describe, expect, it } from "vitest";
import { publicationRow, shortStamp, type RowPublication } from "@/lib/publishing/publication-row";

const NOW = Date.parse("2026-11-21T15:00:00Z");

function pub(over: Partial<RowPublication> = {}): RowPublication {
  return {
    id: "p1",
    platform: "youtube",
    status: "manual",
    external_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    published_at: "2026-11-21T10:00:00Z",
    created_at: "2026-11-21T10:05:00Z",
    tracking: "link",
    tracking_until: "2026-12-21T10:00:00Z",
    next_snapshot_at: "2026-11-21T16:00:00Z",
    link_check: {},
    ...over,
  };
}

const ok = { fetched_at: "2026-11-21T17:00:00Z", views: 1234, likes: 56, error: null };

describe("publicationRow", () => {
  it("zeigt Zahl mit Stand in Wiener Zeit und bis wann gemessen wird", () => {
    const r = publicationRow(pub(), { latest: ok, last: ok }, undefined, NOW);
    expect(r).toMatchObject({ platform: "YouTube", url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ", number: "1.234 Aufrufe", numberAt: "Stand 21.11. 18:00", status: "Wird gemessen bis 21.12.", tone: "normal", canStop: true, canEnterNumbers: false });
  });

  it("meldet eine fehlgeschlagene letzte Messung und behält die letzte Zahl", () => {
    const failed = { fetched_at: "2026-11-21T18:00:00Z", views: null, likes: null, error: "plattform_fehler: x" };
    const r = publicationRow(pub(), { latest: ok, last: failed }, undefined, NOW);
    expect(r).toMatchObject({ number: "1.234 Aufrufe", status: "Letzte Messung fehlgeschlagen", tone: "attention" });
  });

  it("sagt ehrlich, wenn nicht gemessen wird, und bietet dann Zahlen von Hand an", () => {
    const tiktok = publicationRow(pub({ platform: "tiktok", next_snapshot_at: null, external_url: "https://www.tiktok.com/@a/video/1" }), undefined, undefined, NOW);
    expect(tiktok).toMatchObject({ status: "Wird nicht gemessen: TikTok braucht ein verbundenes Konto", number: null, canEnterNumbers: true });
    const youtube = publicationRow(pub({ next_snapshot_at: null }), undefined, undefined, NOW);
    expect(youtube.status).toBe("Zahlen für YouTube sind noch nicht eingerichtet");
    expect(`${tiktok.status} ${youtube.status}`).not.toMatch(/[–—]| - |_KEY|TOKEN/);
  });

  it("zeigt Ende, Abschalten und endgültigen Stopp", () => {
    expect(publicationRow(pub({ next_snapshot_at: null, tracking_until: "2026-11-20T10:00:00Z" }), { latest: ok, last: ok }, undefined, NOW)).toMatchObject({ status: "Gemessen bis 20.11.", canStop: false });
    expect(publicationRow(pub({ tracking: "off", next_snapshot_at: null }), undefined, undefined, NOW)).toMatchObject({ status: "Wird nicht mehr gemessen", canStop: false });
    expect(publicationRow(pub({ next_snapshot_at: null, link_check: { stopped: { reason: "nicht_gefunden" } } }), undefined, undefined, NOW)).toMatchObject({ status: "Wird nicht mehr gemessen: Beitrag nicht gefunden", tone: "attention", canStop: false });
  });

  it("nimmt bei Einträgen ohne Link die Zahlen von Hand und das Schnittformat als Namen", () => {
    const r = publicationRow(pub({ platform: "shorts", tracking: "oauth", external_url: null, next_snapshot_at: null, tracking_until: null }), undefined, { publication_id: "p1", views: 900, follows: 12, fetched_at: null }, NOW);
    expect(r).toMatchObject({ platform: "Shorts", url: null, number: "900 Aufrufe, 12 neue Folgende", numberAt: null, status: null, canStop: false, canEnterNumbers: false });
    expect(publicationRow(pub({ platform: "shorts", tracking: "oauth", external_url: null, next_snapshot_at: null }), undefined, undefined, NOW).canEnterNumbers).toBe(true);
  });

  it("verlinkt nur https", () => {
    expect(publicationRow(pub({ external_url: "javascript:alert(1)" }), undefined, undefined, NOW).url).toBeNull();
  });

  it("formatiert Zeitpunkte als Tag, Monat und Uhrzeit", () => {
    expect(shortStamp("2026-07-01T06:05:00Z")).toBe("01.07. 08:05");
  });
});
