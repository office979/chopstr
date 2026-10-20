/* Eine Stelle im Video als „m:ss“ oder „m:ss,z“.
 *
 * Lag vorher im Lineal der Timeline. Die Timeline ist weg (docs/decisions/050-timeline-entfernen.md),
 * die Zeitangabe wird weiter gebraucht: im Bildausschnitt, in den Belegstellen der Kandidatenliste
 * und unter der Vorschau. */
export function timecode(t: number, mitZehntel = false): string {
  const s = Math.max(0, t);
  if (!mitZehntel) {
    const m = Math.floor(s / 60);
    return `${m}:${String(Math.floor(s - m * 60)).padStart(2, "0")}`;
  }
  /* Gerundet, nicht abgeschnitten: formatClipDuration rundet auch, und dieselbe Zahl soll an zwei
   * Stellen gleich aussehen. Gerundet wird auf Zehntel in EINEM Schritt, bevor Minuten und
   * Sekunden entstehen: sonst ergäbe 59,96 s die Anzeige „0:60,0“ statt „1:00,0“. */
  const zehntel = Math.round(s * 10);
  const ganzeSekunden = Math.floor(zehntel / 10);
  return `${Math.floor(ganzeSekunden / 60)}:${String(ganzeSekunden % 60).padStart(2, "0")},${zehntel % 10}`;
}
