/* Weitere Fassungen desselben Moments.
 *
 * Ein Moment kann in mehreren Formaten hinausgehen: hochkant für TikTok, quadratisch für den Feed,
 * quer für die eigene Website. Was dabei NICHT geht, ist zweimal dasselbe Format. Der Auftrag
 * nennt die Falle beim Namen: „Vermeide identische Exporte mit bloß geändertem Plattformnamen."
 *
 * Bei chopstr sind TikTok, Reels und Shorts alle hochkant. Eine zweite Datei für Reels wäre Bild
 * für Bild dieselbe Datei mit einem anderen Wort im Feld daneben - und der Kunde lädt zweimal
 * dasselbe herunter, in dem Glauben, zwei Fassungen zu haben. Deshalb ist die Einheit hier das
 * FORMAT und nicht die Plattform: nur das Format verändert Bildausschnitt, sicheren Bereich,
 * Schriftgrösse und damit die Datei.
 */

import { ASPECT_SIZE, PLATFORM_ASPECT } from "@/lib/clips/presets";
import { ASPECT_LABELS } from "@/lib/clips/labels";
import type { Aspect, Platform } from "@/lib/repo/types";

export const FASSUNG_FORMATE: Aspect[] = ["9:16", "4:5", "1:1", "16:9"];

/* Wofür ein Format bei den DACH-Plattformen typischerweise taugt. Als Hilfe formuliert und nicht
 * als Regel: wer ein quadratisches Video auf TikTok stellt, macht nichts falsch. */
export const FORMAT_HILFT_BEI: Record<Aspect, string> = {
  "9:16": "TikTok, Reels und Shorts",
  "4:5": "LinkedIn und den Feed von Instagram",
  "1:1": "den Feed und für LinkedIn",
  "16:9": "YouTube und die eigene Website",
};

/* Lässt sich für diesen Moment noch eine Fassung in diesem Format anlegen? */
export function fassungMoeglich(vorhandeneFormate: Aspect[], aspect: Aspect): boolean {
  return !vorhandeneFormate.includes(aspect);
}

/* Die Plattform, für die dieses Format der Standard ist. Für die Fälle, in denen der Aufrufer nur
 * das Format nennt. */
export function plattformFuerFormat(aspect: Aspect): Platform {
  return (Object.keys(PLATFORM_ASPECT) as Platform[]).find((p) => PLATFORM_ASPECT[p] === aspect) ?? "tiktok";
}

export function formatSatz(aspect: Aspect): string {
  const g = ASPECT_SIZE[aspect];
  return `${ASPECT_LABELS[aspect]}, ${g.width} mal ${g.height}`;
}
