/* Dieselbe Schreibweise an allen anderen Stellen.
 *
 * Ein Eigenname, den die Spracherkennung falsch hört, steht im ganzen Video falsch. Vierzig Mal
 * von Hand ist der Punkt, an dem Leute aufhören zu korrigieren und mit falschen Untertiteln leben.
 */

import { describe, expect, it } from "vitest";
import { ersetzungFuer, kern, nachfrageSatz, weitereStellen } from "@/lib/transcript/vorkommen";

const w = (...t: string[]) => t.map((text) => ({ text }));

describe("dieselbe Stelle wiederfinden", () => {
  it("findet dasselbe Wort weiter hinten", () => {
    expect(weitereStellen(w("Placemedia", "macht", "Videos", "bei", "Placemedia"), 0, "Placemedia")).toEqual([4]);
  });

  it("stört sich nicht an Satzzeichen", () => {
    /* „Placemedia," und „Placemedia" sind dasselbe Wort an zwei Stellen. */
    expect(weitereStellen(w("Placemedia", "und", "Placemedia,", "ja"), 0, "Placemedia")).toEqual([2]);
  });

  it("stört sich nicht an Groß- und Kleinschreibung", () => {
    expect(weitereStellen(w("Placemedia", "bei", "placemedia"), 0, "Placemedia")).toEqual([2]);
  });

  it("überfährt keine Stelle, an der jemand schon von Hand entschieden hat", () => {
    expect(weitereStellen(w("Test", "Test", "Test"), 0, "Test", [1])).toEqual([2]);
  });

  it("zählt die eigene Stelle nicht mit", () => {
    expect(weitereStellen(w("Test", "eins"), 0, "Test")).toEqual([]);
  });

  it("findet nichts zu einem leeren Wort", () => {
    expect(weitereStellen(w(",", "."), 0, ",")).toEqual([]);
  });
});

describe("die Ersetzung an der einzelnen Stelle", () => {
  it("behält das Satzzeichen dieser Stelle", () => {
    expect(ersetzungFuer("Placemedia,", "Placemedia GmbH")).toBe("Placemedia GmbH,");
    expect(ersetzungFuer("Placemedia?", "Placemedia GmbH")).toBe("Placemedia GmbH?");
  });

  it("behält ein Anführungszeichen davor", () => {
    expect(ersetzungFuer("„Placemedia“", "Placemedia GmbH")).toBe("„Placemedia GmbH“");
  });

  it("lässt ein Wort ohne Satzzeichen unangetastet", () => {
    expect(ersetzungFuer("Placemedia", "Placemedia GmbH")).toBe("Placemedia GmbH");
  });

  it("trennt Wort und Rand richtig", () => {
    expect(kern("„Hallo!“")).toBe("Hallo");
  });
});

describe("die Nachfrage", () => {
  it("nennt die Zahl, damit niemand blind zustimmt", () => {
    expect(nachfrageSatz(12, "Hannes", "Johannes")).toContain("12 weiteren Stellen");
    expect(nachfrageSatz(1, "Hannes", "Johannes")).toContain("einer weiteren Stelle");
  });

  it("setzt deutsche Anführungszeichen", () => {
    /* Ein gerades Zeichen am Ende sieht nach Programmcode aus. */
    expect(nachfrageSatz(3, "Hannes", "Johannes")).toBe(
      "„Hannes“ steht noch an 3 weiteren Stellen. Auch dort zu „Johannes“ ändern?",
    );
  });
});
