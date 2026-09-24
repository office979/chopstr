/* Die Timeline: was weggeschnitten ist, und wo die Bildausschnitt-Marker in der Quelle liegen. */

import { describe, expect, it } from "vitest";
import { luecken, marken_abschnitte } from "@/app/projekte/[id]/clips/[clipId]/timeline/Timeline";
import type { Schnitt } from "@/lib/clips/schnitt";

const A = (start: number, end: number) => ({ start, end, role: "body" as const });

describe("luecken", () => {
  it("zeigt bei einem durchgehenden Clip nur Vorlauf und Nachlauf", () => {
    expect(luecken([A(10, 40)], 5, 45)).toEqual([
      { von: 5, bis: 10 },
      { von: 40, bis: 45 },
    ]);
  });

  it("zeigt eine entfernte Stelle in der Mitte", () => {
    const l = luecken([A(10, 20), A(30, 40)], 10, 40);
    expect(l).toEqual([{ von: 20, bis: 30 }]);
  });

  it("gibt ohne Vorlauf nichts aus", () => {
    expect(luecken([A(0, 40)], 0, 40)).toEqual([]);
  });

  it("liefert keine Lücken mit null Breite", () => {
    for (const l of luecken([A(10, 20), A(20, 30)], 10, 30)) {
      expect(l.bis).toBeGreaterThan(l.von);
    }
  });
});

describe("marken_abschnitte", () => {
  const SCHNITT: Schnitt = [A(10, 40)];

  it("gibt ohne Marker einen automatischen Abschnitt über die ganze Länge", () => {
    const a = marken_abschnitte([], SCHNITT);
    expect(a).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: null }]);
  });

  it("rechnet Clipzeit in Quellzeit um", () => {
    /* Der Marker steht bei Sekunde 5 des Clips; der Clip fängt bei 10 an. */
    const m = { ab_s: 5, x: 400 };
    expect(marken_abschnitte([m], SCHNITT)).toEqual([
      { vonQuelle: 10, bisQuelle: 15, marke: null },
      { vonQuelle: 15, bisQuelle: 40, marke: m },
    ]);
  });

  it("rechnet über eine entfernte Lücke hinweg richtig", () => {
    /* Zwei Abschnitte, dazwischen fehlen 10 s. Sekunde 12 des Clips liegt hinter der Naht. */
    const zwei: Schnitt = [A(10, 20), A(30, 40)];
    const m = { ab_s: 12, zoom: 1.3 };
    const a = marken_abschnitte([m], zwei);
    expect(a[1].vonQuelle).toBe(32);
  });

  it("ein Marker bei null ersetzt den automatischen Anfang", () => {
    const m = { ab_s: 0, zoom: 1.6 };
    expect(marken_abschnitte([m], SCHNITT)).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: m }]);
  });

  it("übergeht Marker hinter dem Ende des Clips", () => {
    /* Nach einem Kürzen kann ein Marker draußen liegen; ein Abschnitt mit negativer Breite wäre
     * unsichtbar und in der Rechnung Unsinn. */
    expect(marken_abschnitte([{ ab_s: 99, x: 1 }], SCHNITT)).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: null }]);
  });

  it("die Abschnitte liegen lückenlos hintereinander", () => {
    const a = marken_abschnitte([{ ab_s: 5, x: 1 }, { ab_s: 18, zoom: 1.3 }], SCHNITT);
    for (let i = 1; i < a.length; i += 1) expect(a[i].vonQuelle).toBeCloseTo(a[i - 1].bisQuelle, 5);
  });
});
