/* Die Ausschnitt-Rechnung in TypeScript gegen den Python-Renderer.
 *
 * Dieselbe Rechnung steht zweimal da, einmal im Worker und einmal hier, damit die Vorschau sofort
 * zeigt, was eine Aenderung bewirkt. Zwei Stellen laufen mit der Zeit auseinander; deshalb prueft
 * dieser Test nicht gegen erdachte Werte, sondern gegen eine Datei, die der Python-Renderer selbst
 * erzeugt hat. Neu erzeugen mit workers/scripts/ausschnitt_fixtures.py. */

import { describe, expect, it } from "vitest";
import { ausschnittBerechnen, blickraumAnker, grundAusschnitt } from "@/lib/clips/ausschnitt";
import fixtures from "./fixtures-ausschnitt.json";

describe("Gleichstand mit dem Renderer", () => {
  it("rechnet jeden Ausschnitt genauso wie Python", () => {
    for (const f of fixtures.ausschnitt) {
      const ist = ausschnittBerechnen({
        srcW: f.src[0],
        srcH: f.src[1],
        outW: f.out[0],
        outH: f.out[1],
        cx: f.cx,
        cy: f.cy,
        anker: f.anker,
        zoom: f.zoom,
      });
      expect(ist, `src=${f.src} out=${f.out} cx=${f.cx} zoom=${f.zoom}`).toEqual(f.erwartet);
    }
  });

  it("setzt den Blickraum genauso wie Python", () => {
    for (const f of fixtures.anker) {
      expect(blickraumAnker(f.cx, f.breite, f.andere), JSON.stringify(f)).toBeCloseTo(f.erwartet, 6);
    }
  });

  it("die Datei deckt mehr als einen Fall ab", () => {
    /* Sonst liesse sich der Test erfuellen, ohne dass er etwas prueft. */
    expect(fixtures.ausschnitt.length).toBeGreaterThan(20);
    expect(fixtures.anker.length).toBeGreaterThan(4);
  });
});

describe("grundAusschnitt", () => {
  it("nimmt bei querformatiger Quelle die volle Höhe", () => {
    expect(grundAusschnitt(3840, 2160, 1080, 1920)).toEqual([1214, 2160]);
  });

  it("nimmt bei hochformatiger Quelle die volle Breite", () => {
    const [w] = grundAusschnitt(1080, 1920, 1920, 1080);
    expect(w).toBe(1080);
  });

  it("liefert immer gerade Zahlen", () => {
    /* Ungerade Masse mag der Encoder nicht. */
    for (const [sw, sh] of [[1921, 1081], [999, 555], [3840, 2160]]) {
      const [w, h] = grundAusschnitt(sw, sh, 1080, 1920);
      expect(w % 2).toBe(0);
      expect(h % 2).toBe(0);
    }
  });
});

describe("ausschnittBerechnen", () => {
  it("bleibt auch am Bildrand im Quellbild", () => {
    for (const cx of [0, 50, 1920, 3790, 3840]) {
      for (const zoom of [1, 1.3, 1.8]) {
        const a = ausschnittBerechnen({ srcW: 3840, srcH: 2160, outW: 1080, outH: 1920, cx, cy: 900, anker: 1 / 3, zoom });
        expect(a.x).toBeGreaterThanOrEqual(0);
        expect(a.y).toBeGreaterThanOrEqual(0);
        expect(a.x + a.w).toBeLessThanOrEqual(3840);
        expect(a.y + a.h).toBeLessThanOrEqual(2160);
      }
    }
  });

  it("hält beim Zoom das Seitenverhältnis", () => {
    const voll = ausschnittBerechnen({ srcW: 3840, srcH: 2160, outW: 1080, outH: 1920, cx: 1920, cy: 900, anker: 0.5, zoom: 1 });
    const nah = ausschnittBerechnen({ srcW: 3840, srcH: 2160, outW: 1080, outH: 1920, cx: 1920, cy: 900, anker: 0.5, zoom: 1.6 });
    expect(nah.w / nah.h).toBeCloseTo(voll.w / voll.h, 2);
    expect(nah.w).toBeLessThan(voll.w);
  });

  it("schneidet ohne Gesicht mittig", () => {
    const a = ausschnittBerechnen({ srcW: 3840, srcH: 2160, outW: 1080, outH: 1920, cx: null, cy: null, anker: 0.5, zoom: 1 });
    expect(a.x).toBe(Math.round((3840 - a.w) / 2));
    expect(a.y).toBe(0);
  });
});
