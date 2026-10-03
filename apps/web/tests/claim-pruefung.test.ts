/* Claim-Prüfung v2 (AP6a): der Web-Port prüft gegen dieselbe Falldatei wie der Worker.
 *
 * Ein manuell bearbeiteter Hook darf nicht mehr behaupten als der Clip. Der Worker prüft mit
 * fidelity.hook_claim_check_v2, das Web mit hookClaimCheckV2; beide müssen für jeden Fall in
 * packages/editorial/parity/claim_check_v1.json wörtlich dieselben Befunde liefern.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { hookClaimCheck, hookClaimCheckV2, numberMentions } from "@/lib/copy/claims";

interface ParityCase {
  id: string;
  note: string;
  hook: string;
  clip_text: string;
  uncertain_tokens: string[];
  expected_issues: string[];
}

const here = dirname(fileURLToPath(import.meta.url));
const parity = JSON.parse(
  readFileSync(resolve(here, "../../../packages/editorial/parity/claim_check_v1.json"), "utf-8"),
) as { version: string; cases: ParityCase[] };

describe("Parität mit dem Worker", () => {
  it("die Falldatei hat die erwartete Version und Fälle", () => {
    expect(parity.version).toBe("claim_check_v1");
    expect(parity.cases.length).toBeGreaterThanOrEqual(20);
  });

  for (const c of parity.cases) {
    it(`${c.id}: ${c.note}`, () => {
      expect(hookClaimCheckV2(c.hook, c.clip_text, c.uncertain_tokens)).toEqual(c.expected_issues);
    });
  }
});

describe("Zahlen als Wert und Einheit", () => {
  it("„40 Euro“ ist nicht „400.000 Euro“, die alte Prüfung per Teilstring übersieht das", () => {
    expect(hookClaimCheck("40 Euro gespart", "Wir haben 400.000 Euro gespart.")).toEqual([]);
    expect(hookClaimCheckV2("40 Euro gespart", "Wir haben 400.000 Euro gespart.")).toEqual([
      "Zahl '40' (Euro) steht so nicht im Clip",
    ]);
  });

  it("„4“ steckt nicht in „2024“", () => {
    expect(hookClaimCheckV2("4 Tipps", "Das war 2024.")).toHaveLength(1);
  });

  it("„40 %“ und „40 Prozent“ sind dasselbe", () => {
    expect(hookClaimCheckV2("40 % Marge", "Wir haben 40 Prozent Marge verloren.")).toEqual([]);
  });

  it("normalisiert Tausenderpunkt, Leerzeichen, Dezimalkomma und Zahlwörter", () => {
    const m = numberMentions("40.000 Euro, 40 000 Euro, 3,5 Prozent und zwölf Leute");
    expect(m.map((x) => [x.value, x.unit])).toEqual([
      [40000, "EUR"],
      [40000, "EUR"],
      [3.5, "%"],
      [12, "noun:leute"],
    ]);
  });
});

describe("Geltungsbereich und unsichere Zahlen", () => {
  it("„für jeden“ im Hook gegen „bei uns“ im Clip ist ein Befund", () => {
    expect(hookClaimCheckV2("Das hilft für jeden", "Bei uns hat das geholfen.")).toEqual([
      "Geltungsbereich: 'für jeden' im Hook, der Clip schränkt ein ('bei uns')",
    ]);
  });

  it("eine unsicher erkannte Zahl darf nicht in den Hook, auch wenn sie im Clip steht", () => {
    expect(hookClaimCheckV2("40.000 Euro gespart", "Wir haben 40.000 Euro gespart.", ["40.000"])).toHaveLength(1);
    expect(hookClaimCheckV2("40.000 Euro gespart", "Wir haben 40.000 Euro gespart.")).toEqual([]);
  });
});
