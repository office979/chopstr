/* Eine von Hand getippte Farbe.
 *
 * Der Farbwert stand bisher nur da. Wer die Farbe seiner Marke treffen will, muss sie im Farbrad
 * des Betriebssystems suchen, und mit der Tastatur geht das je nach System gar nicht. Genau das
 * steckt hinter der Meldung „die Farbauswahl ist teilweise nicht benutzbar".
 */

import { describe, expect, it } from "vitest";
import { hexEingabe } from "@/lib/clips/caption-style";

describe("was das Farbfeld annimmt", () => {
  it("nimmt die übliche Schreibweise", () => {
    expect(hexEingabe("#020CF5")).toBe("#020cf5");
  });

  it("nimmt sie auch ohne Raute", () => {
    /* Wer eine Farbe aus einem Styleguide abschreibt, tippt die Raute oft nicht mit. */
    expect(hexEingabe("020cf5")).toBe("#020cf5");
  });

  it("nimmt die Kurzform", () => {
    expect(hexEingabe("#f0a")).toBe("#ff00aa");
    expect(hexEingabe("fff")).toBe("#ffffff");
  });

  it("stört sich nicht an Leerzeichen", () => {
    expect(hexEingabe("  #FFD700 ")).toBe("#ffd700");
  });

  it("gibt null zurück, solange die Eingabe unfertig ist", () => {
    /* Beim Tippen ist jede Zwischenstufe ungültig. Das ist kein Fehler, sondern ein Zwischenstand. */
    expect(hexEingabe("#ff")).toBeNull();
    expect(hexEingabe("")).toBeNull();
    expect(hexEingabe("#ffddgg")).toBeNull();
    expect(hexEingabe("rot")).toBeNull();
  });

  it("liefert immer Kleinschreibung", () => {
    /* Sonst geht der Vergleich mit den Vorschlägen und mit dem Renderplan nicht auf. */
    expect(hexEingabe("#FFD700")).toBe(hexEingabe("#ffd700"));
  });
});
