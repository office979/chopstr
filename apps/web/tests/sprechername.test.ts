/* „SPEAKER_00" ist eine Kennung aus der Diarisierung und kein Name. In einem Auswahlfeld, in dem
 * jemand entscheiden soll, wem ein Satz gehört, hilft sie nicht - und sie sieht nach einem
 * Fehler aus. */

import { describe, expect, it } from "vitest";
import { hatEigenenNamen, sprecherName } from "@/lib/transcript/sprechername";

describe("sprecherName", () => {
  it("macht aus der Kennung eine lesbare Nummer, beginnend bei eins", () => {
    expect(sprecherName("SPEAKER_00")).toBe("Sprecher 1");
    expect(sprecherName("SPEAKER_01")).toBe("Sprecher 2");
    expect(sprecherName("SPEAKER_11")).toBe("Sprecher 12");
  });

  it("nimmt den vergebenen Namen, wenn es einen gibt", () => {
    expect(sprecherName("SPEAKER_00", { SPEAKER_00: "Jakob" })).toBe("Jakob");
  });

  it("ignoriert einen leeren Namen", () => {
    expect(sprecherName("SPEAKER_00", { SPEAKER_00: "   " })).toBe("Sprecher 1");
  });

  it("erfindet nichts bei einer unbekannten Form", () => {
    /* Eine Kennung, die wir nicht kennen, umzubenennen hiesse, etwas zu behaupten. */
    expect(sprecherName("Moderator")).toBe("Moderator");
    expect(sprecherName("spk-3")).toBe("spk-3");
  });
});

describe("hatEigenenNamen", () => {
  it("unterscheidet vergeben von hergeleitet", () => {
    expect(hatEigenenNamen("SPEAKER_00", { SPEAKER_00: "Jakob" })).toBe(true);
    expect(hatEigenenNamen("SPEAKER_00", {})).toBe(false);
    expect(hatEigenenNamen("SPEAKER_00", { SPEAKER_00: "" })).toBe(false);
  });
});
