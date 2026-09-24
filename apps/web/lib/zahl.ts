/* Zahlen aus fremder Hand.
 *
 * Die naheliegende Abkuerzung ueber ``Number(x)`` ist an einer Schnittstelle falsch, und zwar
 * zweimal falsch:
 *
 *   Number(null)  === 0      ein fehlender Wert wird zu einer Zahl
 *   Number([])    === 0      dasselbe fuer eine leere Liste
 *   Number(true)  === 1      ein Schalter wird zu einer Zahl
 *   Math.min(180, NaN) === 180   jeder Vergleich mit NaN ist falsch, der Wert kaeme durch
 *
 * Das ist in diesem Projekt schon zweimal passiert (Untertitel-Groesse, Zeitmarken), beide Male
 * mit demselben Ergebnis: aus Unsinn wurde stillschweigend ein gueltiger Wert. Deshalb steht die
 * Pruefung jetzt an einer Stelle statt an jeder.
 *
 * Python entscheidet an denselben Stellen gleich (``captions_de._zahl_im_rahmen``); ein Test
 * vergleicht die Grenzen beider Seiten miteinander. */

export function alsZahl(wert: unknown): number | null {
  const z = typeof wert === "number" ? wert : typeof wert === "string" && wert.trim() !== "" ? Number(wert) : NaN;
  return Number.isFinite(z) ? z : null;
}

/* Zahl auf einen Bereich ziehen, oder null wenn es keine brauchbare Zahl ist. */
export function zahlImRahmen(wert: unknown, unten: number, oben: number): number | null {
  const z = alsZahl(wert);
  return z == null ? null : Math.round(Math.max(unten, Math.min(oben, z)));
}
