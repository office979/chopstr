import { describe, expect, it } from "vitest";
import { PLATFORM_ASPECT, aspectFor, aspectForSource } from "@/lib/clips/presets";
import type { Platform } from "@/lib/repo/types";

const PLATTFORMEN: Platform[] = ["tiktok", "reels", "shorts", "linkedin"];

describe("aspectForSource", () => {
  it("erkennt die vier unterstützten Seitenverhältnisse exakt", () => {
    expect(aspectForSource(1080, 1920)).toBe("9:16");
    expect(aspectForSource(1080, 1350)).toBe("4:5");
    expect(aspectForSource(1080, 1080)).toBe("1:1");
    expect(aspectForSource(1920, 1080)).toBe("16:9");
  });

  it("erkennt dieselben Verhältnisse auch in anderen Auflösungen", () => {
    expect(aspectForSource(720, 1280)).toBe("9:16");
    expect(aspectForSource(3840, 2160)).toBe("16:9");
    expect(aspectForSource(2160, 2700)).toBe("4:5");
    expect(aspectForSource(500, 500)).toBe("1:1");
  });

  it("rundet krumme Formate auf das nächstgelegene Verhältnis", () => {
    expect(aspectForSource(1920, 1088)).toBe("16:9"); // typische Encoder-Höhe
    expect(aspectForSource(1440, 1080)).toBe("1:1"); // 4:3 liegt näher an 1:1 als an 16:9
    expect(aspectForSource(1080, 1400)).toBe("4:5"); // 0,771 liegt näher an 0,8 als an 0,5625
    expect(aspectForSource(1080, 1600)).toBe("9:16"); // 0,675 liegt noch näher an 0,5625 als an 0,8
    expect(aspectForSource(1080, 1800)).toBe("9:16"); // 0,6 liegt näher an 0,5625
  });

  it("ordnet extreme Formate dem äußersten Verhältnis zu", () => {
    expect(aspectForSource(100, 1000)).toBe("9:16"); // sehr hoch
    expect(aspectForSource(3840, 1080)).toBe("16:9"); // sehr breit (Cinemascope)
  });

  it("liefert null, wenn Maße fehlen", () => {
    expect(aspectForSource(null, null)).toBeNull();
    expect(aspectForSource(undefined, undefined)).toBeNull();
    expect(aspectForSource(1080, null)).toBeNull();
    expect(aspectForSource(null, 1920)).toBeNull();
  });

  it("liefert null bei null, negativen oder unbrauchbaren Maßen", () => {
    expect(aspectForSource(0, 1920)).toBeNull();
    expect(aspectForSource(1080, 0)).toBeNull();
    expect(aspectForSource(0, 0)).toBeNull();
    expect(aspectForSource(-1080, 1920)).toBeNull();
    expect(aspectForSource(1080, -1920)).toBeNull();
    expect(aspectForSource(Number.NaN, 1920)).toBeNull();
    expect(aspectForSource(1080, Number.NaN)).toBeNull();
  });
});

describe("aspectFor", () => {
  it("nimmt standardmäßig das Plattform-Format und ignoriert die Quelle", () => {
    const quelle = { width: 1920, height: 1080 };
    expect(aspectFor("tiktok", quelle)).toBe("9:16");
    expect(aspectFor("reels", quelle)).toBe("9:16");
    expect(aspectFor("shorts", quelle)).toBe("9:16");
    expect(aspectFor("linkedin", quelle)).toBe("4:5");
  });

  it("entspricht für jede Plattform PLATFORM_ASPECT, solange der Schalter aus ist", () => {
    for (const p of PLATTFORMEN) {
      expect(aspectFor(p, { width: 1080, height: 1080 }, false)).toBe(PLATFORM_ASPECT[p]);
      expect(aspectFor(p, null)).toBe(PLATFORM_ASPECT[p]);
    }
  });

  it("übernimmt mit keepSourceAspect=true das Format der Quelle", () => {
    expect(aspectFor("tiktok", { width: 1920, height: 1080 }, true)).toBe("16:9");
    expect(aspectFor("linkedin", { width: 1080, height: 1080 }, true)).toBe("1:1");
    expect(aspectFor("shorts", { width: 1080, height: 1350 }, true)).toBe("4:5");
  });

  it("bleibt beim Plattform-Standard, wenn die Maße der Quelle fehlen", () => {
    for (const p of PLATTFORMEN) {
      expect(aspectFor(p, null, true)).toBe(PLATFORM_ASPECT[p]);
      expect(aspectFor(p, {}, true)).toBe(PLATFORM_ASPECT[p]);
      expect(aspectFor(p, { width: 1920, height: null }, true)).toBe(PLATFORM_ASPECT[p]);
      expect(aspectFor(p, { width: 0, height: 0 }, true)).toBe(PLATFORM_ASPECT[p]);
    }
  });
});
