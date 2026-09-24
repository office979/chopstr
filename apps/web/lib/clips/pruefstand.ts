/* Der Stand eines Clips auf der Prüfseite: drei Fragen, drei Antworten.
 *
 * Bisher gab es dafür EINEN Zustand („Korrektur nötig", „Bereit", „Bitte prüfen"). Der musste drei
 * verschiedene Dinge gleichzeitig ausdrücken, und das ging schief: an drei von drei Clips stand
 * „Korrektur nötig", und daneben war „Freigeben" anklickbar. Beides kann nicht stimmen. Wer das
 * sieht, weiss nicht, ob er freigeben darf, und klickt entweder blind oder gar nicht.
 *
 * Die drei Fragen sind wirklich verschieden und hängen an verschiedenen Dingen:
 *
 *   redaktion  Hat ein Mensch entschieden?      Hängt an clip.review und der Gastfreigabe.
 *   qualitaet  Stimmt inhaltlich etwas nicht?   Hängt an den Befunden aus dem Renderlauf.
 *   datei      Gibt es ein aktuelles Video?     Hängt am Renderstand und an vorschau-stand.
 *
 * Ein Clip kann freigegeben sein UND eine veraltete Datei haben. Das ist kein Widerspruch,
 * sondern zwei Tatsachen, und der Nutzer braucht beide. Erst zusammen ergeben sie die Antwort auf
 * die einzige Frage, die beim Posten zählt: kann das raus?
 */

import { vorschauStand, type StandEingabe } from "@/lib/clips/vorschau-stand";
import type { CaptionStyle } from "@/lib/clips/caption-style";
import type { Clip, ClipStand, GuestApproval } from "@/lib/repo/types";

/* 1. Redaktionell: was hat ein Mensch entschieden? */
export type Redaktion = "vorgeschlagen" | "in_arbeit" | "freigegeben" | "verworfen";

export const REDAKTION_LABEL: Record<Redaktion, string> = {
  vorgeschlagen: "Vorgeschlagen",
  in_arbeit: "In Arbeit",
  freigegeben: "Freigegeben",
  verworfen: "Verworfen",
};

export const REDAKTION_SATZ: Record<Redaktion, string> = {
  vorgeschlagen: "Der Computer hat diese Stelle vorgeschlagen. Niemand hat sie bisher angesehen.",
  in_arbeit: "Hier wurde schon etwas geändert, entschieden ist noch nichts.",
  freigegeben: "Du hast entschieden: der darf raus.",
  verworfen: "Aussortiert. Lässt sich zurückholen.",
};

/* 2. Qualität: stimmt am Inhalt etwas nicht?
 *
 * „hinweis" und „fehler" sind nicht dasselbe, und der Unterschied entscheidet, ob freigegeben
 * werden darf. Zügiges Sprechen ist ein Hinweis: der Clip ist brauchbar, er liest sich nur
 * anstrengend. Ein weggeschnittenes „nicht" ist ein Fehler: dann sagt der Clip etwas anderes als
 * der Sprecher. */
export type Qualitaet = "ok" | "hinweis" | "fehler";

export const QUALITAET_LABEL: Record<Qualitaet, string> = {
  ok: "Kein Problem",
  hinweis: "Hinweis",
  fehler: "Fehler",
};

/* 3. Datei: gibt es ein Video, und zeigt es, was eingestellt ist? */
export type Datei = "keine" | "wird_erstellt" | "aktuell" | "veraltet" | "fehlgeschlagen";

export const DATEI_LABEL: Record<Datei, string> = {
  keine: "Noch kein Video",
  wird_erstellt: "Wird geclippt",
  aktuell: "Video aktuell",
  veraltet: "Video veraltet",
  fehlgeschlagen: "Clippen fehlgeschlagen",
};

export const DATEI_SATZ: Record<Datei, string> = {
  keine: "Für diesen Clip gibt es noch keine Videodatei.",
  wird_erstellt: "Das Video wird gerade geclippt.",
  aktuell: "Das geclippte Video zeigt genau, was eingestellt ist.",
  veraltet: "Das geclippte Video zeigt nicht mehr, was eingestellt ist.",
  fehlgeschlagen: "Beim Clippen ist etwas schiefgegangen.",
};

/* Ein einzelner Befund, formuliert als das, was zu tun ist.
 *
 * „82 Stellen laufen schnell durch" ist keine Arbeitsanweisung, sondern eine Zahl. Auf einem Clip
 * von dreissig Sekunden sind 82 Stellen ausserdem fast jedes Wort, und eine Warnung, die überall
 * gilt, sagt nichts. Deshalb steht hier ein Satz, der eine Handlung beschreibt, und daneben die
 * Stelle, an der es am engsten ist. */
export interface Befund {
  schwere: "hinweis" | "fehler";
  art: "sinn" | "tempo" | "datei" | "render";
  /* Was los ist und was hilft, in einem Satz. */
  text: string;
  /* Der Wortlaut der schlimmsten Stelle, falls bekannt. Damit findet man sie im Clip wieder. */
  stelle: string | null;
}

export interface Pruefstand {
  redaktion: Redaktion;
  qualitaet: Qualitaet;
  datei: Datei;
  /* Das Wichtigste zuerst: Fehler vor Hinweisen. */
  befunde: Befund[];
  /* Darf das raus? Nur wenn alle drei Achsen mitspielen. */
  postbereit: boolean;
}

export interface PruefstandEingabe {
  clip: Clip;
  /* Die letzte Gastfreigabe zu diesem Clip, falls es eine gibt. */
  freigabe: GuestApproval | null;
  /* Zeigt die gebaute Datei noch, was eingestellt ist? Aus lib/clips/vorschau-stand. */
  stand: StandEingabe;
  /* Hat jemand an diesem Clip schon gearbeitet? Der Aufrufer weiss das: eigener Untertitelstil,
   * gesetzte Bildausschnitte oder ein geänderter Schnitt. Hier hereingereicht, damit dieses Modul
   * eine reine Rechnung bleibt. */
  bearbeitet?: boolean;
}

/* Die Treuewarnungen aus dem Renderlauf, in Sätze übersetzt.
 *
 * Sie kommen als {type, severity, detail} aus fidelity.check_cut und standen in der Oberfläche
 * bisher als „Der Renderlauf hat etwas angemerkt." Das ist das Eingeständnis, den eigenen Befund
 * nicht zu verstehen. Dabei ist jeder dieser vier Fälle klar benennbar, und drei davon sind
 * ernst: sie bedeuten, dass der Clip etwas anderes sagt als der Sprecher. */
function treueSatz(typ: string, detail: unknown): string {
  const liste = Array.isArray(detail) ? detail.map(String).join(", ") : typeof detail === "string" ? detail : "";
  switch (typ) {
    case "negation_removed":
      return liste
        ? `Der Schnitt lässt eine Verneinung weg (${liste}). Der Clip kann damit das Gegenteil sagen.`
        : "Der Schnitt lässt eine Verneinung weg. Der Clip kann damit das Gegenteil sagen.";
    case "qualifier_removed":
      return liste
        ? `Der Schnitt lässt eine Einschränkung weg (${liste}). Die Aussage wird dadurch schärfer, als sie war.`
        : "Der Schnitt lässt eine Einschränkung weg. Die Aussage wird dadurch schärfer, als sie war.";
    case "ends_before_contrast":
      return "Der Clip hört auf, kurz bevor der Sprecher einschränkt. Wer nur den Clip sieht, hört die halbe Aussage.";
    case "joined_statements":
      return liste
        ? `Zwei Stellen sind zusammengesetzt, die im Original ${liste} auseinanderliegen. Das klingt wie ein Satz, war aber keiner.`
        : "Zwei weit auseinanderliegende Stellen sind zusammengesetzt. Das klingt wie ein Satz, war aber keiner.";
    default:
      return "Der Schnitt verändert die Aussage. Bitte den Text ansehen.";
  }
}

/* Aus einer Tempowarnung die zitierte Stelle holen.
 *
 * Der Worker schreibt sie als "Zu schnell (38 Z/s): 'Der Handwerksbetrieb mit'". Der Wortlaut ist
 * das, was dem Nutzer hilft: damit findet er die Stelle im Text wieder, ohne eine Sekundenzahl
 * umrechnen zu müssen. */
function tempoStelle(warnung: string): string | null {
  const m = /'([^']+)'/.exec(warnung);
  return m ? m[1] : null;
}

export function pruefstand({ clip, freigabe, stand, bearbeitet = false }: PruefstandEingabe): Pruefstand {
  const redaktion: Redaktion =
    clip.review === "verworfen"
      ? "verworfen"
      : clip.review === "bereit" || freigabe?.decision === "approved"
        ? "freigegeben"
        : bearbeitet
          ? "in_arbeit"
          : "vorgeschlagen";

  const datei: Datei =
    clip.status === "failed"
      ? "fehlgeschlagen"
      : clip.status === "rendering"
        ? "wird_erstellt"
        /* „draft" heisst: der Clip ist angelegt, aber noch nie gebaut worden. Das ist nicht
         * dasselbe wie „wird gerade gebaut" - da läuft nichts, und wer wartet, wartet vergeblich. */
        : !clip.file_key
          ? "keine"
          : vorschauStand(stand) === "veraltet"
            ? "veraltet"
            : "aktuell";

  const befunde: Befund[] = [];

  for (const roh of clip.fidelity_warnings) {
    if (!roh || typeof roh !== "object") continue;
    const w = roh as { type?: unknown; severity?: unknown; detail?: unknown };
    const typ = typeof w.type === "string" ? w.type : "";
    befunde.push({
      schwere: w.severity === "medium" ? "hinweis" : "fehler",
      art: "sinn",
      text: treueSatz(typ, w.detail),
      stelle: null,
    });
  }

  /* Alle Tempowarnungen zu EINEM Befund. Sie haben dieselbe Ursache (der Sprecher ist zügig) und
   * dieselbe Abhilfe (straffen oder herausnehmen); als Liste wären sie zwanzigmal derselbe Satz. */
  if (clip.cps_warnings.length > 0) {
    const stelle = tempoStelle(clip.cps_warnings[0]);
    befunde.push({
      schwere: "hinweis",
      art: "tempo",
      text:
        clip.cps_warnings.length === 1
          ? "Eine Einblendung läuft schneller durch, als sich mitlesen lässt. Im Text straffen oder in der Timeline herausnehmen."
          : "An mehreren Stellen wird zügig gesprochen, zum Mitlesen ohne Ton ist das knapp. Im Text straffen oder in der Timeline herausnehmen.",
      stelle,
    });
  }

  if (datei === "veraltet") {
    befunde.push({
      schwere: "fehler",
      art: "datei",
      text: "Das geclippte Video zeigt nicht mehr, was eingestellt ist. Einmal neu clippen, dann stimmt der Download wieder.",
      stelle: null,
    });
  }

  if (datei === "fehlgeschlagen") {
    befunde.push({
      schwere: "fehler",
      art: "render",
      text: clip.render_error ?? "Das Clippen hat nicht geklappt. Nochmal versuchen.",
      stelle: null,
    });
  }

  befunde.sort((a, b) => (a.schwere === b.schwere ? 0 : a.schwere === "fehler" ? -1 : 1));

  const qualitaet: Qualitaet = befunde.some((b) => b.schwere === "fehler" && (b.art === "sinn" || b.art === "render"))
    ? "fehler"
    : befunde.some((b) => b.art === "sinn" || b.art === "tempo")
      ? "hinweis"
      : "ok";

  /* Die eine Frage, die beim Posten zählt. Alle drei Achsen müssen mitspielen: entschieden,
   * inhaltlich in Ordnung, und die Datei zeigt genau das. */
  const postbereit = redaktion === "freigegeben" && qualitaet !== "fehler" && datei === "aktuell";

  return { redaktion, qualitaet, datei, befunde, postbereit };
}

/* Was als Nächstes zu tun ist, in der Reihenfolge, in der es weh tut. Genau eine Handlung je
 * Karte: vier gleichrangige Knöpfe sind keine Führung, sondern eine Auswahlaufgabe. */
export type AktionId =
  | "pruefen"
  | "beheben"
  | "neu_bauen"
  | "freigeben"
  | "herunterladen"
  | "zurueckholen"
  | "warten";

export interface Hauptaktion {
  id: AktionId;
  label: string;
}

export function hauptaktion(p: Pruefstand): Hauptaktion {
  if (p.redaktion === "verworfen") return { id: "zurueckholen", label: "Zurückholen" };
  if (p.datei === "fehlgeschlagen") return { id: "neu_bauen", label: "Nochmal versuchen" };
  if (p.datei === "wird_erstellt") return { id: "warten", label: "Wird geclippt" };
  if (p.qualitaet === "fehler" && p.befunde.some((b) => b.art === "sinn")) {
    return { id: "beheben", label: "Fehler beheben" };
  }
  if (p.datei === "veraltet" || p.datei === "keine") {
    return { id: "neu_bauen", label: p.datei === "keine" ? "Video clippen" : "Video neu clippen" };
  }
  if (p.redaktion === "freigegeben") return { id: "herunterladen", label: "Herunterladen" };
  return { id: "pruefen", label: "Clip prüfen" };
}

/* Ob eine Handlung zum Stand passt, und wenn nicht: was zuerst zu tun ist.
 *
 * Ein gesperrter Knopf ohne Begründung ist eine Sackgasse. Der Satz steht deshalb sichtbar an der
 * Karte und nicht nur im Titelattribut, das nur mit einer Maus erreichbar ist. */
export interface AktionStand {
  erlaubt: boolean;
  grund: string | null;
}

const ERLAUBT: AktionStand = { erlaubt: true, grund: null };

export function aktionStand(
  id: "freigeben" | "herunterladen" | "neu_bauen" | "verwerfen" | "gast_fragen",
  p: Pruefstand,
  opts: { exportGesperrt?: string | null; hatDatei?: boolean } = {},
): AktionStand {
  if (id === "verwerfen") {
    return p.redaktion === "verworfen" ? { erlaubt: false, grund: "Ist schon verworfen." } : ERLAUBT;
  }

  if (id === "freigeben") {
    if (p.redaktion === "verworfen") return { erlaubt: false, grund: "Erst zurückholen." };
    if (p.redaktion === "freigegeben") return { erlaubt: false, grund: "Ist schon freigegeben." };
    if (p.datei === "wird_erstellt") return { erlaubt: false, grund: "Warte, bis das Video fertig geclippt ist." };
    /* Ein schwerer Befund am Inhalt sperrt die Freigabe. Ein veraltetes Video nicht: das ist eine
     * Aussage über die Datei, nicht über den Clip, und wird nach der Freigabe neu gebaut. */
    if (p.qualitaet === "fehler" && p.befunde.some((b) => b.art === "sinn")) {
      return { erlaubt: false, grund: "Erst den Fehler am Inhalt beheben, sonst gibst du etwas anderes frei, als gesagt wurde." };
    }
    if (p.datei === "fehlgeschlagen") return { erlaubt: false, grund: "Das Clippen ist fehlgeschlagen. Erst nochmal versuchen." };
    return ERLAUBT;
  }

  if (id === "herunterladen") {
    if (opts.exportGesperrt) return { erlaubt: false, grund: opts.exportGesperrt };
    if (p.datei === "wird_erstellt") return { erlaubt: false, grund: "Das Video entsteht noch." };
    if (p.datei === "fehlgeschlagen") return { erlaubt: false, grund: "Das Clippen ist fehlgeschlagen. Erst nochmal versuchen." };
    if (p.datei === "keine") return { erlaubt: false, grund: "Erst das Video clippen." };
    if (p.datei === "veraltet") return { erlaubt: false, grund: "Erst das Video neu clippen, sonst lädst du einen alten Stand herunter." };
    if (opts.hatDatei === false) return { erlaubt: false, grund: "Die Datei ist gerade nicht verfügbar." };
    return ERLAUBT;
  }

  if (id === "neu_bauen") {
    if (p.datei === "wird_erstellt") return { erlaubt: false, grund: "Läuft schon." };
    return ERLAUBT;
  }

  /* Gastfreigabe: jemanden von aussen um eine Entscheidung bitten. An einem veralteten Video wäre
   * das eine Frage zu etwas, das so nicht herauskommt. */
  if (p.datei === "veraltet") return { erlaubt: false, grund: "Erst neu clippen, sonst sieht die Person einen alten Stand." };
  if (p.datei !== "aktuell") return { erlaubt: false, grund: "Erst das Video clippen." };
  return ERLAUBT;
}

/* Die Reihenfolge in der Liste: was Arbeit macht, steht oben. Gerechnet aus den drei Achsen statt
 * aus einem Zustandsnamen, damit ein freigegebener Clip mit veralteter Datei nicht zwischen den
 * erledigten verschwindet. */
export function rang(p: Pruefstand): number {
  if (p.qualitaet === "fehler") return 0;
  if (p.datei === "fehlgeschlagen") return 1;
  if (p.datei === "veraltet") return 2;
  if (p.redaktion === "vorgeschlagen" || p.redaktion === "in_arbeit") return p.qualitaet === "hinweis" ? 3 : 4;
  if (p.datei === "wird_erstellt" || p.datei === "keine") return 5;
  if (p.postbereit) return 6;
  if (p.redaktion === "freigegeben") return 7;
  return 8;
}

/* Womit lässt sich filtern? Die Frage vor der Liste lautet fast nie „zeig mir alles", sondern
 * „was muss ich noch anfassen". */
export type FilterId =
  | "alle"
  | "zu_pruefen"
  | "fehler"
  | "hinweis"
  | "veraltet"
  | "wird_erstellt"
  | "postbereit"
  | "freigegeben"
  | "verworfen";

export const FILTER_LABEL: Record<FilterId, string> = {
  alle: "Alle",
  zu_pruefen: "Zu prüfen",
  fehler: "Fehler beheben",
  hinweis: "Mit Hinweis",
  veraltet: "Video veraltet",
  wird_erstellt: "Wird geclippt",
  postbereit: "Bereit zum Posten",
  freigegeben: "Freigegeben",
  verworfen: "Verworfen",
};

export function passtZuFilter(p: Pruefstand, f: FilterId): boolean {
  switch (f) {
    case "alle":
      return p.redaktion !== "verworfen";
    case "zu_pruefen":
      return p.redaktion === "vorgeschlagen" || p.redaktion === "in_arbeit";
    case "fehler":
      return p.qualitaet === "fehler";
    case "hinweis":
      return p.qualitaet === "hinweis";
    case "veraltet":
      return p.datei === "veraltet";
    case "wird_erstellt":
      return p.datei === "wird_erstellt";
    case "postbereit":
      return p.postbereit;
    case "freigegeben":
      return p.redaktion === "freigegeben";
    case "verworfen":
      return p.redaktion === "verworfen";
  }
}

/* Die Reihenfolge der Filterknöpfe: erst die Arbeit, dann das Erledigte. */
export const FILTER_ORDNUNG: FilterId[] = [
  "zu_pruefen",
  "fehler",
  "hinweis",
  "veraltet",
  "wird_erstellt",
  "postbereit",
  "freigegeben",
  "verworfen",
];

/* Eine Clip-Zeile aus der Übersichtsabfrage in einen Prüfstand rechnen.
 *
 * Damit rechnet die Startseite mit demselben Modell wie die Prüfseite. Vorher zählte sie selbst:
 * „Clips zu prüfen" waren gebaute Clips ohne Entscheidung, „Fertige Clips" waren gebaute Clips -
 * zwei Namen für dieselben vierzehn Clips, und der zweite trug den Zusatz „bereit zum Posten",
 * obwohl niemand sie freigegeben hatte. */
export function standAusZeile(r: ClipStand, stil: CaptionStyle): Pruefstand {
  const clip = {
    status: r.status,
    review: r.review,
    file_key: r.hat_datei ? "x" : null,
    composition: r.composition,
    zeitmarken: r.zeitmarken,
    cps_warnings: r.cps_warnings,
    fidelity_warnings: r.fidelity_warnings,
    render_error: r.render_error,
  } as unknown as Clip;
  return pruefstand({
    clip,
    freigabe: null,
    stand: {
      status: r.status,
      hatDatei: r.hat_datei,
      /* Nur die vier Teile, die verglichen werden. Der Rest des Plans wird für diese Frage nicht
       * gebraucht und deshalb gar nicht erst geladen. */
      plan: r.plan_captions
        ? ({
            captions: r.plan_captions,
            segments: r.plan_segments ?? [],
            zeitmarken: r.plan_zeitmarken ?? [],
            sources: { transcript_version: r.plan_transcript_version },
            output: { height: r.plan_output_height },
          } as unknown as Clip["render_plan"])
        : null,
      renderFehler: r.render_error,
      transkriptVersion: r.transkript_version,
      stil,
      schnitt: r.composition,
      zeitmarken: r.zeitmarken,
    },
    bearbeitet: (r.caption_style != null && Object.keys(r.caption_style).length > 0) || r.zeitmarken.length > 0 || r.composition.length > 1,
  });
}

/* Was an einem Video noch Arbeit macht, in den Worten der Prüfseite.
 *
 * Ein Clip kann in mehreren Zahlen stehen: ein freigegebener mit veraltetem Video ist freigegeben
 * UND veraltet. Das ist kein Zählfehler, sondern die Folge davon, dass es drei Fragen sind. */
export interface VideoStand {
  gesamt: number;
  zuPruefen: number;
  fehler: number;
  veraltet: number;
  wirdGebaut: number;
  postbereit: number;
  freigegeben: number;
  verworfen: number;
}

export function zaehlen(staende: Pruefstand[]): VideoStand {
  const z: VideoStand = { gesamt: 0, zuPruefen: 0, fehler: 0, veraltet: 0, wirdGebaut: 0, postbereit: 0, freigegeben: 0, verworfen: 0 };
  for (const p of staende) {
    if (p.redaktion === "verworfen") {
      z.verworfen += 1;
      continue;
    }
    z.gesamt += 1;
    /* Solange gebaut wird, wartet der Clip nicht auf eine Entscheidung, sondern auf die
     * Maschine. Ihn in beide Zahlen zu zählen ergäbe „12 zu prüfen, 12 werden gebaut" über
     * denselben zwölf Clips - und genau solche Doppelaussagen sollen hier verschwinden.
     * Dieselbe Grenze zieht aktionStand: bei „wird gebaut" ist Freigeben gesperrt. */
    if ((p.redaktion === "vorgeschlagen" || p.redaktion === "in_arbeit") && p.datei !== "wird_erstellt") {
      z.zuPruefen += 1;
    }
    if (p.redaktion === "freigegeben") z.freigegeben += 1;
    if (p.qualitaet === "fehler") z.fehler += 1;
    if (p.datei === "veraltet") z.veraltet += 1;
    if (p.datei === "wird_erstellt") z.wirdGebaut += 1;
    if (p.postbereit) z.postbereit += 1;
  }
  return z;
}

/* Die eine Aufgabe, die an diesem Video als Nächstes ansteht, mit dem Weg dorthin.
 *
 * Auf der Übersicht soll nicht stehen, wie viele Clips es gibt, sondern was zu tun ist. „3 Clips
 * prüfen" ist eine Aufgabe; „14 Clips" ist eine Zahl. */
export interface Aufgabe {
  text: string;
  /* Pfad relativ zum Video, samt Filter. */
  pfad: string;
}

export function naechsteAufgabe(z: VideoStand): Aufgabe | null {
  if (z.fehler > 0) {
    return { text: z.fehler === 1 ? "1 Fehler beheben" : `${z.fehler} Fehler beheben`, pfad: "/clips#fehler" };
  }
  if (z.veraltet > 0) {
    return {
      text: z.veraltet === 1 ? "1 Video neu clippen" : `${z.veraltet} Videos neu clippen`,
      pfad: "/clips#veraltet",
    };
  }
  if (z.zuPruefen > 0) {
    return { text: z.zuPruefen === 1 ? "1 Clip prüfen" : `${z.zuPruefen} Clips prüfen`, pfad: "/clips#zu_pruefen" };
  }
  if (z.wirdGebaut > 0) {
    return { text: z.wirdGebaut === 1 ? "1 Clip wird geclippt" : `${z.wirdGebaut} Clips werden geclippt`, pfad: "/clips" };
  }
  if (z.postbereit > 0) {
    return {
      text: z.postbereit === 1 ? "1 Clip herunterladen" : `${z.postbereit} Clips herunterladen`,
      pfad: "/clips#postbereit",
    };
  }
  return null;
}
