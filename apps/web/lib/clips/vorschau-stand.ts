/* Ist das gebaute Video noch das, was gerade eingestellt ist?
 *
 * Die Frage stand bisher an vier Stellen und wurde an jeder anders beantwortet: der Text verglich
 * nichts, der Untertitelstil verglich gegen den Renderplan, der Schnitt gegen den gespeicherten
 * Stand, und die Marken gar nicht. Herausgekommen ist der Widerspruch, ueber den sich niemand
 * wundern muss: „Fertig" an der einen Stelle, „im Bild sind noch die alten Untertitel" an der
 * anderen.
 *
 * Hier steht die Antwort einmal. Verglichen wird immer gegen den RENDERPLAN, also gegen das, was
 * wirklich im Bild ist, und nicht gegen den gespeicherten Stand: nach dem Speichern ist nichts
 * mehr „geaendert", im gebauten Video steht aber weiter das Alte.
 */

import { gleich as schnittGleich, zusammenziehen, type Schnitt } from "@/lib/clips/schnitt";
import { passtZumRender, type CaptionStyle } from "@/lib/clips/caption-style";
import { gleich as effekteGleich, lesen as effekteLesen, type Effekt } from "@/lib/clips/effekte";
import type { ClipStatus, RenderPlan, Zeitmarke } from "@/lib/repo/types";

/* Die drei Zustaende, die der Nutzer auseinanderhalten muss. „veraltet" ist der wichtige: nur er
 * rechtfertigt es, eine Freigabe zu sperren. */
export type VorschauStand = "keine" | "laeuft" | "veraltet" | "aktuell" | "fehler";

export interface WasAbweicht {
  text: boolean;
  untertitel: boolean;
  schnitt: boolean;
  bildausschnitt: boolean;
  effekte: boolean;
}

export interface StandEingabe {
  status: ClipStatus;
  /* Liegt eine gebaute Datei vor? Ohne sie gibt es keine Vorschau, die veralten koennte. */
  hatDatei: boolean;
  plan: RenderPlan | null;
  renderFehler: string | null;
  /* Der Stand, der gespeichert ist. Ungespeicherte Aenderungen sind eine andere Frage und
   * gehoeren nicht hierher: sie haben ihre eigenen Speicherknoepfe. */
  transkriptVersion: number | null;
  stil: CaptionStyle;
  schnitt: Schnitt;
  zeitmarken: Zeitmarke[];
  /* Effekte auf der Clip-Zeitachse. Sie stehen im Renderplan, also muss ihre Änderung das
   * gebaute Video als veraltet melden - sonst zeigt der Download eine Betonung, die es nicht mehr
   * gibt. */
  effekte?: Effekt[];
}

function markenGleich(a: Zeitmarke[], b: Zeitmarke[]): boolean {
  if (a.length !== b.length) return false;
  const schluessel = (m: Zeitmarke) =>
    `${Math.round(m.ab_s * 100)}|${m.x != null ? Math.round(m.x) : "-"}|${m.zoom ?? 1}|${m.layout ?? "einzel"}`;
  return a.every((m, i) => schluessel(m) === schluessel(b[i]));
}

/* Was genau am gebauten Video nicht mehr stimmt. Wird gebraucht, um es zu benennen: „die
 * Untertitel sind anders" hilft, „irgendwas ist anders" nicht. */
export function wasAbweicht(e: StandEingabe): WasAbweicht {
  const plan = e.plan;
  if (!plan) return { text: false, untertitel: false, schnitt: false, bildausschnitt: false, effekte: false };
  const geplanteVersion = plan.sources?.transcript_version ?? null;
  return {
    text:
      e.transkriptVersion != null && geplanteVersion != null && geplanteVersion !== e.transkriptVersion,
    untertitel: !passtZumRender(e.stil, plan.captions as unknown as Record<string, unknown>),
    /* In der Form des Plans verglichen: der Renderer zieht durchgehende Abschnitte zusammen. */
    schnitt: !schnittGleich(zusammenziehen(e.schnitt), zusammenziehen(plan.segments ?? [])),
    bildausschnitt: !markenGleich(e.zeitmarken, plan.zeitmarken ?? []),
    effekte: !effekteGleich(effekteLesen(e.effekte ?? [], 1e9), effekteLesen(plan.effekte ?? [], 1e9)),
  };
}

export function vorschauStand(e: StandEingabe): VorschauStand {
  if (e.status === "rendering") return "laeuft";
  if (e.status === "failed") return "fehler";
  if (!e.hatDatei || !e.plan) return "keine";
  const ab = wasAbweicht(e);
  return ab.text || ab.untertitel || ab.schnitt || ab.bildausschnitt || ab.effekte ? "veraltet" : "aktuell";
}

/* Ein Satz, der sagt was los ist. Bewusst nicht „Status: veraltet": das sagt niemandem, was er
 * tun soll. */
export function standSatz(stand: VorschauStand, ab: WasAbweicht): string {
  switch (stand) {
    case "laeuft":
      return "Das Video wird gerade geclippt.";
    case "fehler":
      return "Beim Clippen ist etwas schiefgegangen.";
    case "keine":
      return "Es gibt noch keine Videodatei. Links siehst du, wie der Clip aussehen wird.";
    case "aktuell":
      return "Die geclippte Datei zeigt genau das, was eingestellt ist.";
    case "veraltet": {
      /* Die Mehrzahl haengt nicht an der Zahl der Teile: „die Untertitel" ist fuer sich schon
       * Mehrzahl. Deshalb steht sie am Teil und wird nicht gezaehlt. */
      const teile = [
        ab.text ? { wort: "der Text", mehrzahl: false } : null,
        ab.untertitel ? { wort: "die Untertitel", mehrzahl: true } : null,
        ab.schnitt ? { wort: "der Schnitt", mehrzahl: false } : null,
        ab.bildausschnitt ? { wort: "der Bildausschnitt", mehrzahl: false } : null,
        ab.effekte ? { wort: "die Effekte", mehrzahl: true } : null,
      ].filter(Boolean) as { wort: string; mehrzahl: boolean }[];
      if (teile.length === 0) return "Das geclippte Video ist nicht mehr aktuell.";
      const woerter = teile.map((t) => t.wort);
      const liste =
        woerter.length === 1 ? woerter[0] : `${woerter.slice(0, -1).join(", ")} und ${woerter[woerter.length - 1]}`;
      const mehrzahl = teile.length > 1 || teile[0].mehrzahl;
      return `${liste} ${mehrzahl ? "wurden" : "wurde"} geändert, seit das Video geclippt wurde. Zum Herunterladen einmal neu clippen.`;
    }
  }
}
