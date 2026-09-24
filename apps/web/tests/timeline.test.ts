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
    expect(marken_abschnitte([], SCHNITT)).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: null }]);
  });

  it("nimmt die Zeit des Markers so, wie sie in der Quelle liegt", () => {
    /* Marker liegen in Quellzeit, nicht in Clipzeit: eine Marke zeigt auf eine Stelle im Video.
     * Genau so liest sie der Renderer (tracking.zeitmarken_anwenden), und nur so bleibt der
     * Bildausschnitt stehen, wenn vorne etwas weggeschnitten wird. */
    const m = { ab_s: 15, x: 400 };
    expect(marken_abschnitte([m], SCHNITT)).toEqual([
      { vonQuelle: 10, bisQuelle: 15, marke: null },
      { vonQuelle: 15, bisQuelle: 40, marke: m },
    ]);
  });

  it("verschiebt sich nicht, wenn der Anfang gekürzt wird", () => {
    /* Der Kern der Sache: derselbe Marker, ein um fünf Sekunden späterer Clipanfang, und der
     * Marker sitzt weiter bei Quellsekunde 25. */
    const m = { ab_s: 25, zoom: 1.3 };
    expect(marken_abschnitte([m], [A(10, 40)])[1].vonQuelle).toBe(25);
    expect(marken_abschnitte([m], [A(15, 40)])[1].vonQuelle).toBe(25);
  });

  it("ein Marker auf dem Clipanfang ersetzt den automatischen Anfang", () => {
    const m = { ab_s: 10, zoom: 1.6 };
    expect(marken_abschnitte([m], SCHNITT)).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: m }]);
  });

  it("ein Marker vor dem Clipanfang gilt trotzdem, denn er ist die letzte Entscheidung", () => {
    /* Nach einem Kürzen am Anfang kann eine gesetzte Marke davor liegen. Sie einfach fallen zu
     * lassen hiesse, eine Entscheidung stillschweigend zurückzunehmen. */
    const m = { ab_s: 4, zoom: 1.6 };
    expect(marken_abschnitte([m], SCHNITT)).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: m }]);
  });

  it("übergeht Marker hinter dem Ende des Clips", () => {
    expect(marken_abschnitte([{ ab_s: 99, x: 1 }], SCHNITT)).toEqual([{ vonQuelle: 10, bisQuelle: 40, marke: null }]);
  });

  it("die Abschnitte liegen lückenlos hintereinander", () => {
    const a = marken_abschnitte([{ ab_s: 15, x: 1 }, { ab_s: 28, zoom: 1.3 }], SCHNITT);
    expect(a[0].vonQuelle).toBe(10);
    expect(a[a.length - 1].bisQuelle).toBe(40);
    for (let i = 1; i < a.length; i += 1) expect(a[i].vonQuelle).toBe(a[i - 1].bisQuelle);
  });
});
