/* Was an den eingestellten Untertiteln nicht aufgeht.
 *
 * Bisher kam die Warnung „Untertitel laufen schnell durch" aus dem letzten Render und war ein
 * Satz ohne Zeitangabe: man konnte sie lesen, aber nichts damit anfangen. Hier wird dieselbe
 * Rechnung auf den GERADE eingestellten Stil angewendet. Das hat zwei Folgen, die beide zaehlen:
 * die Warnung nennt die Stelle, und sie verschwindet, sobald die Ursache weg ist.
 *
 * Gerechnet wird in Bildpunkten bei 1080x1920, wie ueberall in der Untertitel-Rechnung; der
 * Renderer skaliert das auf die Ausgabegroesse um.
 */

import { maxZeichen, mitVorgabe, type CaptionStyle } from "@/lib/clips/caption-style";
import type { TranscriptWord } from "@/lib/repo/types";

/* Spiegel von captions_de.MAX_CPS. Darueber liest ein Mensch nicht mehr mit. */
export const MAX_CPS = 17;

export interface Karte {
  woerter: TranscriptWord[];
  von: number;
  bis: number;
  text: string;
}

export type Grund = "zu_schnell" | "passt_nicht";

export interface Befund {
  grund: Grund;
  karte: Karte;
  /* Zeichen je Sekunde, nur bei ``zu_schnell``. */
  cps?: number;
}

/* Woerter in Einblendungen gruppieren. Bei fester Wortzahl genau wie der Renderer
 * (captions_de.build_cards); ohne feste Wortzahl eine Naeherung ueber das Zeichenbudget. */
export function karten(woerter: TranscriptWord[], proKarte: number | undefined, budget: number): Karte[] {
  const gruppen: TranscriptWord[][] = [];
  if (proKarte && proKarte > 0) {
    for (let i = 0; i < woerter.length; i += proKarte) gruppen.push(woerter.slice(i, i + proKarte));
  } else {
    let lauf: TranscriptWord[] = [];
    let laenge = 0;
    for (const w of woerter) {
      const n = w.text.length + 1;
      if (lauf.length && laenge + n > budget) {
        gruppen.push(lauf);
        lauf = [];
        laenge = 0;
      }
      lauf.push(w);
      laenge += n;
    }
    if (lauf.length) gruppen.push(lauf);
  }
  return gruppen
    .filter((g) => g.length > 0)
    .map((g) => ({
      woerter: g,
      von: g[0].start,
      bis: g[g.length - 1].end,
      text: g.map((w) => w.text).join(" "),
    }));
}

/* Stellen, an denen die Einstellung nicht aufgeht.
 *
 * ``passt_nicht``: der Text der Karte braucht mehr Zeilen, als erlaubt sind. Der Renderer laesst
 * dann weg, was nicht mehr hineinpasst. Das ist eine Einstellungsfrage und hier zu beheben:
 * mehr Zeilen, kleinere Schrift oder weniger Woerter je Einblendung.
 *
 * ``zu_schnell``: mehr Zeichen je Sekunde, als sich lesen lassen. Achtung, das ist KEINE
 * Einstellungsfrage: die Zahl haengt am Sprechtempo, nicht am Aussehen. Deshalb kommen hier nur
 * die schlimmsten Stellen zurueck, sortiert, und die Oberflaeche zeigt sie als das, was sie sind.
 *
 * Bei EINEM Wort je Einblendung gibt es kein Tempo zu melden: das Wort steht genau so lange, wie
 * es gesprochen wird, und niemand liest voraus. Spiegel von captions_de.cps_warnings. */
export function pruefen(woerter: TranscriptWord[], stil: CaptionStyle): Befund[] {
  const s = mitVorgabe(stil);
  const proZeile = maxZeichen(s.font_px);
  const budget = proZeile * s.max_lines;
  const passtNicht: Befund[] = [];
  const zuSchnell: Befund[] = [];
  for (const k of karten(woerter, s.words_per_card, budget)) {
    const zeichen = (s.all_caps ? k.text.toUpperCase() : k.text).length;
    /* Wie viele Zeilen braucht die Karte? Der Renderer bricht an Wortgrenzen um und trennt lange
     * Komposita; hier reicht die Abschaetzung ueber die Zeichenzahl, denn es geht um die Frage
     * „passt das ueberhaupt", nicht um den genauen Umbruch. */
    if (zeichen > proZeile * s.max_lines) {
      passtNicht.push({ grund: "passt_nicht", karte: k });
      continue;
    }
    if (k.woerter.length < 2) continue;
    const cps = zeichen / Math.max(k.bis - k.von, 0.01);
    if (cps > MAX_CPS) zuSchnell.push({ grund: "zu_schnell", karte: k, cps });
  }
  zuSchnell.sort((a, b) => (b.cps ?? 0) - (a.cps ?? 0));
  return [...passtNicht, ...zuSchnell];
}

/* Das Lesetempo des ganzen Clips. Gebraucht, um die Tempo-Hinweise einzuordnen: liegt schon der
 * Mittelwert deutlich ueber der Grenze, ist nicht eine Stelle zu schnell, sondern der Sprecher
 * zuegig - und dann ist „drei Stellen zu schnell" eine irrefuehrende Aussage. */
export function tempo(woerter: TranscriptWord[], stil: CaptionStyle): { mittel: number; ueberGrenze: boolean } {
  const s = mitVorgabe(stil);
  const k = karten(woerter, s.words_per_card, maxZeichen(s.font_px) * s.max_lines).filter((x) => x.woerter.length >= 2);
  if (!k.length) return { mittel: 0, ueberGrenze: false };
  const werte = k
    .map((x) => (s.all_caps ? x.text.toUpperCase() : x.text).length / Math.max(x.bis - x.von, 0.01))
    .sort((a, b) => a - b);
  const mittel = werte[Math.floor(werte.length / 2)];
  return { mittel, ueberGrenze: mittel > MAX_CPS };
}

export function befundSatz(b: Befund): string {
  if (b.grund === "zu_schnell") {
    return `${Math.round(b.cps ?? 0)} Zeichen je Sekunde, mitlesen lassen sich etwa ${MAX_CPS}.`;
  }
  return "Passt nicht in die erlaubten Zeilen. Was nicht hineinpasst, fehlt im Bild.";
}
