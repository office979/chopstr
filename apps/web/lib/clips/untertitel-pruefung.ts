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

import { GRENZEN, maxZeichen, mitVorgabe, type CaptionStyle } from "@/lib/clips/caption-style";
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

/* Zeichen einer Karte, so wie sie im Bild stehen. Spiegel von captions_de._kartenlaenge. */
function kartenlaenge(gruppe: TranscriptWord[], grossbuchstaben: boolean): number {
  const text = gruppe.map((w) => w.text).join(" ");
  return (grossbuchstaben ? text.toUpperCase() : text).length;
}

/* Eine zu lange Gruppe so aufteilen, dass jeder Teil in die erlaubten Zeilen passt.
 * Spiegel von captions_de._passend_teilen: gierig von links, ein einzelnes zu langes Wort bleibt
 * allein stehen (dafuer gibt es die Silbentrennung). */
function passendTeilen(gruppe: TranscriptWord[], budget: number, grossbuchstaben: boolean): TranscriptWord[][] {
  if (gruppe.length <= 1 || kartenlaenge(gruppe, grossbuchstaben) <= budget) return [gruppe];
  const aus: TranscriptWord[][] = [];
  let lauf: TranscriptWord[] = [];
  for (const w of gruppe) {
    const versuch = [...lauf, w];
    if (lauf.length && kartenlaenge(versuch, grossbuchstaben) > budget) {
      aus.push(lauf);
      lauf = [w];
    } else {
      lauf = versuch;
    }
  }
  if (lauf.length) aus.push(lauf);
  return aus;
}

/* Woerter in Einblendungen gruppieren, genau wie der Renderer (captions_de.build_cards).
 *
 * Die feste Wortzahl ist eine OBERGRENZE: passt eine Gruppe nicht in die erlaubten Zeilen, wird
 * sie geteilt. Beide Seiten muessen dieselbe Rechnung machen, sonst zeigt die Vorschau eine
 * andere Einteilung als das fertige Video. */
export function karten(
  woerter: TranscriptWord[],
  proKarte: number | undefined,
  budget: number,
  grossbuchstaben = false,
): Karte[] {
  const gruppen: TranscriptWord[][] = [];
  if (proKarte && proKarte > 0) {
    for (let i = 0; i < woerter.length; i += proKarte) {
      gruppen.push(...passendTeilen(woerter.slice(i, i + proKarte), budget, grossbuchstaben));
    }
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
 * ``passt_nicht``: ein EINZELNES Wort ist laenger, als in die erlaubten Zeilen passt. Gruppen aus
 * mehreren Woertern werden geteilt (siehe karten), das kann also nur noch ein langes Kompositum
 * sein. Der Renderer trennt es mit Silbentrennung; reicht das nicht, steht es ueber die sichere
 * Flaeche hinaus. Weggelassen wird nichts - das stand hier frueher und war falsch.
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
  for (const k of karten(woerter, s.words_per_card, budget, s.all_caps)) {
    const zeichen = (s.all_caps ? k.text.toUpperCase() : k.text).length;
    /* Nach dem Teilen kann eine Karte nur noch zu lang sein, wenn sie aus einem einzigen Wort
     * besteht. Dann hilft keine andere Einteilung, sondern nur kleinere Schrift oder mehr Zeilen. */
    if (zeichen > proZeile * s.max_lines) {
      if (k.woerter.length <= 1) passtNicht.push({ grund: "passt_nicht", karte: k });
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
  const k = karten(woerter, s.words_per_card, maxZeichen(s.font_px) * s.max_lines, s.all_caps).filter(
    (x) => x.woerter.length >= 2,
  );
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
  return "Dieses Wort ist länger, als in die erlaubten Zeilen passt. Es ragt dann über den sicheren Bereich hinaus.";
}

/* Die eine Einstellung, die alle „passt nicht"-Stellen aufloest.
 *
 * Ein Befund ohne ausfuehrbare Korrektur ist eine Sackgasse: „mehr Zeilen, kleinere Schrift oder
 * weniger Woerter" ueberlaesst dem Nutzer das Ausrechnen. Hier wird ausgerechnet, was reicht.
 *
 * Reihenfolge mit Absicht: erst eine Zeile mehr, dann kleinere Schrift. Verkleinern trifft den
 * ganzen Clip und macht auch die Stellen kleiner, die gepasst haetten; eine Zeile mehr trifft nur
 * die lange Stelle. Nur wenn die Zeilen ausgereizt sind, wird die Schrift angefasst. */
export interface Korrektur {
  feld: "max_lines" | "font_px";
  wert: number;
  /* Beschriftung des Knopfes. */
  label: string;
}

export function korrektur(woerter: TranscriptWord[], stil: CaptionStyle): Korrektur | null {
  const s = mitVorgabe(stil);
  const laengste = pruefen(woerter, stil)
    .filter((b) => b.grund === "passt_nicht")
    .reduce((max, b) => Math.max(max, (s.all_caps ? b.karte.text.toUpperCase() : b.karte.text).length), 0);
  if (laengste === 0) return null;

  const noetigeZeilen = Math.ceil(laengste / maxZeichen(s.font_px));
  if (noetigeZeilen > s.max_lines && noetigeZeilen <= GRENZEN.max_lines[1]) {
    return {
      feld: "max_lines",
      wert: noetigeZeilen,
      label: `${ZEILENWORT[noetigeZeilen] ?? noetigeZeilen} Zeilen erlauben`,
    };
  }

  /* Von der eingestellten Groesse abwaerts die erste, bei der es aufgeht. Schrittweise, weil
   * maxZeichen abrundet: die Umkehrfunktion traefe daneben. */
  for (let px = s.font_px - 1; px >= GRENZEN.font_px[0]; px--) {
    if (maxZeichen(px) * s.max_lines >= laengste) {
      return { feld: "font_px", wert: px, label: `Schrift auf ${px} Punkt verkleinern` };
    }
  }
  return null;
}

const ZEILENWORT: Record<number, string> = { 2: "Zwei", 3: "Drei", 4: "Vier" };
