/* Thema und Einstieg eines Clips, lesbar gemacht.
 *
 * In der Übersicht stand bisher die Form des Clips als Überschrift („Pointe am Anfang",
 * „Eine Entscheidung") und darunter ein roher Ausschnitt aus dem Transkript, mitsamt „ähm" und
 * „halt". Beides half beim Suchen nicht: die Form sagt nichts über den Inhalt, und roher
 * gesprochener Text liest sich nicht.
 *
 * Erfunden wird hier nichts. Thema und Einstieg kommen aus dem, was im Clip gesagt wird; nur
 * Sprecherpräfixe, Füllwörter und Wiederholungen fallen weg.
 */

import { HARD_FILLERS, normalize, SOFT_FILLERS } from "@/lib/transcript/fillers";

/* Das Präfix der Spracherkennung. In einer Ergebnisübersicht hat es nichts verloren: „SPEAKER_00"
 * ist eine Kennung aus der Diarisierung und kein Name.
 *
 * Die Klammern gehören dazu. Der Worker schreibt die Kennung je nach Stelle als „SPEAKER_00:",
 * als „[SPEAKER_00]" oder als „(SPEAKER_00)" - und genau die runde Form stand weiter in den
 * Überschriften, weil dieser Ausdruck sie nicht kannte. Ein Clip hiess dann „(SPEAKER_00) Wenn du
 * jetzt Menschen einen Shortcut quasi gibst". */
const SPRECHER = /(^|\s)[([]?SPEAKER_\d+[)\]]?:?\s*/gi;

/* Interne Marken in eckigen Klammern: [33], [SPEAKER_01], [inaudible], [Musik].
 *
 * Woher sie kommen, ist von Fall zu Fall verschieden - Wortindizes, Sprecherwechsel, Anmerkungen
 * der Spracherkennung. Was sie gemeinsam haben: sie sind für die Maschine geschrieben. In einer
 * Überschrift, an der ein Mensch einen Clip wiedererkennen soll, steht „[33]" einfach im Weg. */
const MARKEN = /\[[^\]]{0,40}\]/g;

function saeubern(text: string): string {
  return text
    .replace(MARKEN, " ")
    .replace(SPRECHER, " ")
    .replace(/\s+/g, " ")
    .replace(/^[\s,;:.–-]+/, "")
    .trim();
}

/* Füllwörter am Anfang weg: „Ja, ähm, das ist halt der Denkfehler" wird zu „Das ist der
 * Denkfehler". Nur am Anfang und nur harte Füllwörter mitten im Satz - wer „genau" mittendrin
 * sagt, meint es oft. */
function ohneFueller(text: string): string {
  const woerter = text.split(" ");
  let i = 0;
  while (i < woerter.length) {
    const w = normalize(woerter[i]).replace(/[,.!?]+$/, "");
    if (HARD_FILLERS.has(w) || SOFT_FILLERS.has(w) || w === "ja" || w === "okay" || w === "") i += 1;
    else break;
  }
  const rest = woerter.slice(i).filter((w) => !HARD_FILLERS.has(normalize(w).replace(/[,.!?]+$/, "")));
  const zusammen = rest.join(" ").replace(/\s+([,.!?])/g, "$1").replace(/^[,\s]+/, "");
  return zusammen.charAt(0).toUpperCase() + zusammen.slice(1);
}

/* Abkürzungen, deren Punkt keinen Satz beendet. Kurz gehalten: was hier fehlt, führt zu einem zu
 * frühen Schnitt, und das fällt in der Übersicht sofort auf. */
const ABKUERZUNGEN = new Set([
  "ca", "bzw", "usw", "usf", "z", "b", "d", "h", "evtl", "ggf", "inkl", "exkl", "max", "min",
  "mio", "mrd", "nr", "s", "sog", "u", "a", "vgl", "zzgl", "abzgl", "dr", "prof", "bspw",
]);

/* Der erste Satz.
 *
 * Ein Punkt beendet einen Satz nur, wenn danach etwas Neues anfängt. „ca. 14.000 Euro" enthält
 * zwei Punkte, aber keinen Satzschluss: der eine steht hinter einer Abkürzung, der andere in
 * einer Zahl. Beides zu übersehen hiesse, das Thema mitten im Wort abzuschneiden. */
function ersterSatz(text: string): string {
  for (let i = 0; i < text.length; i += 1) {
    const z = text[i];
    if (z !== "." && z !== "!" && z !== "?") continue;
    const davor = text.slice(0, i);
    const danach = text.slice(i + 1);
    /* Zahl mit Punkt: 14.000 */
    if (z === "." && /\d$/.test(davor) && /^\d/.test(danach)) continue;
    /* Abkürzung: das letzte Wort davor steht in der Liste */
    const letztes = (/([A-Za-zÄÖÜäöüß]+)$/.exec(davor)?.[1] ?? "").toLowerCase();
    if (z === "." && ABKUERZUNGEN.has(letztes)) continue;
    /* Danach muss ein Satz anfangen: Leerzeichen und ein Grossbuchstabe, oder Textende. */
    if (danach.trim() === "") return text.slice(0, i + 1).trim();
    if (/^\s+[A-ZÄÖÜ"„(]/.test(danach)) return text.slice(0, i + 1).trim();
  }
  return text.trim();
}

function kuerzen(text: string, max: number): string {
  if (text.length <= max) return text;
  const schnitt = text.slice(0, max);
  const luecke = schnitt.lastIndexOf(" ");
  return `${(luecke > max * 0.6 ? schnitt.slice(0, luecke) : schnitt).replace(/[,;:\s]+$/, "")} …`;
}

/* Worum es geht, in einer Zeile. Der erste Satz des Clips, von Füllwörtern befreit und gekürzt. */
export function thema(text: string, max = 72): string {
  const sauber = saeubern(text);
  if (!sauber) return "Ohne Text";
  return kuerzen(ohneFueller(ersterSatz(sauber)), max) || "Ohne Text";
}

/* Wie er weitergeht. Was nach dem ersten Satz kommt, damit die Karte mehr zeigt als die
 * Überschrift; ist danach nichts mehr, bleibt es beim Thema. */
export function fortsetzung(text: string, max = 130): string {
  const sauber = saeubern(text);
  const erster = ersterSatz(sauber);
  const rest = sauber.slice(erster.length).trim();
  return rest ? kuerzen(ohneFueller(rest), max) : "";
}
