/* Effekte auf der Zeitachse des Clips: Zoom hinein, Zoom heraus.
 *
 * Dieselben Regeln wie workers/chopstr_worker/pipeline/effekte.py. Dort ist die Wahrheit - der
 * Renderer entscheidet, was im Bild passiert - und hier steht die Fassung, die die Oberfläche zum
 * Anzeigen und Bearbeiten braucht. Die Tests halten beide auf denselben Zahlen.
 *
 * „ab_s" ist die Sekunde IM FERTIGEN CLIP, wie bei den Zeitmarken. Wer den Schnitt ändert,
 * verschiebt damit die Effekte - richtig so, sie hängen an dem, was gesagt wird.
 */

export type EffektArt = "zoom_in" | "zoom_out";

export interface Effekt {
  art: EffektArt;
  ab_s: number;
  dauer_s: number;
}

export const EFFEKT_ARTEN: EffektArt[] = ["zoom_in", "zoom_out"];

export const EFFEKT_LABEL: Record<EffektArt, string> = {
  zoom_in: "Näher heran",
  zoom_out: "Weiter weg",
};

/* Was der Effekt tut, in einem Satz. Steht in der Auswahl, damit niemand raten muss, was
 * „Näher heran" im fertigen Video heisst. */
export const EFFEKT_SATZ: Record<EffektArt, string> = {
  zoom_in: "Geht schnell näher heran und lässt langsam wieder los. Betont ein Wort.",
  zoom_out: "Beginnt nah und zieht sich ruhig zurück. Öffnet eine Szene.",
};

export const STAERKE = 0.1;
export const MIN_DAUER_S = 0.4;
export const MAX_DAUER_S = 6;
export const STANDARD_DAUER_S = 1.4;
const ANSTIEG = 0.18;

function zahl(v: unknown, ersatz: number): number {
  const f = typeof v === "number" ? v : Number(v);
  return Number.isFinite(f) ? f : ersatz;
}

/* Aus dem, was gespeichert ist, eine geprüfte Liste machen. Grosszügig beim Lesen, streng beim
 * Ergebnis - wie im Worker. */
export function lesen(roh: unknown, clipDauerS: number): Effekt[] {
  if (!Array.isArray(roh)) return [];
  const aus: Effekt[] = [];
  for (const e of roh) {
    if (!e || typeof e !== "object") continue;
    const art = (e as { art?: unknown }).art;
    if (art !== "zoom_in" && art !== "zoom_out") continue;
    const ab = Math.max(0, zahl((e as { ab_s?: unknown }).ab_s, 0));
    if (ab >= clipDauerS) continue;
    const dauer = Math.min(
      Math.max(zahl((e as { dauer_s?: unknown }).dauer_s, STANDARD_DAUER_S), MIN_DAUER_S),
      MAX_DAUER_S,
      clipDauerS - ab,
    );
    if (dauer < MIN_DAUER_S) continue;
    aus.push({ art, ab_s: Math.round(ab * 1000) / 1000, dauer_s: Math.round(dauer * 1000) / 1000 });
  }
  aus.sort((a, b) => a.ab_s - b.ab_s);
  return entzerren(aus);
}

/* Überschneidungen auflösen: der frühere gewinnt, der spätere rückt nach. Zwei Zooms übereinander
 * addieren sich im Bild und sehen nach einem Fehler aus. */
export function entzerren(effekte: Effekt[]): Effekt[] {
  const aus: Effekt[] = [];
  for (const roh of effekte) {
    let e = roh;
    const vor = aus[aus.length - 1];
    if (vor && e.ab_s < vor.ab_s + vor.dauer_s) {
      const neuAb = vor.ab_s + vor.dauer_s;
      const rest = e.ab_s + e.dauer_s - neuAb;
      if (rest < MIN_DAUER_S) continue;
      e = { art: e.art, ab_s: Math.round(neuAb * 1000) / 1000, dauer_s: Math.round(rest * 1000) / 1000 };
    }
    aus.push(e);
  }
  return aus;
}

function form(art: EffektArt, u: number): number {
  if (art === "zoom_out") return (1 - u) ** 2;
  if (u <= ANSTIEG) {
    const x = u / ANSTIEG;
    return x * x * (3 - 2 * x);
  }
  const rest = (u - ANSTIEG) / (1 - ANSTIEG);
  return (1 - rest) ** 2;
}

/* Der Zoomfaktor zum Zeitpunkt t (Sekunden im Clip). 1 heisst: unberührt. */
export function faktor(effekte: Effekt[], t: number): number {
  let z = 1;
  for (const e of effekte) {
    const u = (t - e.ab_s) / e.dauer_s;
    if (u < 0 || u > 1) continue;
    z += STAERKE * form(e.art, u);
  }
  return z;
}

/* Einen Effekt anlegen, verschieben, verlängern oder entfernen. Alle vier geben eine neue,
 * geprüfte Liste zurück - der Aufrufer muss nichts nachräumen. */
export function hinzufuegen(effekte: Effekt[], art: EffektArt, abS: number, clipDauerS: number): Effekt[] {
  const dauer = Math.min(STANDARD_DAUER_S, clipDauerS - abS);
  if (dauer < MIN_DAUER_S) return effekte;
  return lesen([...effekte, { art, ab_s: abS, dauer_s: dauer }], clipDauerS);
}

export function verschieben(effekte: Effekt[], index: number, neuAbS: number, clipDauerS: number): Effekt[] {
  const e = effekte[index];
  if (!e) return effekte;
  const ohne = effekte.filter((_, i) => i !== index);
  const ab = Math.min(Math.max(0, neuAbS), Math.max(0, clipDauerS - e.dauer_s));
  return lesen([...ohne, { ...e, ab_s: ab }], clipDauerS);
}

export function dauerAendern(effekte: Effekt[], index: number, neuDauerS: number, clipDauerS: number): Effekt[] {
  const e = effekte[index];
  if (!e) return effekte;
  const ohne = effekte.filter((_, i) => i !== index);
  return lesen([...ohne, { ...e, dauer_s: neuDauerS }], clipDauerS);
}

export function entfernen(effekte: Effekt[], index: number): Effekt[] {
  return effekte.filter((_, i) => i !== index);
}

/* Gleich? Für den Vergleich „zeigt das gebaute Video noch, was eingestellt ist". */
export function gleich(a: Effekt[], b: Effekt[]): boolean {
  if (a.length !== b.length) return false;
  return a.every(
    (e, i) =>
      e.art === b[i].art &&
      Math.round(e.ab_s * 100) === Math.round(b[i].ab_s * 100) &&
      Math.round(e.dauer_s * 100) === Math.round(b[i].dauer_s * 100),
  );
}
