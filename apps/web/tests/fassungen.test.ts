/* Weitere Fassungen desselben Moments.
 *
 * Der Auftrag nennt die Falle ausdrücklich: „Vermeide identische Exporte mit bloß geändertem
 * Plattformnamen." Bei chopstr sind TikTok, Reels und Shorts alle hochkant. Eine zweite Datei für
 * Reels wäre Bild für Bild dieselbe Datei; gewählt wird deshalb das Format, denn nur das Format
 * verändert das Video.
 */

import { describe, expect, it } from "vitest";
import { FASSUNG_FORMATE, fassungMoeglich, formatSatz, plattformFuerFormat } from "@/lib/clips/fassungen";
import { ASPECT_SIZE, PLATFORM_ASPECT } from "@/lib/clips/presets";
import type { Aspect, Platform } from "@/lib/repo/types";

describe("welche Fassung noch fehlt", () => {
  it("bietet ein Format an, das es noch nicht gibt", () => {
    expect(fassungMoeglich(["9:16"], "1:1")).toBe(true);
  });

  it("verweigert ein Format, das es schon gibt", () => {
    /* Die zweite Datei wäre dieselbe Datei. */
    expect(fassungMoeglich(["9:16"], "9:16")).toBe(false);
    expect(fassungMoeglich(["9:16", "1:1"], "1:1")).toBe(false);
  });
});

describe("Formate statt Plattformnamen", () => {
  it("jedes angebotene Format hat eine eigene Bildgröße", () => {
    const groessen = FASSUNG_FORMATE.map((a) => `${ASPECT_SIZE[a].width}x${ASPECT_SIZE[a].height}`);
    expect(new Set(groessen).size).toBe(FASSUNG_FORMATE.length);
  });

  it("die drei Hochformat-Plattformen teilen sich ein Format", () => {
    /* Genau deshalb zeigt die Auswahl Formate. Vier Plattformen anzubieten, von denen drei
     * dieselbe Datei liefern, wäre ein Versprechen, das die Datei nicht einlöst. */
    const hoch = (["tiktok", "reels", "shorts"] as Platform[]).map((p) => PLATFORM_ASPECT[p]);
    expect(new Set(hoch)).toEqual(new Set(["9:16"]));
    expect(PLATFORM_ASPECT.linkedin).not.toBe("9:16");
  });

  it("zu jedem Format gibt es eine Plattform, für die es der Standard ist", () => {
    for (const a of ["9:16", "4:5"] as Aspect[]) {
      expect(PLATFORM_ASPECT[plattformFuerFormat(a)]).toBe(a);
    }
  });

  it("nennt Format und Bildgröße in einem Satz", () => {
    expect(formatSatz("1:1")).toBe("Quadratisch, 1080 mal 1080");
    expect(formatSatz("9:16")).toBe("Hochformat, 1080 mal 1920");
  });
});
