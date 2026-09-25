/* Zoom als Betonung.
 *
 * Die Wahrheit steht im Worker (pipeline/effekte.py) - er entscheidet, was im Bild passiert. Hier
 * steht die Fassung für die Oberfläche, und diese Tests halten beide auf denselben Zahlen. Die
 * Werte unten sind aus der Python-Umsetzung übernommen; laufen sie auseinander, zeigt die Vorschau
 * etwas anderes als das fertige Video.
 */

import { describe, expect, it } from "vitest";
import {
  dauerAendern,
  entfernen,
  faktor,
  gleich,
  hinzufuegen,
  lesen,
  MAX_FAKTOR,
  MIN_DAUER_S,
  MIN_FAKTOR,
  STAERKE,
  verschieben,
  type Effekt,
} from "@/lib/clips/effekte";

const e = (art: "zoom_in" | "zoom_out", ab: number, dauer: number): Effekt => ({ art, ab_s: ab, dauer_s: dauer });

describe("die Bewegung", () => {
  it("fährt bei „Zoom in“ über den Block und BLEIBT dann dort", () => {
    /* Der Block ist die Fahrt, nicht der Zustand. Nach ihr bleibt das Bild nah - bis ein „Zoom
     * out“ es zurückholt. Vorher sprang es am Blockende zurück. */
    const x = [e("zoom_in", 2, 1)];
    expect(faktor(x, 1.9)).toBe(1);
    expect(faktor(x, 2)).toBe(1);
    expect(faktor(x, 3)).toBeCloseTo(1 + STAERKE, 9);
    for (const t of [3.5, 6, 30]) expect(faktor(x, t)).toBeCloseTo(1 + STAERKE, 9);
  });

  it("holt „Zoom out“ das Bild wieder zurück", () => {
    const x = [e("zoom_in", 1, 1), e("zoom_out", 5, 1)];
    expect(faktor(x, 3)).toBeCloseTo(1 + STAERKE, 9);
    expect(faktor(x, 6)).toBeCloseTo(1, 9);
    expect(faktor(x, 20)).toBeCloseTo(1, 9);
  });

  it("fährt ohne Knick los und kommt ohne Knick an", () => {
    /* Ein linearer Verlauf setzt sichtbar an und bricht sichtbar ab - genau das nimmt man als
     * Ruckeln wahr. Die Steigung muss an beiden Enden gegen null gehen. */
    const x = [e("zoom_in", 0, 2)];
    const steigung = (t: number) => (faktor(x, t + 0.01) - faktor(x, t)) / 0.01;
    expect(Math.abs(steigung(0.01))).toBeLessThan(0.02);
    expect(Math.abs(steigung(1.97))).toBeLessThan(0.02);
    expect(steigung(1)).toBeGreaterThan(0.05);
  });

  it("begrenzt, wie weit es insgesamt gehen kann", () => {
    /* Die Wirkungen addieren sich. Ohne Grenze wäre das Bild nach fünf Effekten unbrauchbar. */
    const viele = [0, 2, 4, 6, 8, 10].map((t) => e("zoom_in", t, 1));
    expect(faktor(viele, 30)).toBeLessThanOrEqual(MAX_FAKTOR + 1e-9);
    const raus = [0, 2, 4, 6, 8, 10].map((t) => e("zoom_out", t, 1));
    expect(faktor(raus, 30)).toBeGreaterThanOrEqual(MIN_FAKTOR - 1e-9);
  });

  it("macht das Bild bei „Zoom out“ ohne vorheriges Hinein kleiner und lässt es so", () => {
    const x = [e("zoom_out", 0, 1)];
    expect(faktor(x, 0)).toBeCloseTo(1, 9);
    expect(faktor(x, 1)).toBeCloseTo(1 - STAERKE, 9);
    expect(faktor(x, 9)).toBeCloseTo(1 - STAERKE, 9);
  });

  it("stimmt mit den Werten des Renderers überein", () => {
    /* Abgelesen aus pipeline/effekte.py. Zwei Umsetzungen derselben Kurve brauchen einen Anker. */
    const x = [e("zoom_in", 1, 1), e("zoom_out", 5, 1)];
    expect(faktor(x, 1.25)).toBeCloseTo(1.016, 3);
    expect(faktor(x, 1.5)).toBeCloseTo(1.05, 3);
    expect(faktor(x, 3)).toBeCloseTo(1.1, 3);
    expect(faktor(x, 5.5)).toBeCloseTo(1.05, 3);
    expect(faktor(x, 8)).toBeCloseTo(1.0, 3);
  });
});

describe("was gelesen wird", () => {
  it("wirft unbekannte Arten und Zeiten ausserhalb des Clips weg", () => {
    const aus = lesen(
      [e("zoom_in", 1, 1.4), { art: "glitzer", ab_s: 2, dauer_s: 1 }, e("zoom_in", 99, 1), "kein Objekt"],
      30,
    );
    expect(aus.map((x) => x.art)).toEqual(["zoom_in"]);
  });

  it("kürzt einen Effekt, der über das Ende hinausragt", () => {
    /* Der Nutzer hat ihn gesetzt; seitdem ist nur der Schnitt kürzer geworden. */
    const aus = lesen([e("zoom_in", 9, 5)], 10);
    expect(aus[0].dauer_s).toBeCloseTo(1, 9);
  });

  it("lässt zwei Effekte nie übereinander liegen", () => {
    const aus = lesen([e("zoom_in", 1, 2), e("zoom_out", 1.5, 2)], 30);
    for (let t = 0; t < 10; t += 0.05) {
      expect(faktor(aus, t)).toBeLessThanOrEqual(1 + STAERKE + 1e-9);
      expect(faktor(aus, t)).toBeGreaterThanOrEqual(1 - STAERKE - 1e-9);
    }
  });
});

describe("bearbeiten", () => {
  it("legt einen Effekt an", () => {
    const aus = hinzufuegen([], "zoom_in", 3, 30);
    expect(aus).toHaveLength(1);
    expect(aus[0].ab_s).toBe(3);
  });

  it("legt keinen an, für den kein Platz mehr ist", () => {
    expect(hinzufuegen([], "zoom_in", 29.9, 30)).toHaveLength(0);
  });

  it("verschiebt und hält ihn dabei im Clip", () => {
    const aus = verschieben([e("zoom_in", 3, 1.4)], 0, 99, 10);
    expect(aus[0].ab_s).toBeCloseTo(10 - 1.4, 9);
  });

  it("ändert die Dauer und begrenzt sie", () => {
    expect(dauerAendern([e("zoom_in", 0, 1.4)], 0, 0.01, 30)[0].dauer_s).toBe(MIN_DAUER_S);
    expect(dauerAendern([e("zoom_in", 0, 1.4)], 0, 99, 30)[0].dauer_s).toBe(6);
  });

  it("entfernt genau einen", () => {
    const aus = entfernen([e("zoom_in", 1, 1), e("zoom_out", 5, 1)], 0);
    expect(aus.map((x) => x.art)).toEqual(["zoom_out"]);
  });
});

describe("der Vergleich für „Video veraltet“", () => {
  it("merkt eine verschobene Sekunde", () => {
    expect(gleich([e("zoom_in", 1, 1.4)], [e("zoom_in", 2, 1.4)])).toBe(false);
  });

  it("stört sich nicht an Rundung im Millisekundenbereich", () => {
    expect(gleich([e("zoom_in", 1.001, 1.4)], [e("zoom_in", 1.0009, 1.4)])).toBe(true);
  });
});
