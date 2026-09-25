/* Die drei Zustandsachsen der Prüfseite.
 *
 * Der Anlass war ein Bild aus der laufenden Anwendung: an drei von drei Clips stand
 * „Korrektur nötig“, und daneben war „Freigeben“ anklickbar. Ein Zustand, der drei verschiedene
 * Fragen gleichzeitig beantworten soll, beantwortet keine davon. Diese Tests halten die drei
 * Achsen auseinander und prüfen vor allem das, was sie zusammen ergeben: darf das raus?
 */

import { describe, expect, it } from "vitest";
import {
  aktionStand,
  hauptaktion,
  passtZuFilter,
  pruefstand,
  rang,
  type PruefstandEingabe,
} from "@/lib/clips/pruefstand";
import type { Clip, GuestApproval, RenderPlan } from "@/lib/repo/types";
import { assFarbe, LOOKS, mitVorgabe } from "@/lib/clips/caption-style";

const STIL = LOOKS[0].stil;
const SEGMENTE = [{ start: 10, end: 40, role: "body" as const }];

/* Ein Plan, der genau zum eingestellten Stil passt. Nur dann ist die Datei „aktuell“; alles
 * andere wäre ein veraltetes Video, und das ist ein eigener Fall. */
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
    review: "offen",
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

function eingabe(over: Partial<PruefstandEingabe> = {}): PruefstandEingabe {
  const c = over.clip ?? clip();
  return {
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
    ...over,
  };
}

describe("die drei Achsen sind unabhängig", () => {
  it("nennt einen unangetasteten Vorschlag beim Namen", () => {
    const p = pruefstand(eingabe());
    expect(p.redaktion).toBe("vorgeschlagen");
    expect(p.qualitaet).toBe("ok");
    expect(p.datei).toBe("aktuell");
  });

  it("unterscheidet einen angefassten Clip vom rohen Vorschlag", () => {
    expect(pruefstand(eingabe({ bearbeitet: true })).redaktion).toBe("in_arbeit");
  });

  it("lässt einen freigegebenen Clip trotzdem eine veraltete Datei haben", () => {
    /* Genau das ging vorher nicht: ein Zustand musste sich für eines von beidem entscheiden. */
    const c = clip({ review: "bereit", composition: [{ start: 10, end: 25, role: "body" }] });
    const p = pruefstand(eingabe({ clip: c }));
    expect(p.redaktion).toBe("freigegeben");
    expect(p.datei).toBe("veraltet");
  });

  it("hält zügiges Sprechen für einen Hinweis, nicht für einen Fehler", () => {
    const p = pruefstand(eingabe({ clip: clip({ cps_warnings: ["Zu schnell (38 Z/s): 'Der Betrieb mit'"] }) }));
    expect(p.qualitaet).toBe("hinweis");
  });

  it("hält eine weggeschnittene Verneinung für einen Fehler", () => {
    /* Dann sagt der Clip etwas anderes als der Sprecher. Das ist kein Schönheitsfehler. */
    const c = clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: ["nicht"] }] });
    expect(pruefstand(eingabe({ clip: c })).qualitaet).toBe("fehler");
  });

  it("hält eine weggeschnittene Einschränkung für einen Hinweis", () => {
    const c = clip({ fidelity_warnings: [{ type: "qualifier_removed", severity: "medium", detail: ["meistens"] }] });
    expect(pruefstand(eingabe({ clip: c })).qualitaet).toBe("hinweis");
  });
});

describe("Bereit zum Posten", () => {
  it("gilt nur bei freigegeben, ohne schweren Fehler und mit aktueller Datei", () => {
    expect(pruefstand(eingabe({ clip: clip({ review: "bereit" }) })).postbereit).toBe(true);
  });

  it("gilt nicht ohne Freigabe", () => {
    expect(pruefstand(eingabe()).postbereit).toBe(false);
  });

  it("gilt nicht bei einem schweren Fehler", () => {
    const c = clip({ review: "bereit", fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: [] }] });
    expect(pruefstand(eingabe({ clip: c })).postbereit).toBe(false);
  });

  it("gilt nicht bei veralteter Datei", () => {
    const c = clip({ review: "bereit", composition: [{ start: 10, end: 25, role: "body" }] });
    expect(pruefstand(eingabe({ clip: c })).postbereit).toBe(false);
  });

  it("stört sich nicht an einem blossen Hinweis", () => {
    const c = clip({ review: "bereit", cps_warnings: ["Zu schnell (38 Z/s): 'Der Betrieb mit'"] });
    expect(pruefstand(eingabe({ clip: c })).postbereit).toBe(true);
  });
});

describe("Befunde", () => {
  it("fasst alle Tempowarnungen zu einem Befund zusammen", () => {
    /* „82 Stellen laufen schnell durch“ ist eine Zahl, keine Arbeitsanweisung. */
    const viele = Array.from({ length: 82 }, (_, i) => `Zu schnell (3${i % 9} Z/s): 'Stelle ${i}'`);
    const p = pruefstand(eingabe({ clip: clip({ cps_warnings: viele }) }));
    expect(p.befunde.filter((b) => b.art === "tempo")).toHaveLength(1);
    expect(p.befunde[0].text).not.toMatch(/82/);
  });

  it("nennt den Wortlaut der schlimmsten Stelle", () => {
    const p = pruefstand(eingabe({ clip: clip({ cps_warnings: ["Zu schnell (38 Z/s): 'Der Betrieb mit zwölf'"] }) }));
    expect(p.befunde[0].stelle).toBe("Der Betrieb mit zwölf");
  });

  it("sagt bei einer Treuewarnung, was los ist", () => {
    /* Vorher stand hier „Der Renderlauf hat etwas angemerkt.“ */
    const c = clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: ["nicht"] }] });
    const text = pruefstand(eingabe({ clip: c })).befunde[0].text;
    expect(text).toMatch(/Verneinung/);
    expect(text).not.toMatch(/Renderlauf|negation_removed/);
  });

  it("stellt den Fehler vor den Hinweis", () => {
    const c = clip({
      cps_warnings: ["Zu schnell (38 Z/s): 'x'"],
      fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: [] }],
    });
    expect(pruefstand(eingabe({ clip: c })).befunde[0].schwere).toBe("fehler");
  });
});

describe("gesperrte Handlungen nennen den Grund", () => {
  it("sperrt Freigeben bei einem Fehler am Inhalt", () => {
    const c = clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: [] }] });
    const a = aktionStand("freigeben", pruefstand(eingabe({ clip: c })));
    expect(a.erlaubt).toBe(false);
    expect(a.grund).toMatch(/beheben/);
  });

  it("lässt Freigeben bei einem blossen Hinweis zu", () => {
    const c = clip({ cps_warnings: ["Zu schnell (38 Z/s): 'x'"] });
    expect(aktionStand("freigeben", pruefstand(eingabe({ clip: c }))).erlaubt).toBe(true);
  });

  it("lässt Freigeben trotz veralteter Datei zu", () => {
    /* Die Freigabe ist eine Entscheidung über den Clip, nicht über die Datei. Die Datei wird
     * danach neu gebaut, und „Bereit zum Posten“ kommt erst dann. */
    const c = clip({ composition: [{ start: 10, end: 25, role: "body" }] });
    expect(aktionStand("freigeben", pruefstand(eingabe({ clip: c }))).erlaubt).toBe(true);
  });

  it("sperrt Herunterladen bei veralteter Datei und sagt, was zuerst kommt", () => {
    const c = clip({ review: "bereit", composition: [{ start: 10, end: 25, role: "body" }] });
    const a = aktionStand("herunterladen", pruefstand(eingabe({ clip: c })));
    expect(a.erlaubt).toBe(false);
    expect(a.grund).toMatch(/neu clippen/);
  });

  it("gibt für jede gesperrte Handlung einen Satz", () => {
    /* Ein gesperrter Knopf ohne Begründung ist eine Sackgasse. */
    const faelle = [
      clip({ status: "rendering", file_key: null }),
      clip({ status: "failed", render_error: "ffmpeg brach ab" }),
      clip({ file_key: null }),
      clip({ review: "verworfen" }),
      clip({ composition: [{ start: 10, end: 25, role: "body" }] }),
    ];
    for (const c of faelle) {
      const p = pruefstand(eingabe({ clip: c }));
      for (const id of ["freigeben", "herunterladen", "neu_bauen", "verwerfen"] as const) {
        const a = aktionStand(id, p);
        if (!a.erlaubt) expect(a.grund, `${id} bei ${c.status}/${c.review}`).toBeTruthy();
      }
    }
  });
});

describe("hauptaktion", () => {
  it("führt bei einem Fehler am Inhalt zum Beheben", () => {
    const c = clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: [] }] });
    expect(hauptaktion(pruefstand(eingabe({ clip: c }))).id).toBe("beheben");
  });

  it("führt bei veralteter Datei zum Neubauen", () => {
    const c = clip({ composition: [{ start: 10, end: 25, role: "body" }] });
    expect(hauptaktion(pruefstand(eingabe({ clip: c }))).id).toBe("neu_bauen");
  });

  it("führt bei einem frischen Vorschlag zum Prüfen", () => {
    expect(hauptaktion(pruefstand(eingabe())).id).toBe("pruefen");
  });

  it("führt bei einem fertigen freigegebenen Clip zum Download", () => {
    expect(hauptaktion(pruefstand(eingabe({ clip: clip({ review: "bereit" }) }))).id).toBe("herunterladen");
  });

  it("führt bei einem verworfenen Clip zum Zurückholen", () => {
    expect(hauptaktion(pruefstand(eingabe({ clip: clip({ review: "verworfen" }) }))).id).toBe("zurueckholen");
  });
});

describe("Reihenfolge und Filter", () => {
  it("stellt den Fehler vor die offene Prüfung und die vor das Erledigte", () => {
    const fehler = pruefstand(eingabe({ clip: clip({ fidelity_warnings: [{ type: "negation_removed", severity: "high", detail: [] }] }) }));
    const offen = pruefstand(eingabe());
    const fertig = pruefstand(eingabe({ clip: clip({ review: "bereit" }) }));
    expect(rang(fehler)).toBeLessThan(rang(offen));
    expect(rang(offen)).toBeLessThan(rang(fertig));
  });

  it("versteckt Verworfenes unter „alle“", () => {
    /* Sonst wäre Verwerfen folgenlos. */
    const p = pruefstand(eingabe({ clip: clip({ review: "verworfen" }) }));
    expect(passtZuFilter(p, "alle")).toBe(false);
    expect(passtZuFilter(p, "verworfen")).toBe(true);
  });

  it("findet unter „Bereit zum Posten“ nur das, was wirklich raus kann", () => {
    const fertig = pruefstand(eingabe({ clip: clip({ review: "bereit" }) }));
    const alt = pruefstand(eingabe({ clip: clip({ review: "bereit", composition: [{ start: 10, end: 25, role: "body" }] }) }));
    expect(passtZuFilter(fertig, "postbereit")).toBe(true);
    expect(passtZuFilter(alt, "postbereit")).toBe(false);
  });
});

describe("Gastfreigabe", () => {
  it("zählt als Freigabe", () => {
    const f = { decision: "approved" } as GuestApproval;
    expect(pruefstand(eingabe({ freigabe: f })).redaktion).toBe("freigegeben");
  });

  it("wird an einem veralteten Video nicht angefragt", () => {
    const c = clip({ composition: [{ start: 10, end: 25, role: "body" }] });
    const a = aktionStand("gast_fragen", pruefstand(eingabe({ clip: c })));
    expect(a.erlaubt).toBe(false);
    expect(a.grund).toMatch(/alten Stand/);
  });
});

describe("die Marker aus der Analyse", () => {
  /* Es gab eine fertige Funktion mit ausformulierten Sätzen dafür, warningsOf. Sie hatte keinen
   * einzigen Aufrufer: „Muss als Werbung gekennzeichnet werden" stand in der Datenbank und wurde
   * nirgends angezeigt. */
  const kandidat = (over: Record<string, unknown> = {}) =>
    ({ risk_flags: [], story_graph_flags: [], ...over }) as never;

  it("nennt eine Stelle, die als Werbung gekennzeichnet werden muss", () => {
    const p = pruefstand(eingabe({ kandidat: kandidat({ risk_flags: ["ad"] }) }));
    expect(p.befunde.some((b) => b.art === "pruefen" && b.text.includes("Werbung"))).toBe(true);
    expect(p.qualitaet).toBe("hinweis");
  });

  it("sagt, wenn eine Stelle ohne KI gefunden wurde", () => {
    const p = pruefstand(eingabe({ kandidat: kandidat({ risk_flags: ["heuristic_only"] }) }));
    expect(p.befunde.some((b) => b.text === "Ohne KI gefunden")).toBe(true);
  });

  it("nennt eine spätere Relativierung mit Abstand", () => {
    const p = pruefstand(
      eingabe({ kandidat: kandidat({ story_graph_flags: [{ seconds_after: 12, confirmed: true }] }) }),
    );
    expect(p.befunde.some((b) => b.text.startsWith("Relativierung"))).toBe(true);
  });

  it("sperrt nichts: ein Vorschlag ist zum Ansehen da", () => {
    const p = pruefstand(
      eingabe({ clip: clip({ review: "bereit" }), kandidat: kandidat({ risk_flags: ["ad", "claim"] }) }),
    );
    expect(p.qualitaet).toBe("hinweis");
    expect(p.postbereit).toBe(true);
  });

  it("bleibt still, wenn nichts markiert ist", () => {
    expect(pruefstand(eingabe({ kandidat: kandidat() })).befunde).toHaveLength(0);
  });
});

describe("die technische Prüfung der Datei", () => {
  const mitPruefung = (ergebnis: "ok" | "hinweis" | "fehler", text: string) =>
    eingabe({
      clip: clip({ export_checks: [{ pruefung: "ton", ergebnis, text, gemessen: null }] } as never),
    });

  it("zeigt einen Fehler an der Datei als Befund", () => {
    const p = pruefstand(mitPruefung("fehler", "In der Datei ist keine Tonspur."));
    expect(p.befunde.some((b) => b.art === "technik" && b.schwere === "fehler")).toBe(true);
  });

  it("lässt die Qualitätsachse in Ruhe: ein leiser Ton sagt nichts anderes als der Sprecher", () => {
    const p = pruefstand(mitPruefung("fehler", "In der Datei ist keine Tonspur."));
    expect(p.qualitaet).toBe("hinweis");
  });

  it("zeigt bestandene Prüfungen nicht an", () => {
    expect(pruefstand(mitPruefung("ok", "Die Datei hat Ton.")).befunde).toHaveLength(0);
  });
});
