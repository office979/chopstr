/* Welche Untertitel-Schriften liegen wirklich als Datei vor?
 *
 * Die Auswahlliste (packages/design/caption_fonts.json) nennt neun Schriften. Ob eine davon
 * benutzt werden kann, haengt an einer Datei, und die liegt bewusst nicht im Repository:
 * Schriftdateien sind Binaerdateien, und wer sie nicht braucht, soll sie nicht mitladen
 * (workers/fonts/README.md).
 *
 * Ohne diese Pruefung bot die Oberflaeche alle neun an, die Vorschau zeigte eine Ersatzschrift,
 * und der Renderer brannte Inter ein. Der Nutzer stellte also etwas ein, das es nirgends gab.
 *
 * Gelesen wird ``apps/web/public/fonts``: dorthin spiegelt scripts/sync-fonts.mjs die Dateien aus
 * ``workers/fonts``. Was dort liegt, kann der Browser zeigen UND der Renderer einbrennen; alles
 * andere ist fuer diese Installation nicht vorhanden.
 *
 * Nur auf dem Server: ``node:fs`` gibt es im Browser nicht.
 */

import { existsSync } from "node:fs";
import path from "node:path";
import { FONTS } from "@/lib/clips/caption-style";

/* Einmal je Prozess. Schriften kommen nicht im Betrieb dazu, sondern beim Aufsetzen; ein
 * Dateizugriff je Seitenaufruf waere Aufwand ohne Gegenwert. */
let zwischenspeicher: string[] | null = null;

export function vorhandeneSchriften(): string[] {
  if (zwischenspeicher) return zwischenspeicher;
  const ordner = path.join(process.cwd(), "public", "fonts");
  zwischenspeicher = FONTS.filter((f) => existsSync(path.join(ordner, f.datei))).map((f) => f.id);
  return zwischenspeicher;
}
