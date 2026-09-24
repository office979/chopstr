/* Thema und Einstieg aus rohem Transkripttext. Reine Rechnung, deshalb hier. */

import { describe, expect, it } from "vitest";
import { fortsetzung, thema } from "@/lib/clips/karten-text";

describe("thema", () => {
  it("wirft das Sprecherpräfix weg", () => {
    /* „SPEAKER_00" ist eine Kennung aus der Diarisierung und kein Name. In einer
     * Ergebnisübersicht hat sie nichts verloren. */
    expect(thema("SPEAKER_00: Recruiting ist keine Kostenstelle.")).toBe("Recruiting ist keine Kostenstelle.");
  });

  it("räumt Füllwörter am Anfang weg", () => {
    expect(thema("SPEAKER_01: Ja, ähm, das ist halt der Denkfehler.")).toBe("Das ist halt der Denkfehler.");
  });

  it("lässt Modalpartikel mitten im Satz stehen", () => {
    /* „halt" und „eigentlich" tragen Bedeutung; sie zu streichen wäre Umschreiben und nicht
     * Aufräumen. Gestrichen wird nur, was nichts sagt. */
    expect(thema("Das ist halt der Punkt.")).toContain("halt");
  });

  it("nimmt den ersten Satz und nicht den ganzen Absatz", () => {
    expect(thema("Erster Satz hier. Zweiter Satz da.")).toBe("Erster Satz hier.");
  });

  it("bricht nicht an einer Abkürzung", () => {
    expect(thema("Das kostet ca. 14.000 Euro im Monat. Und das merkt niemand.")).toBe(
      "Das kostet ca. 14.000 Euro im Monat.",
    );
  });

  it("kürzt lange Sätze an einer Wortgrenze", () => {
    const lang = "Eine unbesetzte Stelle im Vertrieb kostet ein mittelständisches Unternehmen im Schnitt vierzehntausend Euro pro Monat.";
    const t = thema(lang, 60);
    expect(t.length).toBeLessThanOrEqual(64);
    /* Mit Leerzeichen vor den Auslassungspunkten: sie stehen für weggelassene Wörter, nicht für
     * ausgelassene Buchstaben. */
    expect(t.endsWith(" …")).toBe(true);
    expect(t).not.toMatch(/[,;:]\s…$/);
  });

  it("kommt mit leerem Text zurecht", () => {
    expect(thema("")).toBe("Ohne Text");
    expect(thema("   ")).toBe("Ohne Text");
  });

  it("beginnt groß, auch wenn das erste Wort weggefallen ist", () => {
    expect(thema("ähm also recruiting kostet Geld.")).toBe("Recruiting kostet Geld.");
  });

  it("enthält nie ein Sprecherpräfix, auch mitten im Text", () => {
    const t = thema("SPEAKER_00: Erstens. SPEAKER_01: Zweitens.", 200);
    expect(t).not.toContain("SPEAKER");
  });
});

describe("fortsetzung", () => {
  it("nimmt, was nach dem ersten Satz kommt", () => {
    expect(fortsetzung("Erster Satz. Und dann kam der zweite.")).toBe("Und dann kam der zweite.");
  });

  it("ist leer, wenn es nur einen Satz gibt", () => {
    expect(fortsetzung("Nur ein Satz.")).toBe("");
  });

  it("wirft auch hier die Sprecherpräfixe weg", () => {
    expect(fortsetzung("SPEAKER_00: Eins. SPEAKER_01: Zwei.")).not.toContain("SPEAKER");
  });
});

/* Interne Angaben gehören nicht in eine Überschrift. In der laufenden Anwendung stand an einer
 * Karte „[33]" und an einer anderen der Sprecherschlüssel - beides sagt niemandem etwas. */
describe("interne Marken", () => {
  it("wirft Klammermarken weg", () => {
    expect(thema("[33] Das ist der Denkfehler.")).toBe("Das ist der Denkfehler.");
  });

  it("wirft den Sprecherschlüssel weg, auch ohne Doppelpunkt", () => {
    expect(thema("SPEAKER_00 Das ist der Denkfehler.")).toBe("Das ist der Denkfehler.");
    expect(thema("SPEAKER_00: Das ist der Denkfehler.")).toBe("Das ist der Denkfehler.");
  });

  it("wirft Anmerkungen der Spracherkennung weg", () => {
    expect(thema("[Musik] Wir haben nachgerechnet.")).toBe("Wir haben nachgerechnet.");
  });

  it("lässt echte Klammerinhalte im Satz nicht stehen bleiben als Lücke", () => {
    /* Kein doppeltes Leerzeichen, kein Komma am Anfang. */
    expect(thema("[33] , und dann kam die Rechnung.")).toBe("Und dann kam die Rechnung.");
  });
});
