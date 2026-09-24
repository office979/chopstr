/* Der Schnitt eines Clips: welche Abschnitte der Quelle er zeigt.
 *
 * Die Komposition ist eine Liste von Abschnitten in Quellzeit (``clips.composition``), die der
 * Renderer der Reihe nach aneinanderhaengt. Alles Bearbeiten laeuft darueber: kuerzen heisst, den
 * ersten oder letzten Abschnitt zu beschneiden; teilen heisst, einen Abschnitt in zwei zu zerlegen;
 * entfernen heisst, einen Abschnitt wegzulassen. Die Quelldatei wird nie angefasst.
 *
 * Alles hier ist reine Rechnung ohne Zustand, damit es pruefbar bleibt und Rueckgaengig einfach
 * ueber eine Liste alter Fassungen geht. */

import type { CandidateSegment } from "@/lib/repo/types";

/* Kuerzer als das ergibt keinen sinnvollen Abschnitt mehr: darunter ist es ein Ruckler, kein
 * Schnitt, und der Renderer haengt an jeder Naht eine Tonblende von 20 ms an. */
export const MIN_ABSCHNITT_S = 0.25;

export type Schnitt = CandidateSegment[];

export function dauer(schnitt: Schnitt): number {
  return schnitt.reduce((s, a) => s + Math.max(0, a.end - a.start), 0);
}

/* Quellzeit -> Zeit im fertigen Clip. Faellt die Stelle in eine entfernte Luecke, kommt der Anfang
 * des naechsten Abschnitts heraus. */
export function inClipzeit(schnitt: Schnitt, quellzeit: number): number {
  let vorher = 0;
  for (const a of schnitt) {
    if (quellzeit < a.start) return vorher;
    if (quellzeit <= a.end) return vorher + (quellzeit - a.start);
    vorher += a.end - a.start;
  }
  return vorher;
}

/* Zeit im fertigen Clip -> Quellzeit. Gegenstueck zu inClipzeit. */
export function inQuellzeit(schnitt: Schnitt, clipzeit: number): number {
  let rest = Math.max(0, clipzeit);
  for (const a of schnitt) {
    const laenge = a.end - a.start;
    if (rest <= laenge) return a.start + rest;
    rest -= laenge;
  }
  const letzter = schnitt[schnitt.length - 1];
  return letzter ? letzter.end : 0;
}

/* Liegt diese Quellzeit in einem gezeigten Abschnitt? */
export function istSichtbar(schnitt: Schnitt, quellzeit: number): boolean {
  return schnitt.some((a) => quellzeit >= a.start && quellzeit <= a.end);
}

export function abschnittBei(schnitt: Schnitt, quellzeit: number): number {
  return schnitt.findIndex((a) => quellzeit >= a.start && quellzeit <= a.end);
}

/* Aufraeumen: zu kurze Abschnitte fliegen raus, die Reihenfolge stimmt, und nichts ueberlappt.
 *
 * Beruehrende Abschnitte bleiben bewusst zwei Abschnitte: genau die entstehen beim Teilen, und
 * wer geteilt hat, will die Naht sehen. Beim Bauen werden durchgehende Abschnitte wieder
 * zusammengefasst (render_plan.normalize_segments), damit dort keine Tonblende hoerbar wird. */
export function aufraeumen(schnitt: Schnitt): Schnitt {
  const sortiert = [...schnitt]
    .map((a) => ({ ...a, start: Math.max(0, a.start), end: a.end }))
    .filter((a) => a.end - a.start >= MIN_ABSCHNITT_S)
    .sort((a, b) => a.start - b.start);
  const aus: Schnitt = [];
  for (const a of sortiert) {
    const vor = aus[aus.length - 1];
    /* Ueberlappung: der spaetere Abschnitt faengt erst dort an, wo der vorige aufhoert. Sonst
     * kaeme dieselbe Stelle zweimal im Clip vor. */
    const start = vor ? Math.max(a.start, vor.end) : a.start;
    if (a.end - start < MIN_ABSCHNITT_S) continue;
    aus.push({ ...a, start });
  }
  return aus;
}

/* Anfang kuerzen: alles vor ``quellzeit`` faellt weg. */
export function anfangKuerzen(schnitt: Schnitt, quellzeit: number): Schnitt {
  return aufraeumen(schnitt.map((a) => (a.end <= quellzeit ? { ...a, end: a.start } : { ...a, start: Math.max(a.start, quellzeit) })));
}

/* Ende kuerzen: alles nach ``quellzeit`` faellt weg. */
export function endeKuerzen(schnitt: Schnitt, quellzeit: number): Schnitt {
  return aufraeumen(schnitt.map((a) => (a.start >= quellzeit ? { ...a, start: a.end } : { ...a, end: Math.min(a.end, quellzeit) })));
}

/* An dieser Stelle teilen. Aus einem Abschnitt werden zwei, die luecken los aneinander liegen;
 * erst das Entfernen eines Teils macht daraus eine Luecke. */
export function teilen(schnitt: Schnitt, quellzeit: number): Schnitt {
  const i = abschnittBei(schnitt, quellzeit);
  if (i < 0) return schnitt;
  const a = schnitt[i];
  if (quellzeit - a.start < MIN_ABSCHNITT_S || a.end - quellzeit < MIN_ABSCHNITT_S) return schnitt;
  return [
    ...schnitt.slice(0, i),
    { ...a, end: quellzeit },
    { ...a, start: quellzeit },
    ...schnitt.slice(i + 1),
  ];
}

/* Einen Abschnitt entfernen. Die Luecke schliesst sich im fertigen Clip von selbst, weil der
 * Renderer nur noch die uebrigen Abschnitte aneinanderhaengt. */
export function entfernen(schnitt: Schnitt, index: number): Schnitt {
  if (index < 0 || index >= schnitt.length) return schnitt;
  if (schnitt.length <= 1) return schnitt; // der letzte Abschnitt bleibt, sonst gaebe es keinen Clip
  return aufraeumen(schnitt.filter((_, i) => i !== index));
}

/* Eine Kante verschieben: ``rand`` 0 ist der Anfang des Abschnitts, 1 sein Ende.
 * Die Nachbarn setzen die Grenzen, damit sich Abschnitte nie ueberlappen. */
export function randSetzen(schnitt: Schnitt, index: number, rand: 0 | 1, quellzeit: number, quelleDauer: number): Schnitt {
  const a = schnitt[index];
  if (!a) return schnitt;
  const vor = schnitt[index - 1];
  const nach = schnitt[index + 1];
  const kopie = schnitt.map((x) => ({ ...x }));
  if (rand === 0) {
    const min = vor ? vor.end : 0;
    kopie[index].start = Math.max(min, Math.min(quellzeit, a.end - MIN_ABSCHNITT_S));
  } else {
    const max = nach ? nach.start : quelleDauer;
    kopie[index].end = Math.min(max, Math.max(quellzeit, a.start + MIN_ABSCHNITT_S));
  }
  return kopie;
}

/* Zwei Schnitte vergleichen, damit „geaendert" nicht an der Objektgleichheit haengt. */
export function gleich(a: Schnitt, b: Schnitt): boolean {
  if (a.length !== b.length) return false;
  return a.every((x, i) => Math.abs(x.start - b[i].start) < 1e-4 && Math.abs(x.end - b[i].end) < 1e-4);
}
