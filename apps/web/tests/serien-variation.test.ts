/* Die Ähnlichkeitsprüfung einer Serie.
 *
 * Sie darf nur bei einem echten Vergleich anschlagen. Eine Warnung, die bei jedem zweiten Clip
 * kommt, wird weggeklickt; eine, die nie kommt, hätte man sich sparen können. Geprüft wird
 * deshalb beides: dass sie bei wirklich gleichen Clips kommt und dass sie bei verschiedenen
 * schweigt. */

import { describe, expect, it } from "vitest";
import {
  checkVariation,
  clipFeaturesFor,
  COMPARE_LAST,
  FEATURE_LABELS,
  SIMILARITY_THRESHOLD,
  type ClipFeatures,
} from "@/lib/series/variation";
import type { Clip } from "@/lib/repo/types";

const merkmale = (over: Partial<ClipFeatures> = {}): ClipFeatures => ({
  clip_id: "x",
  caption_preset: "tiktok_words",
  hook_pattern: "open_loop",
  structure: "payoff_first",
  duration_s: 40,
  ...over,
});

describe("checkVariation", () => {
  it("schweigt, wenn es nichts zu vergleichen gibt", () => {
    const r = checkVariation(merkmale(), []);
    expect(r.too_similar).toBe(false);
    expect(r.compared).toBe(0);
  });

  it("schlägt an, wenn genug Merkmale übereinstimmen", () => {
    const r = checkVariation(merkmale({ clip_id: "neu" }), [merkmale({ clip_id: "alt" })]);
    expect(r.too_similar).toBe(true);
    expect(r.hits[0].matches.length).toBeGreaterThanOrEqual(SIMILARITY_THRESHOLD);
  });

  it("schweigt bei einem anderen Aufbau und anderer Länge", () => {
    /* Zwei Merkmale gleich reichen nicht: sonst wäre jeder Clip derselben Plattform verdächtig. */
    const r = checkVariation(
      merkmale({ clip_id: "neu", structure: "how_to_list", duration_s: 90 }),
      [merkmale({ clip_id: "alt" })],
    );
    expect(r.too_similar).toBe(false);
  });

  it("hält eine Länge innerhalb von 15 Prozent für gleich", () => {
    const r = checkVariation(merkmale({ clip_id: "neu", duration_s: 44 }), [merkmale({ clip_id: "alt", duration_s: 40 })]);
    expect(r.hits[0]?.matches).toContain("duration");
  });

  it("hält 30 Prozent Unterschied nicht mehr für gleich", () => {
    const r = checkVariation(merkmale({ clip_id: "neu", duration_s: 52 }), [merkmale({ clip_id: "alt", duration_s: 40 })]);
    expect(r.hits[0]?.matches ?? []).not.toContain("duration");
  });

  it("nennt, worin sich die Clips gleichen", () => {
    const r = checkVariation(merkmale({ clip_id: "neu" }), [merkmale({ clip_id: "alt" })]);
    for (const m of r.hits[0].matches) {
      expect(FEATURE_LABELS[m]).toBeTruthy();
    }
  });

  it("beschreibt die Merkmale in verständlichen Worten", () => {
    /* „Caption-Preset" und „Hook-Muster" standen vorher im Warnfenster. */
    for (const wert of Object.values(FEATURE_LABELS)) {
      expect(wert).not.toMatch(/preset|hook|pattern/i);
    }
  });

  it("vergleicht höchstens die letzten neun", () => {
    expect(COMPARE_LAST).toBe(9);
  });
});

describe("clipFeaturesFor", () => {
  it("nimmt die Werte aus Clip, Einstieg und Kandidat", () => {
    const clip = { id: "c1", duration_s: 33, render_plan: { captions: { preset: "reels_clean" } } } as unknown as Clip;
    const f = clipFeaturesFor(clip, "contrarian", "loop");
    expect(f).toMatchObject({ clip_id: "c1", duration_s: 33, hook_pattern: "contrarian", structure: "loop" });
  });
});
