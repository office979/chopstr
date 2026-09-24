/* Gibt es an der gerade bearbeiteten Marke ungespeicherte Änderungen?
 *
 * Die Frage stellt sich an zwei Stellen, die nichts voneinander wissen: das Formular weiss, dass
 * jemand getippt hat, und die Markenliste darüber weiss, dass jemand auf eine andere Marke
 * klickt. Ohne eine gemeinsame Stelle wechselt die Liste stillschweigend, und die Eingaben sind
 * weg - ohne Meldung, ohne Weg zurück.
 *
 * Bewusst ein Modulwert und kein Context: die beiden Bauteile liegen in verschiedenen Bäumen
 * (die Liste ist eine Serverkomponente), und ein Provider darüber wäre mehr Gerüst als Nutzen.
 */

let offen = false;
const hoerer = new Set<(wert: boolean) => void>();

export function setzeUngespeichert(wert: boolean): void {
  if (offen === wert) return;
  offen = wert;
  for (const h of hoerer) h(wert);
}

export function hatUngespeichert(): boolean {
  return offen;
}

export function beiAenderung(h: (wert: boolean) => void): () => void {
  hoerer.add(h);
  return () => {
    hoerer.delete(h);
  };
}

/* Der Satz, der vor dem Verlassen gefragt wird. An einer Stelle, damit Browserdialog und eigener
 * Dialog dasselbe sagen. */
export const VERLASSEN_FRAGE = "Du hast Änderungen an dieser Marke, die noch nicht gespeichert sind. Trotzdem wechseln?";
