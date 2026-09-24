/* Woran ist ein Projekt gerade, und was ist als Nächstes zu tun?
 *
 * In der Bibliothek stand bisher der technische Zustand der Verarbeitung: „Computer bewertet die
 * Stellen", „Fertig". Der sagt, wo die Maschine steht, und nicht, ob jemand etwas tun muss. Ein
 * Projekt mit sechs ungeprüften Clips und eines, bei dem alles freigegeben ist, standen beide als
 * „Fertig" da.
 *
 * Hier kommen der Verarbeitungsstand und der Prüfstand der Clips zusammen. Heraus kommt ein
 * Zustand und die eine Handlung, die dazu passt.
 */

import type { ClipCount, Source } from "@/lib/repo/types";

export type ProjektZustand = "upload" | "verarbeitung" | "pruefen" | "bereit" | "leer" | "fehler";

export const PROJEKT_LABEL: Record<ProjektZustand, string> = {
  upload: "Upload läuft",
  verarbeitung: "Wird verarbeitet",
  pruefen: "Bitte prüfen",
  bereit: "Bereit",
  leer: "Nichts gefunden",
  fehler: "Fehler",
};

export interface Hauptaktion {
  label: string;
  /* Pfad relativ zum Projekt, zum Beispiel "/clips". Leer heisst: die Projektseite selbst. */
  pfad: string;
}

/* Welche Handlung passt? Immer genau eine, und zwar die, die den Nutzer weiterbringt. Vier
 * gleichrangige Knöpfe je Zeile sind keine Führung, sondern eine Auswahlaufgabe. */
export function hauptaktion(zustand: ProjektZustand): Hauptaktion {
  switch (zustand) {
    case "upload":
    case "verarbeitung":
      return { label: "Zusehen", pfad: "" };
    case "pruefen":
      return { label: "Clips prüfen", pfad: "/clips" };
    case "bereit":
      return { label: "Clips ansehen", pfad: "/clips" };
    case "leer":
      return { label: "Text ansehen", pfad: "/transkript" };
    case "fehler":
      return { label: "Fehler ansehen", pfad: "" };
  }
}

export function projektZustand(source: Source, clips: ClipCount | null): ProjektZustand {
  if (source.status === "failed") return "fehler";
  if (source.status === "uploading") return "upload";
  if (source.status !== "ready") return "verarbeitung";
  /* Fertig analysiert, aber die Clips entstehen noch. */
  if (clips && clips.rendering > 0) return "verarbeitung";
  if (!clips || clips.total === 0) return "leer";
  if (clips.offen > 0) return "pruefen";
  return "bereit";
}

/* Ein Satz zum Zustand, mit den Zahlen, die dazugehören. */
export function projektSatz(zustand: ProjektZustand, clips: ClipCount | null): string {
  const c = clips;
  switch (zustand) {
    case "upload":
      return "Die Datei wird gerade übertragen.";
    case "verarbeitung":
      return c && c.rendering > 0
        ? `${c.rendering === 1 ? "Ein Clip wird" : `${c.rendering} Clips werden`} gerade gebaut.`
        : "Der Computer arbeitet daran.";
    case "pruefen":
      return `${c!.offen === 1 ? "Ein Clip wartet" : `${c!.offen} Clips warten`} auf deine Entscheidung.`;
    case "bereit":
      return c && c.bereit > 0
        ? `${c.bereit === 1 ? "Ein Clip ist" : `${c.bereit} Clips sind`} bereit.`
        : "Alles durchgesehen.";
    case "leer":
      return "Hier hat der Computer keine gute Stelle gefunden.";
    case "fehler":
      return "Beim Verarbeiten ist etwas schiefgegangen.";
  }
}

/* Die Reihenfolge, wenn nach Dringlichkeit sortiert wird. Was Arbeit macht, steht oben. */
export const PROJEKT_RANG: Record<ProjektZustand, number> = {
  fehler: 0,
  pruefen: 1,
  verarbeitung: 2,
  upload: 3,
  bereit: 4,
  leer: 5,
};
