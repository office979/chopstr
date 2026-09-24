/* Mit welcher Fassung der Marke wurde ein Video geclippt?
 *
 * Eine Marke ändert sich: neue Farbe, andere Schrift, ein anderes Wort auf der Sperrliste. Jede
 * Änderung zählt die Fassung hoch. Schon geclippte Videos behalten aber ihr Aussehen - das ist
 * Absicht, sonst sähe ein freigegebener Clip über Nacht anders aus als bei der Freigabe.
 *
 * Genau daraus entsteht die Frage, die eine Agentur täglich hat: welches Video zeigt noch die
 * aktuelle Marke, und welches nicht? Ohne Antwort bleiben zwei schlechte Wege: alles neu clippen
 * (teuer und unnötig) oder hoffen (irgendwann fällt es dem Kunden auf).
 *
 * Der Renderlauf vermerkt die Fassung seit render_plan.brand_block im Plan. Für Videos aus der
 * Zeit davor steht dort nichts, und dann ist „nicht vermerkt" die einzige ehrliche Antwort. Eine
 * Eins hinzuschreiben wäre eine Behauptung über etwas, das niemand mehr weiss.
 */

export type FassungStand = "aktuell" | "aelter" | "unbekannt" | "nicht_geclippt";

export interface Fassung {
  stand: FassungStand;
  /* Die Fassung, mit der geclippt wurde. Null, wenn sie nicht vermerkt ist. */
  geclipptMit: number | null;
  /* Die Fassung, die die Marke jetzt hat. */
  jetzt: number;
}

export function fassung(geclipptMit: number | null | undefined, jetzt: number): Fassung {
  if (geclipptMit == null) return { stand: "unbekannt", geclipptMit: null, jetzt };
  /* Grösser als jetzt kann nicht sein, kommt aber vor, wenn jemand eine frühere Fassung
   * wiederherstellt: die Marke zählt dabei weiter hoch, das Video bleibt bei seiner Zahl. Der
   * Vergleich bleibt trotzdem richtig herum - gleich heisst aktuell, alles andere heisst anders. */
  return { stand: geclipptMit === jetzt ? "aktuell" : "aelter", geclipptMit, jetzt };
}

/* Ein Satz dazu, oder null, wenn es nichts zu sagen gibt.
 *
 * Bei „aktuell" steht bewusst nichts: eine Zeile, die an jedem Video „alles in Ordnung" sagt,
 * ist nach dem dritten Video keine Information mehr, sondern Grundrauschen. */
export function fassungSatz(f: Fassung): string | null {
  if (f.stand === "aktuell") return null;
  if (f.stand === "nicht_geclippt") return null;
  if (f.stand === "unbekannt") {
    return "Mit welcher Fassung der Marke dieses Video geclippt wurde, ist nicht vermerkt. Das gilt für Videos von vor dieser Neuerung.";
  }
  return `Geclippt mit Fassung ${f.geclipptMit}, die Marke ist inzwischen bei Fassung ${f.jetzt}. Neu clippen übernimmt die Änderungen.`;
}

/* Dasselbe kurz, für eine Plakette an einer Liste. */
export function fassungKurz(f: Fassung): string {
  if (f.stand === "nicht_geclippt") return "Noch nicht geclippt";
  if (f.stand === "unbekannt") return "Fassung nicht vermerkt";
  if (f.stand === "aktuell") return `Fassung ${f.geclipptMit}`;
  return `Fassung ${f.geclipptMit} von ${f.jetzt}`;
}

/* Der Stand eines ganzen Videos, dessen Clips aus verschiedenen Läufen stammen können.
 *
 * Ein Video hat mehrere Clips, und wer einen davon neu clippt, hat danach zwei Fassungen im
 * selben Video. Für die Übersicht zählt die schlechteste: solange ein Clip hinterherhinkt, ist
 * das Video nicht auf dem neuesten Stand. */
export function fassungFuerVideo(fassungen: (number | null)[], jetzt: number): Fassung {
  /* Kein einziger geclippter Clip: dann gibt es nichts zu vergleichen, und „nicht vermerkt" wäre
   * die falsche Auskunft. Ein Video, an dem noch nie gearbeitet wurde, hat keine alte Fassung,
   * sondern gar keine. */
  if (fassungen.length === 0) return { stand: "nicht_geclippt", geclipptMit: null, jetzt };
  if (fassungen.some((f) => f == null)) return { stand: "unbekannt", geclipptMit: null, jetzt };
  const aelteste = Math.min(...(fassungen as number[]));
  return fassung(aelteste, jetzt);
}
