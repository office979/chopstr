/* Zeitleiste: Prüfung der Marken an der Schnittstelle und die Benennung der Personen.
 *
 * Beides ist reine Logik und gehört deshalb hierher und nicht in einen Klicktest. Die Bedienung
 * selbst (ziehen, tippen) lässt sich nur am laufenden Bild prüfen. */

import { describe, expect, it } from "vitest";
import { markenPruefen } from "@/app/api/projects/[id]/clips/[clipId]/zeitmarken/route";
import { personName } from "@/app/projekte/[id]/clips/[clipId]/Zeitleiste";
import { aktiverLook, LOOKS, mitVorgabe } from "@/lib/clips/caption-style";

describe("markenPruefen", () => {
  it("lässt gültige Marken durch und sortiert sie", () => {
    expect(markenPruefen([{ ab_s: 8, x: 900 }, { ab_s: 2, x: 400 }])).toEqual([
      { ab_s: 2, x: 400 },
      { ab_s: 8, x: 900 },
    ]);
  });

  it("rundet auf Hundertstel und ganze Bildpunkte", () => {
    expect(markenPruefen([{ ab_s: 1.23456, x: 400.7 }])).toEqual([{ ab_s: 1.23, x: 401 }]);
  });

  it("verwirft, was keine Zahl ist", () => {
    /* NaN ist der gefährliche Fall: ohne ausdrückliche Prüfung landete er in der Datenbank und
     * der Renderer bekäme eine Marke ohne Zeitpunkt. */
    for (const m of [{ ab_s: "viel", x: 400 }, { ab_s: 2, x: null }, { ab_s: NaN, x: 1 }, { ab_s: 2 }, {}, null, "x"]) {
      expect(markenPruefen([m])).toEqual([]);
    }
  });

  it("verwirft negative Zeiten und Bildstellen", () => {
    expect(markenPruefen([{ ab_s: -1, x: 400 }, { ab_s: 1, x: -400 }])).toEqual([]);
  });

  it("gibt bei Unsinn eine leere Liste zurück statt zu werfen", () => {
    expect(markenPruefen(null)).toEqual([]);
    expect(markenPruefen({ ab_s: 1, x: 2 })).toEqual([]);
    expect(markenPruefen("nein")).toEqual([]);
  });

  it("behält bei zwei Marken an derselben Stelle nur die spätere", () => {
    /* Sonst hinge das Ergebnis an der Reihenfolge im Body, und dieselbe Eingabe ergäbe mal dies,
     * mal das. */
    expect(markenPruefen([{ ab_s: 5, x: 400 }, { ab_s: 5, x: 900 }])).toEqual([{ ab_s: 5, x: 900 }]);
  });

  it("deckelt die Zahl der Marken", () => {
    const viele = Array.from({ length: 200 }, (_, i) => ({ ab_s: i, x: 100 + i }));
    expect(markenPruefen(viele)).toHaveLength(60);
  });
});

describe("personName", () => {
  it("nennt bei zwei Personen links und rechts", () => {
    expect(personName(400, [400, 1400])).toBe("links");
    expect(personName(1400, [400, 1400])).toBe("rechts");
  });

  it("nennt bei drei Personen auch die Mitte", () => {
    expect(personName(900, [400, 900, 1400])).toBe("Mitte");
  });

  it("zählt bei mehr Personen von links durch", () => {
    /* „Position 4" sagt niemandem etwas, „4. von links" schon. */
    expect(personName(2100, [700, 1100, 1400, 2100, 2400])).toBe("4. von links");
  });

  it("kommt mit einer unbekannten Bildstelle zurecht", () => {
    expect(personName(999, [400, 1400])).toBe("diese Person");
  });

  it("hängt nicht an der Reihenfolge der Liste", () => {
    expect(personName(400, [1400, 400])).toBe("links");
  });
});

describe("Looks", () => {
  it("erkennt den gesetzten Look wieder", () => {
    for (const l of LOOKS) {
      expect(aktiverLook(l.stil), l.name).toBe(l.id);
    }
  });

  it("bleibt am Look hängen, wenn nur Größe oder Wortzahl abweichen", () => {
    /* Sonst spränge die Auswahl weg, sobald jemand am Schieber dreht. */
    const l = LOOKS[1];
    expect(aktiverLook({ ...l.stil, font_px: 150, words_per_card: 5 })).toBe(l.id);
  });

  it("meldet keinen Look, wenn die Schrift eine andere ist", () => {
    expect(aktiverLook({ ...LOOKS[0].stil, font: "Oswald" })).toBeNull();
  });

  it("jeder Look ergibt einen vollständigen Stil", () => {
    for (const l of LOOKS) {
      const v = mitVorgabe(l.stil);
      expect(v.font).toBeTruthy();
      expect(v.font_px).toBeGreaterThan(0);
      expect(v.base_color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("die Looks haben verschiedene Kennungen und Namen", () => {
    expect(new Set(LOOKS.map((l) => l.id)).size).toBe(LOOKS.length);
    expect(new Set(LOOKS.map((l) => l.name)).size).toBe(LOOKS.length);
  });
});
