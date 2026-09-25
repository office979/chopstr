/* „Ich komme aus einem Clip zurück" - und nur dann gilt der gemerkte Filter.
 *
 * Die Clip-Liste merkt sich Filter, Auswahl und Scrollstand. Das ist richtig, wenn jemand einen
 * Clip öffnet und zurückkommt: er soll dort weitermachen, wo er war, und nicht die Stelle von Hand
 * wiedersuchen.
 *
 * Es ist falsch, wenn jemand frisch auf die Seite kommt. Dann sieht er die Auswahl von vorhin -
 * etwa „Fehler beheben (2)" - und damit zwei von drei Clips, ohne zu wissen warum. Die Seite
 * heisst „Clips prüfen" und soll mit allen anfangen.
 *
 * Deshalb hinterlässt die Clip-Seite beim Zurückgehen diese Notiz, und die Liste liest sie genau
 * einmal. Kein Zeitstempel, keine Herkunftsprüfung: eine Notiz, die verbraucht wird. */

const SCHLUESSEL = "chopstr:zurueck-von-clip";

export function rueckwegMerken(sourceId: string): void {
  try {
    sessionStorage.setItem(SCHLUESSEL, sourceId);
  } catch {
    /* Ohne Speicher beginnt die Liste eben bei „Alle". Das ist der harmlosere Fall. */
  }
}

/* Liest die Notiz und verbraucht sie. Ein zweiter Aufruf sagt nein. */
export function kommtVomClip(sourceId: string): boolean {
  try {
    const da = sessionStorage.getItem(SCHLUESSEL) === sourceId;
    if (da) sessionStorage.removeItem(SCHLUESSEL);
    return da;
  } catch {
    return false;
  }
}
