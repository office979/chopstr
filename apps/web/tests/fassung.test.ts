/* Mit welcher Fassung der Marke wurde ein Video geclippt?
 *
 * Der Punkt dieser Tests ist die ehrliche Lücke: für Videos aus der Zeit vor dem Vermerk gibt es
 * keine Zahl, und dann darf auch keine erfunden werden. Eine Eins hinzuschreiben wäre eine
 * Behauptung über etwas, das niemand mehr weiss - und sie würde dem Nutzer sagen „alles in
 * Ordnung", wo in Wahrheit nichts geprüft werden kann.
 */

import { describe, expect, it } from "vitest";
import { fassung, fassungFuerVideo, fassungKurz, fassungSatz } from "@/lib/brand/fassung";

describe("fassung", () => {
  it("nennt ein Video aktuell, wenn die Zahlen gleich sind", () => {
    expect(fassung(4, 4).stand).toBe("aktuell");
  });

  it("nennt ein Video älter, wenn die Marke weitergezählt hat", () => {
    expect(fassung(2, 5).stand).toBe("aelter");
  });

  it("erfindet keine Zahl, wenn nichts vermerkt ist", () => {
    const f = fassung(null, 3);
    expect(f.stand).toBe("unbekannt");
    expect(f.geclipptMit).toBeNull();
  });

  it("behandelt undefined wie fehlend", () => {
    /* Ältere Pläne haben den Block gar nicht. */
    expect(fassung(undefined, 3).stand).toBe("unbekannt");
  });
});

describe("fassungSatz", () => {
  it("schweigt beim aktuellen Stand", () => {
    /* Ein Satz an jedem Video, der „alles in Ordnung" sagt, ist nach dem dritten Video kein
     * Hinweis mehr, sondern Grundrauschen. */
    expect(fassungSatz(fassung(4, 4))).toBeNull();
  });

  it("nennt beide Zahlen und den Weg heraus", () => {
    const satz = fassungSatz(fassung(2, 5));
    expect(satz).toContain("Fassung 2");
    expect(satz).toContain("Fassung 5");
    expect(satz).toMatch(/neu clippen/i);
  });

  it("sagt bei fehlendem Vermerk, dass es ihn nicht gibt", () => {
    const satz = fassungSatz(fassung(null, 5));
    expect(satz).toMatch(/nicht vermerkt/);
    /* Vor allem: keine Zahl, die es nicht gibt. */
    expect(satz).not.toMatch(/Fassung \d/);
  });
});

describe("fassungKurz", () => {
  it("bleibt für eine Plakette kurz", () => {
    expect(fassungKurz(fassung(4, 4))).toBe("Fassung 4");
    expect(fassungKurz(fassung(2, 5))).toBe("Fassung 2 von 5");
    expect(fassungKurz(fassung(null, 5))).toBe("Fassung nicht vermerkt");
  });
});

describe("fassungFuerVideo", () => {
  it("nimmt die älteste Fassung des Videos", () => {
    /* Wer einen von fünf Clips neu clippt, hat danach zwei Fassungen im selben Video. Solange
     * einer hinterherhinkt, ist das Video nicht auf dem neuesten Stand. */
    expect(fassungFuerVideo([5, 2, 5], 5)).toMatchObject({ stand: "aelter", geclipptMit: 2 });
  });

  it("ist aktuell, wenn alle Clips aktuell sind", () => {
    expect(fassungFuerVideo([5, 5], 5).stand).toBe("aktuell");
  });

  it("wird unbekannt, sobald ein Clip keinen Vermerk hat", () => {
    /* Sonst stünde „aktuell" an einem Video, von dem ein Teil ungeprüft ist. */
    expect(fassungFuerVideo([5, null], 5).stand).toBe("unbekannt");
  });

  it("ist ohne Clips nicht aktuell", () => {
    /* Was hier NICHT stehen darf, ist „aktuell": ein Video ohne Clips zeigt keine Marke. */
    expect(fassungFuerVideo([], 5).stand).not.toBe("aktuell");
  });
});

describe("ohne geclippte Clips", () => {
  it("sagt „noch nicht geclippt“ statt „nicht vermerkt“", () => {
    /* Ein Video, an dem noch nie gearbeitet wurde, hat keine alte Fassung, sondern gar keine.
     * „Fassung nicht vermerkt“ klänge nach einem Versäumnis, wo nichts versäumt wurde. */
    const f = fassungFuerVideo([], 3);
    expect(f.stand).toBe("nicht_geclippt");
    expect(fassungKurz(f)).toBe("Noch nicht geclippt");
    expect(fassungSatz(f)).toBeNull();
  });
});
