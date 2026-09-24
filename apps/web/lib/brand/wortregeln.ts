/* Wörter und Schreibweisen einer Marke, und was daran nicht zusammenpasst.
 *
 * Drei Listen mit drei verschiedenen Wirkungen standen bisher unbenannt nebeneinander:
 *
 *   merken      Eigennamen und Produkte. Gehen als Hinweis in die Spracherkennung und werden
 *               danach in dieser Schreibweise gesetzt.
 *   behalten    Wörter, die nicht „korrigiert" werden dürfen: Jänner bleibt Jänner.
 *   vermeiden   Formulierungen, die weder im Einstieg noch in den Untertiteln vorkommen sollen.
 *
 * Wer dasselbe Wort in zwei Listen schreibt, bekommt ein Ergebnis, das von der Reihenfolge der
 * Verarbeitung abhängt - also Zufall. Solche Fälle werden hier gefunden und benannt, statt sie
 * still zu verschlucken.
 */

export type Liste = "merken" | "behalten" | "vermeiden";

export const LISTEN_NAME: Record<Liste, string> = {
  merken: "So schreiben",
  behalten: "Nicht verändern",
  vermeiden: "Nicht verwenden",
};

export interface Regeln {
  merken: string[];
  behalten: string[];
  vermeiden: string[];
}

export type Befund =
  | { art: "doppelt"; liste: Liste; wort: string }
  | { art: "widerspruch"; wort: string; hier: Liste; dort: Liste };

/* Vergleich ohne Rücksicht auf Groß- und Kleinschreibung und Randzeichen: „PLACEMedia" und
 * „placemedia," sind dasselbe Wort, und ein Widerspruch bleibt einer, egal wie geschrieben. */
function schluessel(w: string): string {
  return w
    .trim()
    .toLowerCase()
    .replace(/^[„"'(\[]+|[.,;:!?„""'()\]]+$/g, "");
}

export function pruefen(regeln: Regeln): Befund[] {
  const aus: Befund[] = [];
  const gesehen = new Map<string, Liste>();

  for (const liste of ["merken", "behalten", "vermeiden"] as Liste[]) {
    const innerhalb = new Set<string>();
    for (const wort of regeln[liste]) {
      const k = schluessel(wort);
      if (!k) continue;
      if (innerhalb.has(k)) {
        aus.push({ art: "doppelt", liste, wort });
        continue;
      }
      innerhalb.add(k);
      const zuvor = gesehen.get(k);
      /* „So schreiben" und „Nicht verändern" vertragen sich: beide sagen „lass das Wort in
       * Ruhe". Erst mit „Nicht verwenden" wird daraus ein Widerspruch. */
      if (zuvor && (zuvor === "vermeiden" || liste === "vermeiden")) {
        aus.push({ art: "widerspruch", wort, hier: liste, dort: zuvor });
      }
      if (!zuvor) gesehen.set(k, liste);
    }
  }
  return aus;
}

export function befundSatz(b: Befund): string {
  if (b.art === "doppelt") {
    return `„${b.wort}" steht zweimal unter „${LISTEN_NAME[b.liste]}". Einmal reicht.`;
  }
  return `„${b.wort}" steht unter „${LISTEN_NAME[b.hier]}" und unter „${LISTEN_NAME[b.dort]}". Was davon gilt, wäre Zufall.`;
}
