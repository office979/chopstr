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
  zoom_in: "Zoom in",
  zoom_out: "Zoom out",
};

/* Was der Effekt tut, in einem Satz. Steht in der Auswahl, damit niemand raten muss, was
 * „Näher heran" im fertigen Video heisst. */
export const EFFEKT_SATZ: Record<EffektArt, string> = {
  zoom_in: "Fährt sanft näher heran und bleibt dort, solange der Block dauert.",
  zoom_out: "Fährt sanft heraus, rundherum steht Schwarz, und bleibt dort.",
};

export const STAERKE = 0.1;
export const MIN_DAUER_S = 0.4;
export const MAX_DAUER_S = 6;
export const STANDARD_DAUER_S = 1;
/* Wie lange die Fahrt dauert, in Sekunden. Danach steht das Bild still. Spiegel von
 * pipeline/effekte.ANSTIEG_S. */
export const ANSTIEG_S = 0.45;

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

/* Der Verlauf über den Block: sanft hinein und dann BLEIBEN. Smoothstep für die Fahrt, weil ein
 * linearer Anstieg sichtbar ansetzt und sichtbar abbricht - das nimmt man als Ruckeln wahr.
 * Danach bleibt der Wert auf 1. Spiegel von pipeline/effekte._form. */
function form(tImEffekt: number, dauerS: number): number {
  const fahrt = Math.min(ANSTIEG_S, dauerS);
  if (fahrt <= 0) return 1;
  if (tImEffekt >= fahrt) return 1;
  const x = Math.max(0, tImEffekt) / fahrt;
  return x * x * (3 - 2 * x);
}

/* Der Zoomfaktor zum Zeitpunkt t (Sekunden im Clip). 1 heisst: unberührt. */
export function faktor(effekte: Effekt[], t: number): number {
  let z = 1;
  for (const e of effekte) {
    if (t < e.ab_s || t > e.ab_s + e.dauer_s) continue;
    z += (e.art === "zoom_out" ? -1 : 1) * STAERKE * form(t - e.ab_s, e.dauer_s);
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
