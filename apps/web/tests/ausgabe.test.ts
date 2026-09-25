/* Die eine Entscheidung: darf diese Fassung hinaus?
 *
 * Der Anlass ist nachlesbar im Code, den diese Tests ersetzen. Die Download-Route prüfte genau
 * eine Sache, nämlich ob eine Gastfreigabe noch aussteht. Ein Schnitt, der eine Verneinung
 * wegschneidet, ein fehlgeschlagener Lauf: alles ging hinaus, sobald man die Adresse kannte. Und die Veröffentlichungsseite prüfte eine Bedingung, die nie fehlschlagen kann.
 *
 * Diese Tests halten fest, was jetzt gilt, und zwar für beide Wege aus derselben Rechnung.
 */

import { describe, expect, it } from "vitest";
import { ausgabe, ausgabeSatz, regelGiltFuer, type AusgabeEingabe, type Zweck } from "@/lib/clips/ausgabe";
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
  const e: PruefstandEingabe = { clip: c, freigabe: null };
  return pruefstand(e);
}

function eingabe(over: Partial<AusgabeEingabe> = {}): AusgabeEingabe {
  return { stand: stand(), technik: null, gastOffen: false, gastNein: false, gastVeraltet: false, ...over };
}

const codes = (zweck: Zweck, e: AusgabeEingabe) =>
  ausgabe(zweck, e).gruende.map((g) => g.code);

describe("ein freigegebener, aktueller Clip darf hinaus", () => {
  it("erlaubt beides", () => {
    const e = eingabe({ vertragUnterschrieben: true, tarifDarfPosten: true });
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
    expect(ausgabe("veroeffentlichen", e).erlaubt).toBe(true);
  });
});

describe("was den Download sperrt, den die alte Route durchgelassen hat", () => {
  /* „Das geclippte Video zeigt nicht mehr, was eingestellt ist" stand hier einmal als eigener
   * Sperrgrund. Den Zustand gibt es nicht mehr: Speichern clippt sofort neu und überschreibt das
   * Alte. Zwischen Klick und fertigem Video greift „clippen_laeuft". */
  it("sperrt den Download, solange noch geclippt wird", () => {
    const p = stand({ status: "rendering", file_key: null });
    expect(p.datei).toBe("wird_erstellt");
    expect(codes("herunterladen", eingabe({ stand: p }))).toContain("clippen_laeuft");
  });

  it("sperrt das Posten eines Schnitts, der eine Verneinung wegschneidet", () => {
    const c = clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: ["nicht"] }] });
    const e = eingabe({ stand: stand({ fidelity_warnings: c.fidelity_warnings }), vertragUnterschrieben: true, tarifDarfPosten: true });
    expect(codes("veroeffentlichen", e)).toContain("inhalt_fehler");
    /* Herunterladen bleibt frei: wer den Schnitt reparieren soll, braucht die Datei. */
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
  });

  it("sperrt einen fehlgeschlagenen Lauf", () => {
    expect(codes("herunterladen", eingabe({ stand: stand({ status: "failed" }) }))).toContain("clippen_gescheitert");
  });

  it("sperrt, solange geclippt wird", () => {
    expect(codes("herunterladen", eingabe({ stand: stand({ status: "rendering" }) }))).toContain("clippen_laeuft");
  });

  it("sperrt das Posten eines verworfenen Vorschlags", () => {
    const e = eingabe({ stand: stand({ review: "verworfen" }), vertragUnterschrieben: true, tarifDarfPosten: true });
    expect(codes("veroeffentlichen", e)).toContain("verworfen");
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
  });

  it("sperrt das Posten einer Datei, die die technische Prüfung nicht bestanden hat", () => {
    const technik: TechnikBefund[] = [
      { pruefung: "ton", ergebnis: "fehler", text: "Die Datei hat keine Tonspur.", gemessen: "0 Spuren" },
    ];
    const e = eingabe({ technik, vertragUnterschrieben: true, tarifDarfPosten: true });
    expect(codes("veroeffentlichen", e)).toContain("technik_fehler");
    /* Herunterladen bleibt frei: wer eine kaputte Datei ansehen soll, braucht sie. */
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
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

describe("die Gastfreigabe sperrt das Posten, nie den Download", () => {
  /* Herunterladen ist kein Veröffentlichen. Wer einen Clip überarbeiten, jemandem zeigen oder
   * auch nur ansehen soll, braucht die Datei - in JEDEM Zustand. Was die Freigabe schützt, ist
   * das Posten. */
  const frei = { vertragUnterschrieben: true, tarifDarfPosten: true };

  it("sperrt das Posten, solange niemand geantwortet hat", () => {
    const e = eingabe({ gastOffen: true, ...frei });
    expect(codes("veroeffentlichen", e)).toContain("gast_offen");
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
  });

  it("sperrt das Posten, wenn die Person nicht zugestimmt hat", () => {
    const e = eingabe({ gastNein: true, ...frei });
    expect(codes("veroeffentlichen", e)).toContain("gast_nein");
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
  });

  it("sperrt das Posten, wenn nach der Freigabe noch geändert wurde", () => {
    /* Die Person hat einer Fassung zugestimmt, die es so nicht mehr gibt. */
    const e = eingabe({ gastVeraltet: true, ...frei });
    expect(codes("veroeffentlichen", e)).toContain("gast_veraltet");
    expect(ausgabe("herunterladen", e).erlaubt).toBe(true);
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
    expect(ausgabe("veroeffentlichen", e).gruende[0].code).toBe("clippen_gescheitert");
  });

  it("gibt zu jedem Grund einen Satz mit Abhilfe", () => {
    const g = ausgabe("herunterladen", eingabe({ stand: stand({ status: "failed" }) })).gruende[0];
    expect(ausgabeSatz(g).length).toBeGreaterThan(20);
    expect(g.hilfe).not.toBe("");
  });
});

describe("der Regelkatalog", () => {
  it("trennt die beiden Wege", () => {
    /* Herunterladen sperrt NUR, was physisch nicht da ist. Alles Redaktionelle, Technische und
     * Rechtliche hängt am Veröffentlichen. */
    for (const code of ["nicht_freigegeben", "technik_fehler", "inhalt_fehler", "gast_offen", "verworfen"] as const) {
      expect(regelGiltFuer(code, "herunterladen"), code).toBe(false);
      expect(regelGiltFuer(code, "veroeffentlichen"), code).toBe(true);
    }
    for (const code of ["datei_fehlt", "clippen_laeuft", "clippen_gescheitert"] as const) {
      expect(regelGiltFuer(code, "herunterladen"), code).toBe(true);
    }
  });
});

describe("nachtragen, dass jemand selbst gepostet hat", () => {
  /* Das ist Buchhaltung und kein Weg nach draussen: die Datei hat chopstr als Download verlassen,
   * und dort galten die Regeln. Hier zu sperren hiesse, eine Tatsache zu verbieten, die schon
   * eingetreten ist - und zwei Seiten, die von diesen Eintragungen leben, blieben leer. */
  it("geht auch ohne Freigabe, ohne Vertrag und ohne passenden Tarif", () => {
    const e = eingabe({
      stand: stand({ review: "offen" }),
      vertragUnterschrieben: false,
      tarifDarfPosten: false,
    });
    expect(ausgabe("veroeffentlichen", e).erlaubt).toBe(false);
    expect(ausgabe("eintragen", e).erlaubt).toBe(true);
  });

  it("geht auch bei offener Gastfrage: gepostet wurde, was damals heruntergeladen wurde", () => {
    const e = eingabe({ gastOffen: true });
    expect(ausgabe("eintragen", e).erlaubt).toBe(true);
  });

  it("geht nicht, wenn es gar kein Video gibt", () => {
    const e = eingabe({ stand: stand({ file_key: null, status: "draft" } as never) });
    expect(codes("eintragen", e)).toContain("datei_fehlt");
  });

  it("geht nicht nach einem fehlgeschlagenen Lauf", () => {
    expect(codes("eintragen", eingabe({ stand: stand({ status: "failed" }) }))).toContain("clippen_gescheitert");
  });
});
