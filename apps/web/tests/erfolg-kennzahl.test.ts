/* Welche Zahl eine Plattform überhaupt liefert.
 *
 * Der A/B-Test misst die Folgequote. Die Fähigkeitstabelle sagt, dass genau diese Zahl auf TikTok,
 * Instagram und LinkedIn nicht existiert: sie ordnen neue Folgende keinem einzelnen Beitrag zu.
 * Ein Test, der darauf wartet, wartet für immer, und die Oberfläche versprach trotzdem
 * „Folgequote". Fehlend heisst nicht null und heisst auch nicht Misserfolg.
 */

import { describe, expect, it } from "vitest";
import { DEFAULT_CAPABILITIES, erfolgKennzahlFuer } from "@/lib/publishing/capabilities";
import { decisionCheck, successMetricLabel } from "@/lib/experiments/stats";
import type { Experiment } from "@/lib/repo/types-publishing";

const experiment = { status: "running", min_exposure: 1000 } as unknown as Experiment;
/* Vor drei Tagen gepostet: die 48 Stunden sind um, es fehlen nur noch die Zahlen. Genau in dieser
 * Lage entscheidet sich, ob „noch nicht da" oder „kommt nicht" die richtige Auskunft ist. */
const vorDreiTagen = new Date(Date.now() - 3 * 86_400_000).toISOString();
const leer = { views: null, follows: null, saves: null, likes: null, follows_per_1k: null, published_at: vorDreiTagen, window: null };

describe("Erfolgskennzahl je Plattform", () => {
  it("weicht auf die Save-Quote aus, wo es keine Folgezuordnung gibt", () => {
    const e = erfolgKennzahlFuer(DEFAULT_CAPABILITIES.instagram, "Instagram");
    expect(e.kennzahl).toBe("saves");
    expect(e.satz).toContain("keinem einzelnen Beitrag");
  });

  it("nimmt auf TikTok die Like-Quote, weil auch Saves nicht gesichert sind", () => {
    const e = erfolgKennzahlFuer(DEFAULT_CAPABILITIES.tiktok, "TikTok");
    expect(e.kennzahl).toBe("likes");
  });

  it("bleibt bei der Folgequote, wo die Plattform sie liefern kann", () => {
    const e = erfolgKennzahlFuer(DEFAULT_CAPABILITIES.youtube, "YouTube");
    expect(e.kennzahl).toBe("follows");
    /* „conditional": die Zahl kommt unter Umständen, das muss dabeistehen. */
    expect(e.sicher).toBe(false);
  });

  it("benennt eine Plattform ohne Aufrufe als Grenze, nicht als Verzögerung", () => {
    const ohneViews = { ...DEFAULT_CAPABILITIES.linkedin, views: false as const };
    const e = erfolgKennzahlFuer(ohneViews, "LinkedIn");
    expect(e.aufrufeMoeglich).toBe(false);
    expect(e.satz).toContain("von Hand");
  });
});

describe("die Entscheidung wartet nicht auf Unmögliches", () => {
  it("sagt bei fehlenden Aufrufen, dass sie nicht kommen", () => {
    const e = erfolgKennzahlFuer({ ...DEFAULT_CAPABILITIES.linkedin, views: false as const }, "LinkedIn");
    const check = decisionCheck(experiment, leer, leer, e);
    expect(check.ready).toBe(false);
    expect(check.reasons.some((r) => r.includes("keine Aufrufe"))).toBe(true);
    expect(check.reasons.some((r) => r.includes("noch keine Aufrufe gemeldet"))).toBe(false);
  });

  it("sagt ohne diese Auskunft weiter, dass die Zahlen noch fehlen", () => {
    const check = decisionCheck(experiment, leer, leer);
    expect(check.reasons.some((r) => r.includes("noch keine Aufrufe gemeldet"))).toBe(true);
  });
});

describe("das Etikett stimmt schon vor der ersten Zahl", () => {
  it("verspricht keine Folgequote, wo es keine gibt", () => {
    const e = erfolgKennzahlFuer(DEFAULT_CAPABILITIES.instagram, "Instagram");
    expect(successMetricLabel(null, e)).toBe("Save-Quote (kein Folge-Signal)");
  });

  it("nimmt die echte Zahl, sobald sie da ist", () => {
    const e = erfolgKennzahlFuer(DEFAULT_CAPABILITIES.instagram, "Instagram");
    expect(successMetricLabel({ ...leer, views: 1000, follows: 12 }, e)).toBe("Folgequote");
  });
});
