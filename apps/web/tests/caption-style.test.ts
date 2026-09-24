/* Untertitel-Stil: Prüfung an der Schnittstelle und Gleichstand mit dem Worker.
 *
 * Der wichtigste Test hier ist der letzte. Grenzen stehen an zwei Stellen, in Python und in
 * TypeScript, und zwei Stellen laufen mit der Zeit auseinander. Dann bietet die Oberfläche etwas
 * an, was der Renderer hinterher zurechtstutzt, und der Nutzer sieht etwas anderes als er
 * eingestellt hat. Deshalb liest dieser Test die Python-Datei und vergleicht die Zahlen. */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { assFarbe, BASIS_PRESETS, type CaptionStyle, FONTS, GRENZEN, maxZeichen, mitVorgabe, passtZumRender, stilPruefen, VORGABE } from "@/lib/clips/caption-style";

const WURZEL = resolve(import.meta.dirname, "../../..");

describe("stilPruefen", () => {
  it("lässt gültige Werte durch", () => {
    expect(stilPruefen({ font: "Anton", font_px: 90, words_per_card: 3, base_color: "#FF00AA" })).toEqual({
      font: "Anton",
      font_px: 90,
      words_per_card: 3,
      base_color: "#ff00aa",
    });
  });

  it("zieht zu große und zu kleine Zahlen auf das Erlaubte", () => {
    expect(stilPruefen({ font_px: 9999 }).font_px).toBe(GRENZEN.font_px[1]);
    expect(stilPruefen({ font_px: -5 }).font_px).toBe(GRENZEN.font_px[0]);
    expect(stilPruefen({ words_per_card: 99 }).words_per_card).toBe(6);
  });

  it("verwirft, was keine Zahl ist", () => {
    /* NaN ist der gefährliche Fall: Math.min(180, NaN) ist NaN, und jeder Vergleich damit ist
     * falsch. Ohne ausdrückliche Prüfung würde daraus stillschweigend ein Wert. */
    for (const wert of ["viel", null, [], {}, true, NaN, Infinity]) {
      expect(stilPruefen({ font_px: wert }).font_px).toBeUndefined();
    }
  });

  it("nimmt nur Farben in voller Hex-Schreibweise", () => {
    expect(stilPruefen({ base_color: "#abc" }).base_color).toBeUndefined();
    expect(stilPruefen({ base_color: "rot" }).base_color).toBeUndefined();
    expect(stilPruefen({ base_color: "#AABBCC" }).base_color).toBe("#aabbcc");
  });

  it("nimmt nur Schriften aus der gemeinsamen Liste", () => {
    expect(stilPruefen({ font: "Comic Sans" }).font).toBeUndefined();
    expect(stilPruefen({ font: FONTS[0].id }).font).toBe(FONTS[0].id);
  });

  it("nimmt nur bekannte Grundlagen", () => {
    expect(stilPruefen({ preset: "gibtsnicht" }).preset).toBeUndefined();
    expect(stilPruefen({ preset: "tiktok_words" }).preset).toBe("tiktok_words");
    /* Die leere Kennung heißt „automatisch" und wird nicht gespeichert. */
    expect(stilPruefen({ preset: "" }).preset).toBeUndefined();
  });

  it("wirft unbekannte Felder weg, statt sie als Altlast mitzuschleppen", () => {
    expect(stilPruefen({ zoom: 3, schriftart: "Anton", id: "x" })).toEqual({});
  });

  it("gibt bei Unsinn ein leeres Objekt zurück statt zu werfen", () => {
    expect(stilPruefen(null)).toEqual({});
    expect(stilPruefen("Text")).toEqual({});
    expect(stilPruefen([1, 2])).toEqual({});
  });

  it("erzwingt bei einem Wort je Einblendung eine Zeile", () => {
    expect(stilPruefen({ words_per_card: 1, max_lines: 3 })).toEqual({ words_per_card: 1, max_lines: 1 });
  });
});

describe("maxZeichen", () => {
  it("wird bei größerer Schrift kleiner", () => {
    expect(maxZeichen(78)).toBeGreaterThan(maxZeichen(120));
  });

  it("bleibt auch bei unsinnigen Werten brauchbar", () => {
    expect(maxZeichen(0)).toBeGreaterThanOrEqual(8);
    expect(maxZeichen(10_000)).toBeGreaterThanOrEqual(8);
  });
});

describe("mitVorgabe", () => {
  it("füllt auf, was nicht eingestellt ist", () => {
    expect(mitVorgabe({ font_px: 60 })).toEqual({ ...VORGABE, font_px: 60 });
  });

  it("kommt mit fehlendem Stil zurecht", () => {
    expect(mitVorgabe(null)).toEqual(VORGABE);
    expect(mitVorgabe(undefined)).toEqual(VORGABE);
  });
});

describe("Gleichstand mit dem Worker", () => {
  const python = readFileSync(resolve(WURZEL, "workers/chopstr_worker/pipeline/captions_de.py"), "utf8");

  it("hat dieselben Grenzen wie captions_de.STIL_GRENZEN", () => {
    const block = python.match(/STIL_GRENZEN: dict\[str, tuple\[float, float\]\] = \{([\s\S]*?)\}/);
    expect(block, "STIL_GRENZEN nicht gefunden").toBeTruthy();
    const ausPython: Record<string, [number, number]> = {};
    for (const [, feld, a, b] of block![1].matchAll(/"(\w+)":\s*\(([\d.]+),\s*([\d.]+)\)/g)) {
      ausPython[feld] = [Number(a), Number(b)];
    }
    expect(ausPython).toEqual(
      Object.fromEntries(Object.entries(GRENZEN).map(([k, v]) => [k, [v[0], v[1]]])),
    );
  });

  it("rechnet die Zeichen pro Zeile nach derselben Formel", () => {
    const em = python.match(/AVG_CHAR_EM = ([\d.]+)/);
    expect(em).toBeTruthy();
    /* Dieselbe Formel: max(8, safe_breite / (font_px * AVG_CHAR_EM)), abgerundet. */
    const nachPython = (fontPx: number, breite: number) =>
      Math.max(8, Math.floor(breite / (Math.max(fontPx, 1) * Number(em![1]))));
    for (const px of [28, 60, 78, 104, 180]) {
      expect(maxZeichen(px)).toBe(nachPython(px, 1080 - 180));
    }
  });

  it("bietet nur Grundlagen an, die der Worker auch kennt", () => {
    const presets = [...python.matchAll(/^\s{4}"(\w+)": CaptionPreset\(|^\s{4}"(\w+)": CaptionPreset$/gm)]
      .map((m) => m[1] ?? m[2])
      .filter(Boolean);
    expect(presets.length).toBeGreaterThan(0);
    for (const p of BASIS_PRESETS) {
      if (!p.id) continue; // "automatisch" ist keine Kennung im Worker
      expect(presets, `Grundlage ${p.id} fehlt im Worker`).toContain(p.id);
    }
  });

  it("liest dieselbe Schriftenliste wie der Worker", () => {
    const datei = JSON.parse(readFileSync(resolve(WURZEL, "packages/design/caption_fonts.json"), "utf8"));
    expect(FONTS.map((f) => f.id)).toEqual(datei.schriften.map((s: { id: string }) => s.id));
  });
});

describe("assFarbe", () => {
  it("dreht die Reihenfolge wie ASS es erwartet", () => {
    /* Spiegel von captions_de.ass_farbe. Falsch herum faellt nicht auf, es sieht nur falsch aus:
     * aus Rot wird Blau. */
    expect(assFarbe("#ffd700")).toBe("&H0000D7FF");
    expect(assFarbe("#FF0000")).toBe("&H000000FF");
    expect(assFarbe("#0000FF")).toBe("&H00FF0000");
  });

  it("lässt bereits gesetzte ASS-Werte durch", () => {
    expect(assFarbe("&H0000D7FF")).toBe("&H0000D7FF");
  });

  it("verwirft Unbrauchbares", () => {
    for (const w of ["", "  ", "#abc", "rot", "#GGGGGG"]) expect(assFarbe(w)).toBeNull();
  });
});

describe("passtZumRender", () => {
  /* Was der Plan traegt, wenn mit der Vorgabe gerendert wurde. Entspricht dem captions-Block aus
   * render_plan.caption_block fuer das Preset reels_words. */
  const gerendert = {
    preset: "reels_words",
    font: VORGABE.font,
    font_px: VORGABE.font_px,
    words_per_card: VORGABE.words_per_card,
    max_lines: VORGABE.max_lines,
    outline_px: VORGABE.outline_px,
    bold: VORGABE.bold,
    all_caps: VORGABE.all_caps,
    box: VORGABE.box,
    highlight: VORGABE.highlight_words,
    base_color: assFarbe(VORGABE.base_color),
    highlight_color: assFarbe(VORGABE.highlight_color),
    outline_color: assFarbe(VORGABE.outline_color),
    box_color: assFarbe(VORGABE.box_color),
    safe_zone: { top: 210, left: 60, right: 120, bottom: 310 },
    baseline_y: 1920 - 310 - VORGABE.bottom_margin_px,
  };

  it("ohne Render gibt es nichts, was veraltet sein könnte", () => {
    expect(passtZumRender({ font_px: 150 }, null)).toBe(true);
  });

  it("unveränderter Stil passt zum Render", () => {
    expect(passtZumRender({}, gerendert)).toBe(true);
  });

  it("erkennt jede Änderung, die man im Bild sähe", () => {
    const aenderungen: CaptionStyle[] = [
      { font_px: 120 },
      { words_per_card: 3 },
      { max_lines: 2 },
      { outline_px: 12 },
      { bold: !VORGABE.bold },
      { all_caps: true },
      { box: true },
      { highlight_words: false },
      { font: "Anton" },
      { base_color: "#00ff9c" },
      { highlight_color: "#ff3b6b" },
      { outline_color: "#ff3b6b" },
      { bottom_margin_px: 420 },
    ];
    for (const a of aenderungen) {
      expect(passtZumRender(a, gerendert), JSON.stringify(a)).toBe(false);
    }
  });

  it("ein alter Plan ohne die neuen Felder gilt als abweichend", () => {
    /* Lieber einmal zu viel darauf hinweisen als eine Änderung stillschweigend verschlucken. */
    const alt = { preset: "reels_words", font: "Inter", font_px: 92, max_chars: 17, baseline_y: 1350 };
    expect(passtZumRender({}, alt)).toBe(false);
  });
});
