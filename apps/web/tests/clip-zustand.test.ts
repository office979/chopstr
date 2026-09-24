/* Der Zustand eines Clips in der Übersicht.
 *
 * Vorher stand dort der technische Zustand: „Fertig", auch an Clips mit einer Untertitelwarnung
 * und an solchen, deren gebautes Video nicht mehr zu den Einstellungen passte. Hier wird geprüft,
 * dass die drei Quellen (Render, Prüfstand, Gastfreigabe) in der richtigen Reihenfolge zählen. */

import { describe, expect, it } from "vitest";
import { clipZustand, korrekturGrund, ZUSTAND_LABEL, ZUSTAND_RANG } from "@/lib/clips/clip-zustand";
import type { StandEingabe } from "@/lib/clips/vorschau-stand";
import type { Clip, GuestApproval } from "@/lib/repo/types";

const SEGMENTE = [{ start: 10, end: 40, role: "body" as const }];

function clip(over: Partial<Clip> = {}): Clip {
  return {
    status: "rendered",
    review: "offen",
    cps_warnings: [],
    fidelity_warnings: [],
    composition: SEGMENTE,
    file_key: "clips/x.mp4",
    render_error: null,
    ...over,
  } as unknown as Clip;
}

/* Ein Stand, bei dem nichts abweicht: gebaut, Datei da, Plan passt zu allem. */
function stand(over: Partial<StandEingabe> = {}): StandEingabe {
  return {
    status: "rendered",
    hatDatei: true,
    plan: null,
    renderFehler: null,
    transkriptVersion: 1,
    stil: {},
    schnitt: SEGMENTE,
    zeitmarken: [],
    ...over,
  };
}

const freigegeben = { decision: "approved" } as unknown as GuestApproval;

describe("clipZustand", () => {
  it("wartet auf eine Entscheidung, wenn alles in Ordnung ist", () => {
    expect(clipZustand({ clip: clip(), freigabe: null, stand: stand() })).toBe("pruefen");
  });

  it("zeigt einen laufenden Render als solchen", () => {
    expect(clipZustand({ clip: clip({ status: "rendering" }), freigabe: null, stand: stand({ status: "rendering" }) })).toBe(
      "wird_erstellt",
    );
    expect(clipZustand({ clip: clip({ status: "draft" }), freigabe: null, stand: stand({ status: "draft" }) })).toBe(
      "wird_erstellt",
    );
  });

  it("meldet einen Fehler als Fehler", () => {
    expect(clipZustand({ clip: clip({ status: "failed" }), freigabe: null, stand: stand({ status: "failed" }) })).toBe("fehler");
  });

  it("verlangt eine Korrektur bei einer Untertitelwarnung", () => {
    /* Genau der Widerspruch aus dem Screenshot: „Fertig" und daneben eine Warnung. */
    const c = clip({ cps_warnings: ["Zu schnell (24 Z/s): 'Der Umsatz'"] });
    expect(clipZustand({ clip: c, freigabe: null, stand: stand() })).toBe("korrektur");
  });

  it("verlangt eine Korrektur, wenn das gebaute Video nicht mehr passt", () => {
    const s = stand({
      plan: { segments: [{ start: 12, end: 40, role: "body" }], sources: { transcript_version: 1 } } as never,
    });
    expect(clipZustand({ clip: clip(), freigabe: null, stand: s })).toBe("korrektur");
  });

  it("stellt die Korrektur über die Freigabe", () => {
    /* Eine Freigabe für eine Datei, die nicht mehr stimmt, wäre eine Freigabe für etwas anderes
     * als das, was herauskommt. */
    const c = clip({ cps_warnings: ["zu schnell"], review: "bereit" });
    expect(clipZustand({ clip: c, freigabe: freigegeben, stand: stand() })).toBe("korrektur");
  });

  it("zeigt eine Gastfreigabe an", () => {
    expect(clipZustand({ clip: clip(), freigabe: freigegeben, stand: stand() })).toBe("freigegeben");
  });

  it("zeigt die eigene Entscheidung an", () => {
    expect(clipZustand({ clip: clip({ review: "bereit" }), freigabe: null, stand: stand() })).toBe("bereit");
  });

  it("stellt das Verwerfen über alles andere", () => {
    /* Wer einen Clip aussortiert hat, will ihn nicht als „Korrektur nötig" wiedersehen. */
    const c = clip({ review: "verworfen", cps_warnings: ["zu schnell"], status: "failed" });
    expect(clipZustand({ clip: c, freigabe: freigegeben, stand: stand({ status: "failed" }) })).toBe("verworfen");
  });

  it("hat für jeden Zustand ein deutsches Wort und einen Rang", () => {
    for (const z of Object.keys(ZUSTAND_LABEL) as (keyof typeof ZUSTAND_LABEL)[]) {
      expect(ZUSTAND_LABEL[z].length).toBeGreaterThan(2);
      expect(ZUSTAND_RANG[z]).toBeGreaterThanOrEqual(0);
    }
  });

  it("stellt in der Reihenfolge nach vorn, was Arbeit macht", () => {
    expect(ZUSTAND_RANG.korrektur).toBeLessThan(ZUSTAND_RANG.pruefen);
    expect(ZUSTAND_RANG.pruefen).toBeLessThan(ZUSTAND_RANG.bereit);
    expect(ZUSTAND_RANG.verworfen).toBeGreaterThan(ZUSTAND_RANG.freigegeben);
  });
});

describe("korrekturGrund", () => {
  it("nennt zuerst das veraltete Video", () => {
    expect(korrekturGrund(clip({ cps_warnings: ["x"] }), true)).toContain("nicht mehr");
  });

  it("zählt die schnellen Stellen", () => {
    expect(korrekturGrund(clip({ cps_warnings: ["a", "b"] }), false)).toBe("2 Stellen laufen schnell durch.");
    expect(korrekturGrund(clip({ cps_warnings: ["a"] }), false)).toBe("Eine Stelle läuft schnell durch.");
  });

  it("gibt eine Treuewarnung im Wortlaut zurück, wenn sie einer ist", () => {
    expect(korrekturGrund(clip({ fidelity_warnings: ["Verneinung entfernt"] }), false)).toBe("Verneinung entfernt");
  });
});
