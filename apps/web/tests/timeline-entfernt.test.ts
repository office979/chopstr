import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { BEREICHE } from "@/app/projekte/[id]/clips/[clipId]/ClipDetail";

/* Keine sichtbare Timeline (docs/decisions/050-timeline-entfernen.md): der Clip hat die Reiter
 * Text, Untertitel und Bildausschnitt; Timeline, Effekte, Musik und ihre Routen sind weg; die
 * Produktseite verspricht kein Zurechtziehen von Anfang und Ende mehr. */

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

describe("Clip ohne Timeline", () => {
  it("bietet nur Korrekturen ohne Timeline an", () => {
    expect(BEREICHE.map((b) => b.id)).toEqual(["text", "untertitel", "bildausschnitt"]);
    expect(BEREICHE.map((b) => b.name).join(" ")).not.toMatch(/Schnitt|Timeline/);
  });

  it("die Routen und Bausteine der Timeline gibt es nicht mehr", () => {
    for (const weg of [
      "app/api/projects/[id]/clips/[clipId]/schnitt/route.ts",
      "app/api/projects/[id]/clips/[clipId]/effekte/route.ts",
      "app/api/projects/[id]/clips/[clipId]/musik/route.ts",
      "app/api/projects/[id]/clips/[clipId]/musik/datei/route.ts",
      "app/projekte/[id]/clips/[clipId]/timeline/Timeline.tsx",
      "app/projekte/[id]/clips/[clipId]/EffektListe.tsx",
      "app/projekte/[id]/clips/[clipId]/MusikListe.tsx",
      "lib/clips/schnitt.ts",
      "lib/clips/effekte.ts",
      "lib/clips/musik.ts",
    ]) {
      expect(existsSync(resolve(root, weg)), weg).toBe(false);
    }
  });
});

describe("Produkttexte", () => {
  const produkt = readFileSync(resolve(root, "app/produkt/page.tsx"), "utf8");
  const mockup = readFileSync(resolve(root, "components/landing/ProductMockup.tsx"), "utf8");

  it("verspricht kein Zurechtziehen von Anfang und Ende", () => {
    expect(produkt).not.toMatch(/zurecht/);
    expect(mockup).not.toMatch(/>Länger<|>Kürzer<|>Nehmen</);
  });

  it("die Begründung, die „Jede Auswahl erklärt“ verspricht, steht an der Karte", () => {
    expect(produkt).toMatch(/Jede Auswahl erklärt/);
    const karte = readFileSync(resolve(root, "app/projekte/[id]/clips/CandidateReview.tsx"), "utf8");
    expect(karte).toMatch(/Warum dieser Clip\?/);
    expect(karte).toMatch(/candidate\.why/);
  });
});
