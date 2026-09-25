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
 *   datei      Gibt es ein fertiges Video?      Hängt am Renderstand.
 *
 * Ein Clip kann freigegeben sein UND noch kein fertiges Video haben. Das ist kein Widerspruch,
 * sondern zwei Tatsachen, und der Nutzer braucht beide. Erst zusammen ergeben sie die Antwort auf
 * die einzige Frage, die beim Posten zählt: kann das raus?
 */

import { warningsOf } from "@/lib/candidates/labels";
import type { Candidate, Clip, ClipStand, GuestApproval } from "@/lib/repo/types";

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

/* Eine Plakette „Mit Hinweis" gab es hier einmal. Sie ist weg: „Hinweis" an einer Karte sagt
 * nicht, was los ist, und stand an fast jedem Clip. Die Hinweise selbst bleiben - aber als der
 * Satz, um den es geht („Bitte kurz ansehen, ob die sprechende Person im Bild ist"), und dort,
 * wo man etwas damit anfangen kann: im geöffneten Clip. */

/* 3. Datei: gibt es ein Video, und zeigt es, was eingestellt ist? */
/* „veraltet" gab es hier einmal: eine Datei, die nicht mehr zeigt, was eingestellt ist. Diesen
 * Zustand kann es nicht mehr geben - Speichern clippt sofort neu, das Alte wird überschrieben.
 * Zwischen Speichern und fertigem Video steht „wird_erstellt", und das sagt dasselbe, nur ohne
 * Vorwurf. */
export type Datei = "keine" | "wird_erstellt" | "aktuell" | "fehlgeschlagen";

export const DATEI_LABEL: Record<Datei, string> = {
  keine: "Noch kein Video",
  wird_erstellt: "Wird geclippt",
  aktuell: "Video aktuell",
  fehlgeschlagen: "Clippen fehlgeschlagen",
};

export const DATEI_SATZ: Record<Datei, string> = {
  keine: "Für diesen Clip gibt es noch keine Videodatei.",
  wird_erstellt: "Das Video wird gerade geclippt.",
  aktuell: "Das geclippte Video zeigt genau, was eingestellt ist.",
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
  art: "sinn" | "tempo" | "datei" | "render" | "technik" | "pruefen" | "bild";
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
  /* Hat jemand an diesem Clip schon gearbeitet? Der Aufrufer weiss das: eigener Untertitelstil,
   * gesetzte Bildausschnitte oder ein geänderter Schnitt. Hier hereingereicht, damit dieses Modul
   * eine reine Rechnung bleibt. */
  bearbeitet?: boolean;
  /* Der Kandidat, aus dem dieser Clip entstanden ist. Er trägt die Marker aus der Analyse:
   * Werbung, heikles Thema, eine Behauptung, eine spätere Relativierung, und ob die Stelle ohne
   * KI gefunden wurde. Sie standen bisher nur in der Datenbank. */
  kandidat?: Pick<Candidate, "risk_flags" | "story_graph_flags"> | null;
  /* Weicht das Zielformat vom Format der Quelle ab? Nur dann wird beschnitten, und nur dann ist
   * die Frage „ist die richtige Person im Bild" überhaupt eine Frage. Der Aufrufer weiss die
   * Masse der Quelle; hier hereingereicht, damit dieses Modul eine reine Rechnung bleibt. */
  quellformatAbweichend?: boolean;
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

export function pruefstand({
  clip,
  freigabe,
  bearbeitet = false,
  kandidat = null,
  quellformatAbweichend = false,
}: PruefstandEingabe): Pruefstand {
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

  /* Wurde das Bild blind beschnitten?
   *
   * Aus einem Video im Querformat einen hochkanten Clip zu machen heisst, zwei Drittel des Bildes
   * wegzuschneiden. Welches Drittel bleibt, entscheidet die Gesichtserkennung. Läuft sie nicht -
   * weil das Modell fehlt oder niemand erkannt wurde - nimmt der Renderer die Mitte. Das kann
   * passen und kann den Sprecher halb abschneiden, und man sieht es erst im fertigen Video.
   *
   * Im Entscheidungsregister steht seit Phase 3, die Oberfläche zeige diesen Fall in Orange. Sie
   * tat es nicht: `reframe.strategy` und `reframe.detector` standen im Renderplan und wurden
   * nirgends gelesen. An den 14 Clips dieses Arbeitsbereichs traf es neun.
   *
   * Kein Fehler, sondern ein Hinweis: der Ausschnitt ist vielleicht richtig. Aber jemand muss
   * hinsehen, und dafür muss er es wissen. Behält der Clip das Format der Quelle, wird nichts
   * beschnitten und es gibt nichts zu prüfen. */
  const reframe = clip.render_plan?.reframe;
  if (reframe && datei !== "keine" && quellformatAbweichend) {
    if (reframe.detector === "none") {
      befunde.push({
        schwere: "hinweis",
        art: "bild",
        text: "Der Bildausschnitt wurde ohne Gesichtserkennung gewählt: der Clip zeigt die Mitte des Originals. Bitte kurz ansehen, ob die sprechende Person im Bild ist.",
        stelle: null,
      });
    } else if (reframe.faces_detected === false) {
      befunde.push({
        schwere: "hinweis",
        art: "bild",
        text: "Im Original wurde niemand erkannt, deshalb zeigt der Clip die Bildmitte. Bitte kurz ansehen, ob das passt.",
        stelle: null,
      });
    }
  }

  /* Die Marker aus der Analyse. Sie sagen nichts über die Technik und nichts über den Schnitt,
   * sondern: hier muss ein Mensch hinsehen. „Muss als Werbung gekennzeichnet werden" ist eine
   * rechtliche Pflicht, „Ohne KI gefunden" heisst, dass die Stelle nur nach Regeln gewählt wurde
   * und schwächer sein kann als üblich.
   *
   * Es gab eine fertige Funktion dafür, warningsOf, mit den Sätzen schon ausformuliert. Sie hatte
   * keinen einzigen Aufrufer: die Marker standen in der Datenbank und wurden nirgends angezeigt.
   * Sie sperren nichts - ein Vorschlag ist zum Ansehen da, und genau darum geht es hier. */
  if (kandidat) {
    for (const w of warningsOf(kandidat)) {
      befunde.push({ schwere: "hinweis", art: "pruefen", text: w.label, stelle: null });
    }
  }

  /* Was die technische Prüfung an der fertigen Datei gefunden hat (Migration 0014). Sie läuft im
   * Worker nach dem Clippen und misst Dinge, die man dem Video nicht ansieht, solange niemand
   * hinsieht: ob überhaupt Ton drauf ist, ob die Lautstärke zu den anderen Videos der Plattform
   * passt, ob die Untertitel im Bild gelandet sind.
   *
   * Sie ändert die Qualitätsachse nicht: „Qualität" beantwortet die Frage, ob der Clip inhaltlich
   * etwas anderes sagt als der Sprecher, und ein leiser Ton sagt nichts anderes. Gesperrt wird
   * trotzdem, das entscheidet lib/clips/ausgabe.ts. */
  for (const t of clip.export_checks ?? []) {
    if (t.ergebnis === "ok") continue;
    befunde.push({
      schwere: t.ergebnis === "fehler" ? "fehler" : "hinweis",
      art: "technik",
      text: t.text,
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
    : befunde.some((b) => b.art === "sinn" || b.art === "tempo" || b.art === "technik" || b.art === "pruefen" || b.art === "bild")
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
  if (p.datei === "keine") return { id: "neu_bauen", label: "Video clippen" };
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
    /* Ein schwerer Befund am Inhalt sperrt die Freigabe: sonst gibt man etwas frei, das anders
     * klingt als gesagt. */
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
    if (opts.hatDatei === false) return { erlaubt: false, grund: "Die Datei ist gerade nicht verfügbar." };
    return ERLAUBT;
  }

  if (id === "neu_bauen") {
    if (p.datei === "wird_erstellt") return { erlaubt: false, grund: "Läuft schon." };
    return ERLAUBT;
  }

  /* Gastfreigabe: jemanden von aussen um eine Entscheidung bitten. Ohne fertiges Video wäre das
   * eine Frage zu etwas, das es noch gar nicht gibt. */
  if (p.datei !== "aktuell") return { erlaubt: false, grund: "Erst das Video clippen." };
  return ERLAUBT;
}

/* Die Reihenfolge in der Liste: was Arbeit macht, steht oben. Gerechnet aus den drei Achsen statt
 * aus einem Zustandsnamen, damit ein freigegebener Clip mit fehlgeschlagenem Lauf nicht zwischen
 * den erledigten verschwindet. */
export function rang(p: Pruefstand): number {
  if (p.qualitaet === "fehler") return 0;
  if (p.datei === "fehlgeschlagen") return 1;
  if (p.redaktion === "vorgeschlagen" || p.redaktion === "in_arbeit") return p.qualitaet === "hinweis" ? 3 : 4;
  if (p.datei === "wird_erstellt" || p.datei === "keine") return 5;
  if (p.postbereit) return 6;
  if (p.redaktion === "freigegeben") return 7;
  return 8;
}

/* Womit lässt sich filtern? Die Frage vor der Liste lautet fast nie „zeig mir alles", sondern
 * „was muss ich noch anfassen". */
export type FilterId = "alle" | "fehler" | "wird_erstellt" | "postbereit" | "freigegeben" | "verworfen";

export const FILTER_LABEL: Record<FilterId, string> = {
  alle: "Alle",
  fehler: "Fehler beheben",
  wird_erstellt: "Wird geclippt",
  postbereit: "Bereit zum Posten",
  freigegeben: "Freigegeben",
  verworfen: "Verworfen",
};

export function passtZuFilter(p: Pruefstand, f: FilterId): boolean {
  switch (f) {
    case "alle":
      return p.redaktion !== "verworfen";
    case "fehler":
      return p.qualitaet === "fehler";
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
  "fehler",
  "wird_erstellt",
  "postbereit",
  "freigegeben",
  "verworfen",
];

/* Eine Clip-Zeile aus der Übersichtsabfrage in einen Prüfstand rechnen.
 *
 * Damit rechnet die Startseite mit demselben Modell wie die Prüfseite. Vorher zählte sie selbst,
 * mit eigenen Namen für dieselben Clips - und der eine Name trug den Zusatz „bereit zum Posten",
 * obwohl niemand sie freigegeben hatte. */
export function standAusZeile(r: ClipStand): Pruefstand {
  const clip = {
    status: r.status,
    review: r.review,
    file_key: r.hat_datei ? "x" : null,
    composition: r.composition,
    zeitmarken: r.zeitmarken,
    cps_warnings: r.cps_warnings,
    fidelity_warnings: r.fidelity_warnings,
    render_error: r.render_error,
    export_checks: r.export_checks,
    render_plan: r.plan_captions
      ? ({ captions: r.plan_captions, reframe: r.plan_reframe } as unknown as Clip["render_plan"])
      : null,
  } as unknown as Clip;
  return pruefstand({
    clip,
    freigabe: null,
    bearbeitet: (r.caption_style != null && Object.keys(r.caption_style).length > 0) || r.zeitmarken.length > 0 || r.composition.length > 1,
    quellformatAbweichend: r.quell_aspekt != null && r.quell_aspekt !== r.aspect,
  });
}

/* Was an einem Video noch Arbeit macht, in den Worten der Prüfseite.
 *
 * Ein Clip kann in mehreren Zahlen stehen: ein freigegebener ohne technischen Fehler ist
 * freigegeben UND postbereit. Das ist kein Zählfehler, sondern die Folge davon, dass es drei
 * Fragen sind.
 *
 * „zu prüfen" und „veraltet" standen hier einmal. Beide sind weggefallen: „veraltet" kann es
 * nicht mehr geben, seit Speichern sofort neu clippt, und „zu prüfen" war nur die Umkehrung von
 * „noch nicht entschieden" - eine Zahl, die an jedem frischen Video gleich hoch war wie die Zahl
 * der Clips und deshalb nichts sagte. */
export interface VideoStand {
  gesamt: number;
  fehler: number;
  wirdGebaut: number;
  postbereit: number;
  freigegeben: number;
  verworfen: number;
}

export function zaehlen(staende: Pruefstand[]): VideoStand {
  const z: VideoStand = { gesamt: 0, fehler: 0, wirdGebaut: 0, postbereit: 0, freigegeben: 0, verworfen: 0 };
  for (const p of staende) {
    if (p.redaktion === "verworfen") {
      z.verworfen += 1;
      continue;
    }
    z.gesamt += 1;
    if (p.redaktion === "freigegeben") z.freigegeben += 1;
    if (p.qualitaet === "fehler") z.fehler += 1;
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
