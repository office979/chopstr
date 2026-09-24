/* Bildausschnitt: Prüfung der Marken an der Schnittstelle und die Benennung der Personen.
 *
 * Beides ist reine Logik und gehört deshalb hierher und nicht in einen Klicktest. Die Bedienung
 * selbst (ziehen, tippen) lässt sich nur am laufenden Bild prüfen. */

import { describe, expect, it } from "vitest";
import { markenPruefen } from "@/app/api/projects/[id]/clips/[clipId]/zeitmarken/route";
import {
  beschreibung,
  NAEHE_MAX,
  NAEHE_MIN,
  NAEHE_SCHRITT,
  naeheKurz,
  naeheName,
  personName,
} from "@/app/projekte/[id]/clips/[clipId]/Bildausschnitt";
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

describe("Marken mit Zoom und geteiltem Bild", () => {
  it("nimmt Zoom und Layout an", () => {
    expect(markenPruefen([{ ab_s: 5, x: 400, zoom: 1.3, layout: "geteilt" }])).toEqual([
      { ab_s: 5, x: 400, zoom: 1.3, layout: "geteilt" },
    ]);
  });

  it("zieht den Zoom auf das Mögliche", () => {
    /* Unter 1,0 wäre Herauszoomen, und dafür gibt es keine Bildpunkte mehr. Spiegel von
     * tracking.ZOOM_MIN / ZOOM_MAX. */
    expect(markenPruefen([{ ab_s: 1, zoom: 9 }])[0].zoom).toBe(1.8);
    expect(markenPruefen([{ ab_s: 1, zoom: 0.2 }])[0].zoom).toBe(1);
  });

  it("übergeht unbekannte Layouts", () => {
    expect(markenPruefen([{ ab_s: 1, x: 400, layout: "karussell" }])[0].layout).toBeUndefined();
  });

  it("eine Marke ohne Inhalt ist keine Entscheidung", () => {
    expect(markenPruefen([{ ab_s: 5 }])).toEqual([]);
  });

  it("eine Marke darf auch nur den Zoom setzen", () => {
    /* Wer näher heran will, muss nicht auch die Person wählen. */
    expect(markenPruefen([{ ab_s: 5, zoom: 1.3 }])).toEqual([{ ab_s: 5, zoom: 1.3 }]);
  });

  it("verwirft unsinnige Zoomwerte, statt sie zu raten", () => {
    for (const z of [null, "viel", NaN, [], {}]) {
      expect(markenPruefen([{ ab_s: 1, x: 5, zoom: z }])[0].zoom).toBeUndefined();
    }
  });
});

describe("Nähe", () => {
  it("bleibt im Bereich, den Worker und Schnittstelle annehmen", () => {
    /* Spiegel von tracking.ZOOM_MIN / ZOOM_MAX. Laufen die auseinander, schneidet der Regler
     * Werte ein, die beim Speichern still zurechtgestutzt werden - und der Nutzer sieht danach
     * etwas anderes als eingestellt. */
    expect(NAEHE_MIN).toBe(1.0);
    expect(NAEHE_MAX).toBe(1.8);
  });

  it("hat eine Schrittweite, die sich noch bedienen lässt", () => {
    const stufen = Math.round((NAEHE_MAX - NAEHE_MIN) / NAEHE_SCHRITT);
    expect(stufen).toBeGreaterThanOrEqual(8);
    expect(stufen).toBeLessThanOrEqual(40);
  });
});

describe("naeheName", () => {
  it("nennt den Ausgangszustand beim Namen und nicht mit einer Zahl", () => {
    expect(naeheName(1)).toBe("Normal");
  });

  it("sagt Prozent statt Faktor", () => {
    /* „1,35×" ist Kamerasprache. Wer den Ausschnitt setzt, denkt in „wie viel näher". */
    expect(naeheName(1.35)).toBe("35 Prozent näher");
    expect(naeheName(1.8)).toBe("80 Prozent näher");
  });

  it("rundet auf ganze Prozent", () => {
    expect(naeheName(1.05)).toBe("5 Prozent näher");
  });
});

describe("beschreibung", () => {
  it("ohne Marke entscheidet die Automatik", () => {
    expect(beschreibung(null, [400, 1400])).toBe("Automatisch");
  });

  it("nennt Person und Nähe in einem Satz", () => {
    expect(beschreibung({ ab_s: 1, x: 1400, zoom: 1.3 }, [400, 1400])).toBe("rechts, 30 % näher");
  });

  it("nennt beim geteilten Bild beide statt einer Person", () => {
    expect(beschreibung({ ab_s: 1, x: 400, layout: "geteilt" }, [400, 1400])).toBe("Beide");
  });

  it("lässt die Person weg, wenn es gar keine Wahl gab", () => {
    expect(beschreibung({ ab_s: 1, x: 400, zoom: 1.6 }, [400])).toBe("60 % näher");
  });

  it("sagt wenigstens, dass von Hand gesetzt wurde", () => {
    expect(beschreibung({ ab_s: 1, zoom: 1 }, [])).toBe("Von Hand");
  });
});

describe("naeheKurz", () => {
  it("passt in eine Abschnittsbeschriftung", () => {
    /* In der Timeline ist Platz für ein paar Zeichen, nicht für einen Satz. */
    expect(naeheKurz(1.3)).toBe("30 % näher");
    expect(naeheKurz(1)).toBe("normal");
    expect(naeheKurz(1.3).length).toBeLessThan(14);
  });
});
