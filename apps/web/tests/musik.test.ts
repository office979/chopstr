import { describe, expect, it } from "vitest";
import { inClipzeit, type Schnitt } from "@/lib/clips/schnitt";
import {
  AUSBLENDE_S,
  DUCK_ABSENKUNG_DB,
  EINBLENDE_S,
  MAX_DB,
  MIN_DB,
  STANDARD_DB,
  ausDezibel,
  blende,
  duckingSchritt,
  gleich,
  lautstaerkeWort,
  lesen,
  tonLage,
  vorschauPegel,
  type Musik,
} from "@/lib/clips/musik";

const stueck = (teil: Partial<Musik> = {}): Musik => ({
  quelle: "eigen",
  datei: "musik/abc/lied.mp3",
  name: "Lied",
  ab_s: 0,
  lautstaerke_db: STANDARD_DB,
  ducking: true,
  ...teil,
});

describe("lesen", () => {
  it("macht ohne Datei keine Musik", () => {
    expect(lesen(null)).toBeNull();
    expect(lesen({ name: "Lied" })).toBeNull();
    expect(lesen({ datei: "   " })).toBeNull();
  });

  it("hält die Lautstärke in den Grenzen", () => {
    expect(lesen({ datei: "a.mp3", lautstaerke_db: 12 })?.lautstaerke_db).toBe(MAX_DB);
    expect(lesen({ datei: "a.mp3", lautstaerke_db: -90 })?.lautstaerke_db).toBe(MIN_DB);
  });

  it("nimmt Ducking als eingeschaltet, solange niemand es abwählt", () => {
    expect(lesen({ datei: "a.mp3" })?.ducking).toBe(true);
    expect(lesen({ datei: "a.mp3", ducking: false })?.ducking).toBe(false);
  });

  it("lässt den Startpunkt nicht ins Negative", () => {
    expect(lesen({ datei: "a.mp3", ab_s: -4 })?.ab_s).toBe(0);
  });
});

describe("gleich", () => {
  it("merkt eine verschobene Musikspur", () => {
    expect(gleich(stueck(), stueck({ ab_s: 12 }))).toBe(false);
    expect(gleich(stueck(), stueck())).toBe(true);
  });

  it("zählt zwei Nichtse als gleich, eines gegen ein Stück nicht", () => {
    expect(gleich(null, null)).toBe(true);
    expect(gleich(null, stueck())).toBe(false);
  });
});

describe("lautstaerkeWort", () => {
  it("sagt, was ein Dezibelwert bedeutet", () => {
    expect(lautstaerkeWort(STANDARD_DB)).toBe("mittel");
    expect(lautstaerkeWort(-24)).toBe("leise");
    expect(lautstaerkeWort(MIN_DB)).toBe("sehr leise");
    expect(lautstaerkeWort(0)).toBe("sehr laut");
  });
});

describe("ausDezibel", () => {
  it("halbiert bei -6 dB", () => {
    expect(ausDezibel(0)).toBe(1);
    expect(ausDezibel(-6)).toBeCloseTo(0.501, 3);
    expect(ausDezibel(-20)).toBeCloseTo(0.1, 6);
  });
});

describe("blende", () => {
  it("beginnt still und ist nach der Einblende voll da", () => {
    expect(blende(0, 30)).toBe(0);
    expect(blende(EINBLENDE_S / 2, 30)).toBeCloseTo(0.5, 6);
    expect(blende(EINBLENDE_S, 30)).toBe(1);
  });

  it("endet still", () => {
    expect(blende(30, 30)).toBe(0);
    expect(blende(30 - AUSBLENDE_S / 2, 30)).toBeCloseTo(0.5, 6);
    expect(blende(30 - AUSBLENDE_S, 30)).toBeCloseTo(1, 9);
  });

  it("bleibt in den Grenzen, auch ausserhalb des Clips", () => {
    expect(blende(-5, 30)).toBe(0);
    expect(blende(99, 30)).toBe(0);
    expect(blende(15, 0)).toBe(0);
  });

  it("überlagert beide Blenden, wenn der Clip kürzer ist als sie zusammen", () => {
    /* Ein Clip von einer Sekunde ist kürzer als Ein- und Ausblende zusammen (2,0 s). Dann darf
     * nicht eine der beiden gewinnen, sonst stünde die Musik am Ende auf vollem Pegel. */
    const p = blende(0.5, 1);
    expect(p).toBeLessThan(1);
    expect(p).toBeCloseTo(Math.min(0.5 / EINBLENDE_S, 0.5 / AUSBLENDE_S), 6);
  });
});

describe("duckingSchritt", () => {
  it("geht unter der Stimme nach unten und in der Pause wieder herauf", () => {
    let a = 1;
    for (let i = 0; i < 40; i += 1) a = duckingSchritt(a, true, 16);
    expect(a).toBeCloseTo(ausDezibel(DUCK_ABSENKUNG_DB), 3);
    for (let i = 0; i < 400; i += 1) a = duckingSchritt(a, false, 16);
    expect(a).toBeCloseTo(1, 3);
  });

  it("senkt schneller als es wieder hebt", () => {
    const runter = duckingSchritt(1, true, 16);
    const hoch = duckingSchritt(ausDezibel(DUCK_ABSENKUNG_DB), false, 16);
    /* In einem Bild (16 ms) ist der Weg nach unten weit, der Weg nach oben ein Schritt. */
    expect(1 - runter).toBeGreaterThan(hoch - ausDezibel(DUCK_ABSENKUNG_DB));
  });

  it("springt nicht: ein einzelnes Bild erreicht das Ziel nicht", () => {
    expect(duckingSchritt(1, true, 16)).toBeGreaterThan(ausDezibel(DUCK_ABSENKUNG_DB));
  });

  it("steht still, wenn keine Zeit vergangen ist", () => {
    expect(duckingSchritt(0.4, true, 0)).toBe(0.4);
  });
});

describe("vorschauPegel", () => {
  it("nimmt die eingestellte Lautstärke, wo keine Blende und keine Stimme ist", () => {
    expect(vorschauPegel(stueck({ lautstaerke_db: -6 }), 10, 30, 1)).toBeCloseTo(ausDezibel(-6), 6);
  });

  it("lässt die Absenkung weg, wenn sie abgeschaltet ist", () => {
    const aus = stueck({ ducking: false });
    expect(vorschauPegel(aus, 10, 30, 0.3)).toBeCloseTo(ausDezibel(STANDARD_DB), 6);
  });

  it("rechnet die Absenkung ein, wenn sie eingeschaltet ist", () => {
    const an = stueck({ ducking: true });
    expect(vorschauPegel(an, 10, 30, 0.3)).toBeCloseTo(ausDezibel(STANDARD_DB) * 0.3, 6);
  });

  it("ist am Anfang und am Ende des Clips still", () => {
    expect(vorschauPegel(stueck(), 0, 30, 1)).toBe(0);
    expect(vorschauPegel(stueck(), 30, 30, 1)).toBe(0);
  });

  it("bleibt bei 0 dB und ohne Absenkung im zulässigen Bereich", () => {
    expect(vorschauPegel(stueck({ lautstaerke_db: 0, ducking: false }), 15, 30, 1)).toBe(1);
  });
});

describe("tonLage", () => {
  const lage = (teil: Partial<Parameters<typeof tonLage>[0]> = {}) =>
    tonLage({
      musik: stueck({ ab_s: 40 }),
      clipzeit: 10,
      clipDauer: 30,
      spricht: false,
      absenkung: 1,
      dtMs: 16,
      tonZeit: 50,
      tonLaenge: 168,
      ...teil,
    });

  it("legt den eingestellten Startpunkt unter den Clipanfang", () => {
    expect(lage({ clipzeit: 0 }).stelle).toBe(40);
    expect(lage({ clipzeit: 10 }).stelle).toBe(50);
  });

  it("rechnet in Clipzeit, nicht in Quellzeit", () => {
    /* Der Weg, den auch die Vorschau geht: Quellzeit -> Clipzeit -> Stelle im Stück.
     *
     * Aus dem Original sind fünf Sekunden entfernt (20 … 25). Wer bei Sekunde 30 des Originals
     * steht, ist im fertigen Clip erst bei Sekunde 25 - und genau dort muss die Musik stehen. Ohne
     * diese Umrechnung liefe sie um die Länge jeder Lücke voraus. */
    const schnitt: Schnitt = [
      { start: 0, end: 20, role: "body" },
      { start: 25, end: 40, role: "body" },
    ];
    expect(inClipzeit(schnitt, 30)).toBe(25);
    expect(lage({ clipzeit: inClipzeit(schnitt, 30) }).stelle).toBe(65);
    /* Ohne Lücke davor bleibt Quellzeit gleich Clipzeit. */
    expect(lage({ clipzeit: inClipzeit(schnitt, 12) }).stelle).toBe(52);
  });

  it("zieht nicht nach, solange Bild und Ton zusammenlaufen", () => {
    expect(lage({ tonZeit: 50.1 }).nachziehen).toBe(false);
    expect(lage({ tonZeit: 50.2 }).nachziehen).toBe(false);
  });

  it("zieht nach, wenn jemand in der Zeitleiste springt", () => {
    expect(lage({ tonZeit: 12 }).nachziehen).toBe(true);
    expect(lage({ tonZeit: 50.4 }).nachziehen).toBe(true);
  });

  it("hält an, wenn das Stück vor dem Clip endet, statt von vorn zu beginnen", () => {
    const l = lage({ clipzeit: 25, tonLaenge: 60 });
    expect(l.zuEnde).toBe(true);
    expect(l.pegel).toBe(0);
    expect(l.nachziehen).toBe(false);
  });

  it("läuft weiter, solange die Länge des Stücks noch unbekannt ist", () => {
    expect(lage({ tonLaenge: null }).zuEnde).toBe(false);
  });

  it("senkt unter der Stimme und hebt in der Pause", () => {
    let a = 1;
    for (let i = 0; i < 40; i += 1) a = lage({ spricht: true, absenkung: a }).absenkung;
    const leise = lage({ spricht: true, absenkung: a }).pegel;
    for (let i = 0; i < 400; i += 1) a = lage({ spricht: false, absenkung: a }).absenkung;
    const laut = lage({ spricht: false, absenkung: a }).pegel;
    expect(leise).toBeLessThan(laut);
    expect(laut / leise).toBeCloseTo(1 / ausDezibel(DUCK_ABSENKUNG_DB), 1);
  });

  it("lässt die Stimme in Ruhe, wenn die Absenkung abgeschaltet ist", () => {
    const aus = stueck({ ab_s: 40, ducking: false });
    expect(lage({ musik: aus, spricht: true, absenkung: 0.2 }).absenkung).toBe(1);
    expect(lage({ musik: aus, spricht: true, absenkung: 0.2 }).pegel).toBeCloseTo(
      ausDezibel(STANDARD_DB),
      6,
    );
  });

  it("beginnt und endet still, auch mitten im Stück", () => {
    expect(lage({ clipzeit: 0 }).pegel).toBe(0);
    expect(lage({ clipzeit: 30 }).pegel).toBe(0);
  });
});
