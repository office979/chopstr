/* Die eine Entscheidung: darf diese Fassung hinaus?
 *
 * Der Anlass ist nachlesbar im Code, den diese Tests ersetzen. Die Download-Route prüfte genau
 * eine Sache, nämlich ob eine Gastfreigabe noch aussteht. Ein veraltetes Video, ein Schnitt, der
 * eine Verneinung wegschneidet, ein fehlgeschlagener Lauf: alles ging hinaus, sobald man die
 * Adresse kannte. Und die Veröffentlichungsseite prüfte eine Bedingung, die nie fehlschlagen kann.
 *
 * Diese Tests halten fest, was jetzt gilt, und zwar für beide Wege aus derselben Rechnung.
 */

import { describe, expect, it } from "vitest";
import { ausgabe, ausgabeSatz, regelGiltFuer, type AusgabeEingabe } from "@/lib/clips/ausgabe";
import { pruefstand, type PruefstandEingabe } from "@/lib/clips/pruefstand";
import type { Clip, RenderPlan, TechnikBefund } from "@/lib/repo/types";
import { assFarbe, LOOKS, mitVorgabe } from "@/lib/clips/caption-style";

const STIL = LOOKS[0].stil;
const SEGMENTE = [{ start: 10, end: 40, role: "body" as const }];

function plan(): RenderPlan {
  const s = mitVorgabe(STIL);
  return {
    contract: "render_plan_v1",
    segments: SEGMENTE,
    zeitmarken: [],
    sources: { storage_key: "x", transcript_version: 3, hook_version: 1, candidate_id: "c" },
    captions: {
      font: s.font,
      font_px: s.font_px,
      words_per_card: s.words_per_card,
      max_lines: s.max_lines,
      outline_px: s.outline_px,
      bold: s.bold,
      all_caps: s.all_caps,
      box: s.box,
      highlight: s.highlight_words,
      base_color: assFarbe(s.base_color),
      highlight_color: assFarbe(s.highlight_color),
      outline_color: assFarbe(s.outline_color),
    },
  } as unknown as RenderPlan;
}

function clip(over: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
    status: "rendered",
    review: "bereit",
    file_key: "clips/c1.mp4",
    render_plan: plan(),
    render_error: null,
    composition: SEGMENTE,
    zeitmarken: [],
    cps_warnings: [],
    fidelity_warnings: [],
    ...over,
  } as unknown as Clip;
}

function stand(over: Partial<Clip> = {}) {
  const c = clip(over);
  const e: PruefstandEingabe = {
    clip: c,
    freigabe: null,
    stand: {
      status: c.status,
      hatDatei: Boolean(c.file_key),
      plan: c.render_plan,
      renderFehler: c.render_error,
      transkriptVersion: 3,
      stil: STIL,
      schnitt: c.composition,
      zeitmarken: c.zeitmarken,
    },
  };
  return pruefstand(e);
}

function eingabe(over: Partial<AusgabeEingabe> = {}): AusgabeEingabe {
  return { stand: stand(), technik: null, gastOffen: false, gastVeraltet: false, ...over };
}

const codes = (zweck: "herunterladen" | "veroeffentlichen", e: AusgabeEingabe) =>
  ausgabe(zweck, e).gruende.map((g) => g.code);

describe("ein freigegebener, aktueller Clip darf hinaus", () => {
  it("erlaubt beides", () => {
    const e = eingabe({ vertragUnterschrieben: true, tarifDarfPosten: true });
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
    expect(ausgabe("veroeffentlichen", e).erlaubt).toBe(true);
  });
});

describe("was den Download sperrt, den die alte Route durchgelassen hat", () => {
  it("sperrt ein veraltetes Video", () => {
    /* Der Text wurde geändert, das Video zeigt noch den alten Stand. */
    const c = clip();
    const p = pruefstand({
      clip: c,
      freigabe: null,
      stand: {
        status: c.status,
        hatDatei: true,
        plan: c.render_plan,
        renderFehler: null,
        transkriptVersion: 4,
        stil: STIL,
        schnitt: c.composition,
        zeitmarken: [],
      },
    });
    expect(p.datei).toBe("veraltet");
    expect(codes("herunterladen", eingabe({ stand: p }))).toContain("datei_veraltet");
  });

  it("sperrt einen Schnitt, der eine Verneinung wegschneidet", () => {
    const c = clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: ["nicht"] }] });
    expect(codes("herunterladen", eingabe({ stand: stand({ fidelity_warnings: c.fidelity_warnings }) }))).toContain(
      "inhalt_fehler",
    );
  });

  it("sperrt einen fehlgeschlagenen Lauf", () => {
    expect(codes("herunterladen", eingabe({ stand: stand({ status: "failed" }) }))).toContain("clippen_gescheitert");
  });

  it("sperrt, solange geclippt wird", () => {
    expect(codes("herunterladen", eingabe({ stand: stand({ status: "rendering" }) }))).toContain("clippen_laeuft");
  });

  it("sperrt einen verworfenen Vorschlag", () => {
    expect(codes("herunterladen", eingabe({ stand: stand({ review: "verworfen" }) }))).toContain("verworfen");
  });

  it("sperrt eine Datei, die die technische Prüfung nicht bestanden hat", () => {
    const technik: TechnikBefund[] = [
      { pruefung: "ton", ergebnis: "fehler", text: "Die Datei hat keine Tonspur.", gemessen: "0 Spuren" },
    ];
    expect(codes("herunterladen", eingabe({ technik }))).toContain("technik_fehler");
  });
});

describe("was nur das Veröffentlichen sperrt", () => {
  it("lässt einen ungeprüften Clip herunterladen, aber nicht posten", () => {
    const e = eingabe({ stand: stand({ review: "offen" }), vertragUnterschrieben: true, tarifDarfPosten: true });
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
    expect(codes("veroeffentlichen", e)).toEqual(["nicht_freigegeben"]);
  });

  it("sperrt ohne Vertrag und ohne passenden Tarif", () => {
    const e = eingabe({ vertragUnterschrieben: false, tarifDarfPosten: false });
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
    expect(codes("veroeffentlichen", e)).toEqual(["vertrag_fehlt", "tarif"]);
  });
});

describe("die Gastfreigabe", () => {
  it("sperrt, solange niemand geantwortet hat", () => {
    expect(codes("herunterladen", eingabe({ gastOffen: true }))).toContain("gast_offen");
  });

  it("sperrt, wenn nach der Freigabe noch geändert wurde", () => {
    /* Die Person hat einer Fassung zugestimmt, die es so nicht mehr gibt. */
    expect(codes("herunterladen", eingabe({ gastVeraltet: true }))).toContain("gast_veraltet");
  });
});

describe("eine fehlende Messung ist kein Befund", () => {
  it("sperrt Videos aus der Zeit vor der technischen Prüfung nicht", () => {
    expect(ausgabe("herunterladen", eingabe({ technik: null })).erlaubt).toBe(true);
  });

  it("ein Hinweis sperrt nicht", () => {
    const technik: TechnikBefund[] = [
      { pruefung: "pegel", ergebnis: "hinweis", text: "Der Ton ist leiser als üblich.", gemessen: "-19,4 LUFS" },
    ];
    expect(ausgabe("herunterladen", eingabe({ technik })).erlaubt).toBe(true);
  });
});

describe("die Reihenfolge der Gründe", () => {
  it("nennt zuerst, was zuerst zu tun ist", () => {
    /* Ein fehlgeschlagener Lauf UND eine offene Gastfreigabe: erst nochmal clippen. */
    const e = eingabe({ stand: stand({ status: "failed" }), gastOffen: true });
    expect(ausgabe("herunterladen", e).gruende[0].code).toBe("clippen_gescheitert");
  });

  it("gibt zu jedem Grund einen Satz mit Abhilfe", () => {
    const g = ausgabe("herunterladen", eingabe({ stand: stand({ status: "failed" }) })).gruende[0];
    expect(ausgabeSatz(g).length).toBeGreaterThan(20);
    expect(g.hilfe).not.toBe("");
  });
});

describe("der Regelkatalog", () => {
  it("trennt die beiden Wege", () => {
    expect(regelGiltFuer("nicht_freigegeben", "herunterladen")).toBe(false);
    expect(regelGiltFuer("nicht_freigegeben", "veroeffentlichen")).toBe(true);
    expect(regelGiltFuer("datei_veraltet", "herunterladen")).toBe(true);
    expect(regelGiltFuer("datei_veraltet", "veroeffentlichen")).toBe(true);
  });
});
