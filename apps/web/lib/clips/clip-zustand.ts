/* Was ist mit diesem Clip los, in einem Wort?
 *
 * Bisher stand in der Übersicht der technische Zustand: „Fertig". Der sagt, dass eine Datei
 * entstanden ist, und sonst nichts. Er stand auch an Clips, deren Untertitel eine Warnung hatten,
 * die niemand angesehen hatte und deren gebautes Video nicht mehr zu den Einstellungen passte.
 *
 * Hier kommen drei Dinge zusammen, die vorher nebeneinander standen: der technische Zustand
 * (läuft ein Render?), der Prüfstand (hat ein Mensch entschieden?) und die Gastfreigabe. Heraus
 * kommt ein Zustand, der sagt, was als Nächstes zu tun ist.
 */

import { vorschauStand, type StandEingabe } from "@/lib/clips/vorschau-stand";
import type { Clip, GuestApproval } from "@/lib/repo/types";

export type ClipZustand = "wird_erstellt" | "fehler" | "korrektur" | "pruefen" | "bereit" | "freigegeben" | "verworfen";

export const ZUSTAND_LABEL: Record<ClipZustand, string> = {
  wird_erstellt: "Wird erstellt",
  fehler: "Hat nicht geklappt",
  korrektur: "Korrektur nötig",
  pruefen: "Bitte prüfen",
  bereit: "Bereit",
  freigegeben: "Freigegeben",
  verworfen: "Verworfen",
};

/* Was als Nächstes zu tun ist. Ein Zustandsname allein sagt niemandem, was er soll. */
export const ZUSTAND_SATZ: Record<ClipZustand, string> = {
  wird_erstellt: "Das Video entsteht gerade.",
  fehler: "Das Erstellen ist fehlgeschlagen.",
  korrektur: "Hier stimmt etwas noch nicht.",
  pruefen: "Ansehen und entscheiden, ob er raus soll.",
  bereit: "Von dir freigegeben, kann veröffentlicht werden.",
  freigegeben: "Von außen freigegeben.",
  verworfen: "Aussortiert. Lässt sich zurückholen.",
};

export interface ZustandEingabe {
  clip: Clip;
  /* Die letzte Gastfreigabe zu diesem Clip, falls es eine gibt. */
  freigabe: GuestApproval | null;
  /* Zeigt die gebaute Datei noch, was eingestellt ist? Aus lib/clips/vorschau-stand. */
  stand: StandEingabe;
}

export function clipZustand({ clip, freigabe, stand }: ZustandEingabe): ClipZustand {
  if (clip.review === "verworfen") return "verworfen";
  if (clip.status === "failed") return "fehler";
  if (clip.status === "rendering" || clip.status === "draft") return "wird_erstellt";
  /* Zuerst das, was einer Korrektur bedarf: eine Freigabe an einer Datei, die nicht mehr stimmt,
   * wäre eine Freigabe für etwas anderes als das, was herauskommt. */
  if (vorschauStand(stand) === "veraltet" || clip.cps_warnings.length > 0 || clip.fidelity_warnings.length > 0) {
    return "korrektur";
  }
  if (freigabe?.decision === "approved") return "freigegeben";
  if (clip.review === "bereit") return "bereit";
  return "pruefen";
}

/* Warum braucht dieser Clip eine Korrektur? Wird nur gerufen, wenn der Zustand „korrektur" ist. */
export function korrekturGrund(clip: Clip, veraltet: boolean): string {
  if (veraltet) return "Das gebaute Video zeigt nicht mehr, was eingestellt ist.";
  /* Die Treuewarnungen kommen als freie Struktur aus dem Worker; hier zaehlt nur, dass es sie
   * gibt, und ein Text, falls einer dabei ist. */
  const treue = clip.fidelity_warnings[0];
  if (typeof treue === "string") return treue;
  if (clip.fidelity_warnings.length > 0) return "Der Renderlauf hat etwas angemerkt.";
  if (clip.cps_warnings.length === 1) return "Eine Stelle läuft schnell durch.";
  return `${clip.cps_warnings.length} Stellen laufen schnell durch.`;
}

/* Die Reihenfolge in der Übersicht: was Arbeit braucht, steht oben. Innerhalb einer Stufe bleibt
 * die Reihenfolge, in der die Clips im Video vorkommen - so findet man sie wieder. */
export const ZUSTAND_RANG: Record<ClipZustand, number> = {
  korrektur: 0,
  pruefen: 1,
  bereit: 2,
  freigegeben: 3,
  wird_erstellt: 4,
  fehler: 5,
  verworfen: 6,
};
