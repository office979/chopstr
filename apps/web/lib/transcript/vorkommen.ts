/* Dieselbe Schreibweise an allen anderen Stellen.
 *
 * Ein Eigenname, den die Spracherkennung falsch hört, hört sie im ganzen Video falsch. Bei einem
 * Podcast von einer Stunde steht derselbe Firmenname dann vierzig Mal falsch da, und bisher musste
 * ihn jemand vierzig Mal von Hand anfassen. Genau an dieser Stelle hören Leute auf, das Transkript
 * zu korrigieren, und leben mit falschen Untertiteln.
 *
 * Hier steht die Rechnung dazu: welche anderen Wörter meinen dasselbe, und wie sieht die Korrektur
 * an jeder dieser Stellen aus. Bewusst als reine Funktion, damit sie prüfbar ist und nicht im
 * Editor versteckt liegt.
 */

export interface Wortartig {
  text: string;
}

/* Satzzeichen am Ende gehören zum Satz, nicht zum Wort. „Placemedia," und „Placemedia" sind
 * dasselbe Wort an zwei Stellen, und wer das nicht trennt, findet die Hälfte nicht. */
const RAND = /^[«»„“”"'(\[]+|[.,;:!?…»«„“”"'\)\]]+$/g;

export function kern(text: string): string {
  return text.replace(RAND, "");
}

function schluessel(text: string): string {
  return kern(text).toLocaleLowerCase("de-AT");
}

/* Die anderen Stellen, an denen dasselbe Wort steht.
 *
 * ``ausser`` sind die Stellen, an denen schon jemand von Hand etwas geändert hat: eine
 * Sammelkorrektur darf eine einzelne Entscheidung nicht überfahren. */
export function weitereStellen(
  woerter: Wortartig[],
  index: number,
  altText: string,
  ausser: Iterable<number> = [],
): number[] {
  const gesucht = schluessel(altText);
  if (!gesucht) return [];
  const geschuetzt = new Set(ausser);
  const out: number[] = [];
  for (let i = 0; i < woerter.length; i += 1) {
    if (i === index || geschuetzt.has(i)) continue;
    if (schluessel(woerter[i].text) === gesucht) out.push(i);
  }
  return out;
}

/* Wie das Wort an einer bestimmten Stelle nach der Korrektur heisst.
 *
 * Die Satzzeichen dieser Stelle bleiben stehen: „Placemedia," wird zu „Placemedia GmbH," und nicht
 * zu „Placemedia GmbH". Ein Komma zu verlieren ist ein kleiner Fehler, aber es ist einer. */
export function ersetzungFuer(vorhanden: string, neuerKern: string): string {
  const roh = kern(vorhanden);
  const vorne = vorhanden.slice(0, vorhanden.indexOf(roh));
  const hinten = vorhanden.slice(vorhanden.indexOf(roh) + roh.length);
  return `${vorne}${kern(neuerKern)}${hinten}`;
}

/* Der Satz für die Nachfrage. Mit Zahl, weil „auch anderswo" niemandem sagt, worauf er sich
 * einlässt. */
export function nachfrageSatz(anzahl: number, alt: string, neu: string): string {
  const a = kern(alt);
  const n = kern(neu);
  return anzahl === 1
    ? `„${a}" steht noch an einer weiteren Stelle. Auch dort zu „${n}" ändern?`
    : `„${a}" steht noch an ${anzahl} weiteren Stellen. Auch dort zu „${n}" ändern?`;
}
