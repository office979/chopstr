/* Der Schnitt eines Clips. Reine Rechnung, deshalb hier und nicht im Klicktest.
 *
 * Wichtig an allen Tests: die Quelldatei wird nie angefasst. Bearbeitet wird ausschliesslich die
 * Liste der Abschnitte, die der Renderer aneinanderhaengt. */

import { describe, expect, it } from "vitest";
import {
  abschnittBei,
  anfangKuerzen,
  aufraeumen,
  dauer,
  endeKuerzen,
  entfernen,
  gleich,
  inClipzeit,
  inQuellzeit,
  istSichtbar,
  MIN_ABSCHNITT_S,
  randSetzen,
  teilen,
  zusammenziehen,
  type Schnitt,
} from "@/lib/clips/schnitt";

const A = (start: number, end: number) => ({ start, end, role: "body" as const });
const EINER: Schnitt = [A(10, 40)];
const ZWEI: Schnitt = [A(10, 20), A(30, 40)];

describe("dauer", () => {
  it("zählt nur die gezeigten Abschnitte", () => {
    expect(dauer(EINER)).toBe(30);
    expect(dauer(ZWEI)).toBe(20);
  });

  it("ist ohne Abschnitte null", () => {
    expect(dauer([])).toBe(0);
  });
});

describe("Zeitumrechnung", () => {
  it("rechnet Quellzeit in Clipzeit um", () => {
    expect(inClipzeit(ZWEI, 10)).toBe(0);
    expect(inClipzeit(ZWEI, 15)).toBe(5);
    expect(inClipzeit(ZWEI, 30)).toBe(10);
    expect(inClipzeit(ZWEI, 35)).toBe(15);
  });

  it("gibt für eine entfernte Lücke den Anfang des nächsten Abschnitts", () => {
    /* Bei 25 s ist nichts zu sehen; im Clip steht dort die Naht. */
    expect(inClipzeit(ZWEI, 25)).toBe(10);
  });

  it("rechnet zurück", () => {
    for (const t of [0, 3, 10, 15, 19.9]) {
      expect(inClipzeit(ZWEI, inQuellzeit(ZWEI, t))).toBeCloseTo(t, 5);
    }
  });

  it("bleibt am Ende stehen statt darüber hinaus zu laufen", () => {
    expect(inQuellzeit(ZWEI, 999)).toBe(40);
  });
});

describe("istSichtbar", () => {
  it("erkennt die Lücke", () => {
    expect(istSichtbar(ZWEI, 15)).toBe(true);
    expect(istSichtbar(ZWEI, 25)).toBe(false);
    expect(abschnittBei(ZWEI, 35)).toBe(1);
    expect(abschnittBei(ZWEI, 25)).toBe(-1);
  });
});

describe("aufräumen", () => {
  it("wirft zu kurze Abschnitte weg", () => {
    expect(aufraeumen([A(10, 40), A(50, 50.1)])).toEqual([A(10, 40)]);
  });

  it("lässt berührende Abschnitte stehen, denn so sieht ein Teilen aus", () => {
    expect(aufraeumen([A(10, 20), A(20, 30)])).toEqual([A(10, 20), A(20, 30)]);
  });

  it("schneidet eine Überlappung weg, damit keine Stelle zweimal kommt", () => {
    expect(aufraeumen([A(10, 25), A(20, 30)])).toEqual([A(10, 25), A(25, 30)]);
  });

  it("sortiert nach Zeit", () => {
    expect(aufraeumen([A(30, 40), A(10, 20)])).toEqual([A(10, 20), A(30, 40)]);
  });
});

describe("Anfang und Ende kürzen", () => {
  it("kürzt den Anfang", () => {
    expect(anfangKuerzen(EINER, 20)).toEqual([A(20, 40)]);
  });

  it("kürzt das Ende", () => {
    expect(endeKuerzen(EINER, 30)).toEqual([A(10, 30)]);
  });

  it("lässt bei mehreren Abschnitten die davor liegenden ganz weg", () => {
    expect(anfangKuerzen(ZWEI, 32)).toEqual([A(32, 40)]);
    expect(endeKuerzen(ZWEI, 18)).toEqual([A(10, 18)]);
  });

  it("kürzt nicht ins Nichts", () => {
    /* Ein Clip ohne Abschnitte ist kein Clip; das Ergebnis bleibt leer statt unsinnig. */
    expect(anfangKuerzen(EINER, 39.99)).toEqual([]);
  });
});

describe("teilen", () => {
  it("macht aus einem Abschnitt zwei, die aneinander liegen", () => {
    const g = teilen(EINER, 25);
    expect(g).toEqual([A(10, 25), A(25, 40)]);
    /* Teilen allein ändert nichts am Ergebnis: erst das Entfernen macht eine Lücke. */
    expect(dauer(g)).toBe(dauer(EINER));
  });

  it("teilt nicht zu nah an einer Kante", () => {
    expect(teilen(EINER, 10.05)).toEqual(EINER);
    expect(teilen(EINER, 39.95)).toEqual(EINER);
  });

  it("teilt nicht in einer Lücke", () => {
    expect(teilen(ZWEI, 25)).toEqual(ZWEI);
  });
});

describe("entfernen", () => {
  it("lässt den Abschnitt weg und schließt damit die Lücke im Clip", () => {
    const g = teilen(EINER, 25);
    const ohne = entfernen(g, 0);
    expect(ohne).toEqual([A(25, 40)]);
    expect(dauer(ohne)).toBe(15);
  });

  it("behält den letzten Abschnitt", () => {
    /* Sonst bliebe ein Clip ohne Bild übrig. */
    expect(entfernen(EINER, 0)).toEqual(EINER);
  });

  it("übergeht einen unmöglichen Index", () => {
    expect(entfernen(ZWEI, 7)).toEqual(ZWEI);
  });
});

describe("randSetzen", () => {
  it("verschiebt den Anfang eines Abschnitts", () => {
    expect(randSetzen(EINER, 0, 0, 15, 60)).toEqual([A(15, 40)]);
  });

  it("lässt einen Abschnitt nicht in den Nachbarn laufen", () => {
    const g = randSetzen(ZWEI, 0, 1, 35, 60);
    expect(g[0].end).toBe(30);
  });

  it("lässt einen Abschnitt nicht unter die Mindestlänge schrumpfen", () => {
    const g = randSetzen(EINER, 0, 1, 10.01, 60);
    expect(g[0].end - g[0].start).toBeCloseTo(MIN_ABSCHNITT_S, 5);
  });

  it("bleibt in der Quelle", () => {
    const g = randSetzen(EINER, 0, 1, 999, 45);
    expect(g[0].end).toBe(45);
  });
});

describe("gleich", () => {
  it("vergleicht den Inhalt und nicht die Objekte", () => {
    expect(gleich(EINER, [A(10, 40)])).toBe(true);
    expect(gleich(EINER, [A(10, 41)])).toBe(false);
    expect(gleich(EINER, ZWEI)).toBe(false);
  });
});

describe("zusammenziehen", () => {
  it("macht aus einem Teilen ohne Entfernen wieder einen Abschnitt", () => {
    /* Genau so sieht der Renderplan aus, und genau dagegen wird verglichen. */
    expect(zusammenziehen(teilen(EINER, 25))).toEqual(EINER);
  });

  it("lässt eine echte Lücke stehen", () => {
    expect(zusammenziehen(ZWEI)).toEqual(ZWEI);
  });

  it("zieht einen Teaser nicht in den Körper", () => {
    const mit: Schnitt = [{ start: 10, end: 20, role: "teaser" }, A(20, 30)];
    expect(zusammenziehen(mit)).toEqual(mit);
  });
});
