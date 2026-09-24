/* Das Zeitlineal: welcher Abstand zwischen zwei beschrifteten Strichen, und wie sie heissen. */

import { describe, expect, it } from "vitest";
import { formatClipDuration } from "@/lib/clips/labels";
import { schrittweite, timecode } from "@/app/projekte/[id]/clips/[clipId]/timeline/Lineal";

describe("timecode", () => {
  it("schreibt Minuten und Sekunden", () => {
    expect(timecode(0)).toBe("0:00");
    expect(timecode(9)).toBe("0:09");
    expect(timecode(75)).toBe("1:15");
    expect(timecode(600)).toBe("10:00");
  });

  it("zeigt auf Wunsch Zehntel", () => {
    expect(timecode(12.34, true)).toBe("0:12,3");
    /* Gerundet, nicht abgeschnitten: 59,99 s ist eine Minute, keine 59,9 Sekunden. Die alte
     * Erwartung gehörte zum abschneidenden Verhalten, das oben „38,8 s" und unten „0:38,7"
     * ergab. */
    expect(timecode(59.99, true)).toBe("1:00,0");
  });

  it("bleibt bei negativen Werten bei null", () => {
    expect(timecode(-5)).toBe("0:00");
  });
});

describe("schrittweite", () => {
  it("nimmt bei viel Platz einen feinen Abstand", () => {
    /* 5 Sekunden auf 800 Punkten sind 160 Punkte je Sekunde; eine halbe Sekunde ist dann 80
     * Punkte breit und damit lesbar. Bei 10 Sekunden waeren es nur 40, deshalb dort eine ganze. */
    expect(schrittweite(5, 800)).toBe(0.5);
    expect(schrittweite(10, 800)).toBe(1);
  });

  it("nimmt bei wenig Platz einen groben", () => {
    /* Zehn Minuten auf 600 Punkten: jede Sekunde waere ein Brei. */
    expect(schrittweite(600, 600)).toBeGreaterThanOrEqual(60);
  });

  it("wählt nur runde Werte", () => {
    /* „Alle 3,7 Sekunden" liest niemand. */
    const erlaubt = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    for (const [s, b] of [[7, 900], [43, 700], [128, 500], [1200, 400], [3, 1200]]) {
      expect(erlaubt).toContain(schrittweite(s, b));
    }
  });

  it("hält den Mindestabstand ein", () => {
    for (const [s, b] of [[7, 900], [43, 700], [128, 500]]) {
      const schritt = schrittweite(s, b);
      expect((schritt * b) / s).toBeGreaterThanOrEqual(64);
    }
  });

  it("kommt mit unsinnigen Massen zurecht", () => {
    expect(schrittweite(0, 0)).toBeGreaterThan(0);
  });
});

/* Am selben Clip stand oben „38,8 s" und in der Timeline „0:38,7". Dieselbe Zahl, zwei
 * Anzeigen - und wer das sieht, sucht den Fehler bei sich. formatClipDuration rundet, timecode
 * schnitt ab. */
describe("timecode und formatClipDuration sagen dasselbe", () => {
  it("rundet die Zehntel wie die Längenangabe", () => {
    expect(timecode(38.75, true)).toBe("0:38,8");
    expect(formatClipDuration(38.75)).toBe("38,8 s");
  });

  it("stimmt über viele Werte hinweg überein", () => {
    for (let i = 0; i < 600; i += 1) {
      const s = i / 7;
      if (s >= 60) break;
      const ausTimecode = timecode(s, true).split(",")[1];
      const ausLaenge = formatClipDuration(s).split(",")[1]?.replace(" s", "");
      expect(ausTimecode, `${s}`).toBe(ausLaenge);
    }
  });

  it("trägt den Übertrag in die Sekunde", () => {
    /* Abgerundet ergäbe 59,96 die Anzeige „0:59,9", naiv gerundet „0:60,0". */
    expect(timecode(59.96, true)).toBe("1:00,0");
    expect(timecode(9.98, true)).toBe("0:10,0");
  });

  it("bleibt ohne Zehntel bei der ganzen Sekunde", () => {
    expect(timecode(38.75)).toBe("0:38");
    expect(timecode(125)).toBe("2:05");
  });
});
