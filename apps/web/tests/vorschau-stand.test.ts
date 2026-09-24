/* Der Zustand der Vorschau. Die Frage „zeigt das gebaute Video noch, was eingestellt ist" stand
 * vorher an vier Stellen und wurde an jeder anders beantwortet. Hier wird sie einmal geprüft. */

import { describe, expect, it } from "vitest";
import { standSatz, vorschauStand, wasAbweicht, type StandEingabe } from "@/lib/clips/vorschau-stand";
import { assFarbe, LOOKS, mitVorgabe } from "@/lib/clips/caption-style";
import type { RenderPlan } from "@/lib/repo/types";

const STIL = LOOKS[0].stil;
const SEGMENTE = [{ start: 10, end: 40, role: "body" as const }];

/* Ein Plan, der genau zu STIL, SEGMENTE und den Marken unten passt. Die Untertitelfelder kommen
 * aus derselben Rechnung, die auch der Renderer benutzt. */
function planAus(over: Partial<RenderPlan> = {}): RenderPlan {
  return {
    contract: "render_plan_v1",
    segments: SEGMENTE,
    zeitmarken: [],
    sources: { storage_key: "x", transcript_version: 3, hook_version: 1, candidate_id: "c" },
    captions: geplanteCaptions(),
    ...over,
  } as unknown as RenderPlan;
}

/* Die Untertitelfelder so, wie sie im Plan stehen: dieselben Namen, Zahlen als Zahlen und Farben
 * im ASS-Format. Gebaut aus mitVorgabe, damit die Vorgaben dieselben sind wie in der Oberfläche. */
function geplanteCaptions(): Record<string, unknown> {
  const s = mitVorgabe(STIL);
  return {
    font: s.font,
    font_px: s.font_px,
    words_per_card: s.words_per_card,
    max_lines: s.max_lines,
    outline_px: s.outline_px,
    bold: s.bold,
    all_caps: s.all_caps,
    box: s.box,
    highlight: s.highlight_words,
    base_color: assFarbe(s.base_color),
    highlight_color: assFarbe(s.highlight_color),
    outline_color: assFarbe(s.outline_color),
  };
}

function eingabe(over: Partial<StandEingabe> = {}): StandEingabe {
  return {
    status: "rendered",
    hatDatei: true,
    plan: planAus(),
    renderFehler: null,
    transkriptVersion: 3,
    stil: STIL,
    schnitt: SEGMENTE,
    zeitmarken: [],
    ...over,
  };
}

describe("vorschauStand", () => {
  it("ist aktuell, wenn nichts abweicht", () => {
    expect(vorschauStand(eingabe())).toBe("aktuell");
  });

  it("läuft, solange gebaut wird", () => {
    expect(vorschauStand(eingabe({ status: "rendering" }))).toBe("laeuft");
  });

  it("meldet einen Fehler als Fehler und nicht als veraltet", () => {
    expect(vorschauStand(eingabe({ status: "failed" }))).toBe("fehler");
  });

  it("ist ohne Datei weder aktuell noch veraltet", () => {
    /* Es gibt nichts, was veralten könnte. „Veraltet" wäre hier eine Warnung ohne Grund. */
    expect(vorschauStand(eingabe({ hatDatei: false, status: "draft" }))).toBe("keine");
    expect(vorschauStand(eingabe({ plan: null }))).toBe("keine");
  });

  it("ist veraltet, wenn der Text seitdem geändert wurde", () => {
    /* Der Kern der Beschwerde: eine Textkorrektur ist gespeichert, im Bild steht das alte Wort. */
    const e = eingabe({ transkriptVersion: 4 });
    expect(vorschauStand(e)).toBe("veraltet");
    expect(wasAbweicht(e).text).toBe(true);
  });

  it("ist veraltet, wenn der Untertitelstil ein anderer ist", () => {
    const e = eingabe({ stil: { ...STIL, font_px: 140 } });
    expect(vorschauStand(e)).toBe("veraltet");
    expect(wasAbweicht(e).untertitel).toBe(true);
  });

  it("ist veraltet, wenn der Schnitt ein anderer ist", () => {
    const e = eingabe({ schnitt: [{ start: 12, end: 40, role: "body" }] });
    expect(vorschauStand(e)).toBe("veraltet");
    expect(wasAbweicht(e).schnitt).toBe(true);
  });

  it("ist veraltet, wenn eine Bildausschnitt-Marke dazukam", () => {
    const e = eingabe({ zeitmarken: [{ ab_s: 12, zoom: 1.3 }] });
    expect(vorschauStand(e)).toBe("veraltet");
    expect(wasAbweicht(e).bildausschnitt).toBe(true);
  });

  it("hält ein Teilen ohne Entfernen nicht für eine Änderung", () => {
    /* Der Renderer zieht durchgehende Abschnitte zusammen. Ohne denselben Schritt hier bliebe
     * jeder geteilte Clip für immer „veraltet". */
    const e = eingabe({
      schnitt: [
        { start: 10, end: 25, role: "body" },
        { start: 25, end: 40, role: "body" },
      ],
    });
    expect(vorschauStand(e)).toBe("aktuell");
  });

  it("hält einen alten Plan ohne Marken-Feld nicht für abweichend, solange keine Marke gesetzt ist", () => {
    const ohne = planAus();
    delete (ohne as { zeitmarken?: unknown }).zeitmarken;
    expect(vorschauStand(eingabe({ plan: ohne }))).toBe("aktuell");
  });
});

describe("standSatz", () => {
  it("nennt beim Veralten, was abweicht", () => {
    const e = eingabe({ transkriptVersion: 4, stil: { ...STIL, font_px: 140 } });
    const satz = standSatz("veraltet", wasAbweicht(e));
    expect(satz).toContain("der Text");
    expect(satz).toContain("die Untertitel");
    expect(satz).toContain("wurden");
  });

  it("bleibt bei einer einzigen Abweichung im Singular", () => {
    const e = eingabe({ transkriptVersion: 4 });
    expect(standSatz("veraltet", wasAbweicht(e))).toContain("der Text wurde");
  });

  it("nimmt die Mehrzahl, wenn das eine Wort schon Mehrzahl ist", () => {
    /* „die Untertitel wurde geändert" stand so in der Oberfläche, weil nur die Teile gezählt
     * wurden. Die Mehrzahl hängt am Wort, nicht an der Anzahl. */
    const e = eingabe({ stil: { ...STIL, font_px: 140 } });
    expect(standSatz("veraltet", wasAbweicht(e))).toContain("die Untertitel wurden");
  });

  it("sagt bei aktuell, dass die Vorschau zeigt was eingestellt ist", () => {
    expect(standSatz("aktuell", wasAbweicht(eingabe()))).toContain("bereit");
  });
});
