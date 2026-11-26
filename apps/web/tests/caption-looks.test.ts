/* Die zehn Looks: jeder ist gültig, nutzt eine vorhandene Schrift und wird von aktiverLook
 * eindeutig wiedererkannt. Ohne den letzten Punkt springt die Auswahl in der Oberfläche auf
 * einen anderen Look, sobald zwei sich in den LOOK_FELDERN gleichen. */

import { describe, expect, it } from "vitest";
import { aktiverLook, FONTS, LOOKS, mitVorgabe, stilPruefen } from "@/lib/clips/caption-style";

describe("LOOKS", () => {
  it("sind zehn mit eindeutigen ids", () => {
    expect(LOOKS).toHaveLength(10);
    expect(new Set(LOOKS.map((l) => l.id)).size).toBe(10);
  });

  it("nutzen nur Schriften aus caption_fonts.json", () => {
    const ids = new Set(FONTS.map((f) => f.id));
    for (const l of LOOKS) expect(ids.has(mitVorgabe(l.stil).font), `${l.id}: ${l.stil.font}`).toBe(true);
  });

  it("bestehen die Stilprüfung unverändert", () => {
    for (const l of LOOKS) expect(stilPruefen(l.stil), l.id).toEqual(l.stil);
  });

  it("werden von aktiverLook eindeutig wiedererkannt", () => {
    for (const l of LOOKS) expect(aktiverLook(l.stil), l.id).toBe(l.id);
  });
});
