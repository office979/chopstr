/* Wörter und Schreibweisen einer Marke: was sich widerspricht, muss auffallen.
 *
 * Der Grund: die drei Listen greifen an verschiedenen Stellen der Verarbeitung. Steht ein Wort
 * in zweien davon, hängt das Ergebnis an der Reihenfolge und nicht an der Absicht. */

import { describe, expect, it } from "vitest";
import { befundSatz, pruefen, type Regeln } from "@/lib/brand/wortregeln";

const leer: Regeln = { merken: [], behalten: [], vermeiden: [] };

describe("pruefen", () => {
  it("findet nichts, wenn nichts da ist", () => {
    expect(pruefen(leer)).toEqual([]);
  });

  it("lässt saubere Listen in Ruhe", () => {
    expect(pruefen({ merken: ["PLACEMedia"], behalten: ["Jänner"], vermeiden: ["Game Changer"] })).toEqual([]);
  });

  it("findet ein doppeltes Wort in derselben Liste", () => {
    const b = pruefen({ ...leer, merken: ["PLACEMedia", "placemedia"] });
    expect(b).toHaveLength(1);
    expect(b[0]).toMatchObject({ art: "doppelt", liste: "merken" });
  });

  it("stört sich nicht an Groß- und Kleinschreibung beim Vergleich", () => {
    expect(pruefen({ ...leer, behalten: ["Jänner", "JÄNNER"] })).toHaveLength(1);
  });

  it("übergeht Satzzeichen am Rand", () => {
    expect(pruefen({ ...leer, vermeiden: ["Game Changer", "Game Changer,"] })).toHaveLength(1);
  });

  it("meldet einen Widerspruch zwischen merken und vermeiden", () => {
    /* Das ist der Fall, der still ein Zufallsergebnis erzeugt: einmal soll das Wort genau so
     * geschrieben werden, einmal gar nicht vorkommen. */
    const b = pruefen({ merken: ["Synergie"], behalten: [], vermeiden: ["Synergie"] });
    expect(b).toHaveLength(1);
    expect(b[0]).toMatchObject({ art: "widerspruch", hier: "vermeiden", dort: "merken" });
    expect(befundSatz(b[0])).toContain("Zufall");
  });

  it("meldet einen Widerspruch zwischen behalten und vermeiden", () => {
    const b = pruefen({ merken: [], behalten: ["Velo"], vermeiden: ["Velo"] });
    expect(b).toHaveLength(1);
    expect(b[0].art).toBe("widerspruch");
  });

  it("hält merken und behalten NICHT für einen Widerspruch", () => {
    /* Beide sagen dasselbe: lass das Wort in Ruhe. Wer „Jänner" merkt und schützt, meint es
     * doppelt und nicht gegensätzlich. */
    expect(pruefen({ merken: ["Jänner"], behalten: ["Jänner"], vermeiden: [] })).toEqual([]);
  });

  it("übergeht leere Einträge", () => {
    expect(pruefen({ ...leer, merken: ["  ", "", "PLACEMedia"] })).toEqual([]);
  });

  it("nennt im Satz beide Listen", () => {
    const b = pruefen({ merken: ["Synergie"], behalten: [], vermeiden: ["Synergie"] });
    const satz = befundSatz(b[0]);
    expect(satz).toContain("So schreiben");
    expect(satz).toContain("Nicht verwenden");
  });

  it("meldet jedes Paar nur einmal", () => {
    const b = pruefen({ merken: ["A"], behalten: ["A"], vermeiden: ["A"] });
    expect(b).toHaveLength(1);
  });
});
