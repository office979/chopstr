/* Gibt es zu diesem Clip ein Video, und wie steht es darum?
 *
 * Hier stand einmal ein Vergleich: entspricht die geclippte Datei noch dem, was eingestellt ist?
 * Wenn nicht, hiess sie „veraltet", und an der Karte stand ein Knopf „Video mit deinen Änderungen
 * neu clippen". Diesen Zwischenzustand gibt es nicht mehr. Speichern clippt sofort neu und
 * überschreibt das Alte; zwischen dem Klick und dem fertigen Video steht „wird geclippt", und
 * danach zeigt die Datei wieder genau das, was eingestellt ist.
 *
 * Damit bleiben vier Zustände, und alle vier hängen nur am Renderlauf - nichts muss mehr
 * verglichen werden.
 */

import type { ClipStatus } from "@/lib/repo/types";

export type VorschauStand = "keine" | "laeuft" | "aktuell" | "fehler";

export interface StandEingabe {
  status: ClipStatus;
  /* Liegt eine geclippte Datei vor? Ohne sie gibt es nichts zu zeigen. */
  hatDatei: boolean;
  renderFehler: string | null;
}

export function vorschauStand(e: StandEingabe): VorschauStand {
  if (e.status === "rendering") return "laeuft";
  if (e.status === "failed") return "fehler";
  return e.hatDatei ? "aktuell" : "keine";
}

/* Ein Satz, der sagt was los ist. Bewusst nicht der Zustandsname allein: „keine" sagt niemandem,
 * was als Nächstes zu tun ist. */
export function standSatz(stand: VorschauStand): string {
  switch (stand) {
    case "laeuft":
      return "Das Video wird gerade geclippt.";
    case "fehler":
      return "Beim Clippen ist etwas schiefgegangen.";
    case "keine":
      return "Es gibt noch keine Videodatei. Links siehst du, wie der Clip aussehen wird.";
    case "aktuell":
      return "Die geclippte Datei zeigt genau das, was eingestellt ist.";
  }
}
