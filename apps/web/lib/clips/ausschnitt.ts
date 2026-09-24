/* Wo im Quellbild der Ausschnitt sitzt.
 *
 * Spiegel von workers/chopstr_worker/pipeline/reframe.py (crop_geometry, crop_origin,
 * plan_shots_aus_zielen) und tracking.blickraum_anker. Gebraucht wird die Rechnung hier, damit die
 * Vorschau sofort zeigt, was eine Aenderung bewirkt: wer im Bild ist, wie nah. Ohne sie muesste
 * erst gerendert werden, um eine Entscheidung zu sehen, und dann ist die Entscheidung schon
 * getroffen.
 *
 * Dass dieselbe Rechnung zweimal dasteht, ist eine Last. Deshalb pruefen die Tests sie nicht gegen
 * erdachte Werte, sondern gegen eine Datei, die der Python-Renderer selbst erzeugt hat
 * (tests/fixtures-ausschnitt.json). Laufen die beiden Seiten auseinander, faellt es dort auf. */

const DRITTEL = 1 / 3;
const BLICKRAUM_AB = 0.08;

/* Auf die naechste gerade Zahl ABRUNDEN, nicht runden. Spiegel von reframe._even; Codecs brauchen
 * gerade Kanten, und wer hier rundet statt abzurunden, bekommt bei 1215 eine 1216 heraus, wo der
 * Renderer 1214 nimmt - und die Vorschau zeigt einen anderen Ausschnitt als das Ergebnis. */
function gerade(n: number): number {
  return Math.floor(Math.trunc(n) / 2) * 2;
}

/* Runden wie Python, also bei genau ,5 zur GERADEN Zahl.
 *
 * Math.round rundet ,5 immer auf: aus 472,5 wird 473, waehrend Python 472 nimmt. Genau dieser eine
 * Bildpunkt ist beim Abgleich mit dem Renderer aufgefallen. Er faellt im Bild nicht auf, aber eine
 * Vorschau, die sich vom Ergebnis unterscheidet, ist genau das, was sie nicht sein darf. */
function rundenWiePython(n: number): number {
  const ab = Math.floor(n);
  const rest = n - ab;
  if (Math.abs(rest - 0.5) > 1e-9) return Math.round(n);
  return ab % 2 === 0 ? ab : ab + 1;
}

export interface Ausschnitt {
  x: number;
  y: number;
  w: number;
  h: number;
}

/* Groesster Ausschnitt mit dem Ziel-Seitenverhaeltnis. */
export function grundAusschnitt(srcW: number, srcH: number, outW: number, outH: number): [number, number] {
  const verhaeltnis = outW / outH;
  let w: number;
  let h: number;
  if (srcW / srcH >= verhaeltnis) {
    h = gerade(srcH);
    w = gerade(h * verhaeltnis);
  } else {
    w = gerade(srcW);
    h = gerade(w / verhaeltnis);
  }
  return [Math.max(2, Math.min(w, gerade(srcW))), Math.max(2, Math.min(h, gerade(srcH)))];
}

/* Wo im Ausschnitt das Gesicht sitzt: 0,33 links, 0,5 mittig, 0,67 rechts.
 *
 * Entscheidend ist die Lage der ANDEREN Personen, nicht die Lage im Bild: sitzt jemand rechts von
 * mir, gehoere ich auf das linke Drittel, damit er mit ins Bild kommt. Ist sonst niemand da, bleibt
 * nur die Lage im Bild als Anhaltspunkt. */
export function blickraumAnker(gesichtCx: number, quelleBreite: number, andere: number[] = []): number {
  if (quelleBreite <= 0) return 0.5;
  if (andere.length > 0) {
    const mindest = quelleBreite * BLICKRAUM_AB;
    const links = andere.some((x) => x < gesichtCx - mindest);
    const rechts = andere.some((x) => x > gesichtCx + mindest);
    if (links && !rechts) return 1 - DRITTEL;
    if (rechts && !links) return DRITTEL;
    return 0.5;
  }
  const versatz = (gesichtCx - quelleBreite / 2) / quelleBreite;
  if (versatz < -BLICKRAUM_AB) return DRITTEL;
  if (versatz > BLICKRAUM_AB) return 1 - DRITTEL;
  return 0.5;
}

export interface AusschnittEingabe {
  srcW: number;
  srcH: number;
  outW: number;
  outH: number;
  /* Bildstelle der Person. Null heisst: kein Gesicht, mittig schneiden. */
  cx: number | null;
  cy: number | null;
  /* Wo im Ausschnitt das Gesicht sitzt (siehe blickraumAnker). */
  anker: number;
  /* 1,0 ist der volle Ausschnitt, groesser heisst enger schneiden. */
  zoom: number;
}

/* Die Augenlinie: senkrecht sitzt die Gesichtsmitte bei 37 Prozent der Hoehe. Spiegel von
 * reframe.EYE_LINE. */
export const AUGENLINIE = 0.37;

export function ausschnittBerechnen({ srcW, srcH, outW, outH, cx, cy, anker, zoom }: AusschnittEingabe): Ausschnitt {
  const [grundW, grundH] = grundAusschnitt(srcW, srcH, outW, outH);
  let w = grundW;
  let h = grundH;
  if (zoom > 1) {
    /* Naeher heran heisst enger schneiden; das Skalieren auf die Ausgabegroesse macht daraus den
     * Zoom. Das Seitenverhaeltnis bleibt, sonst waere das Bild verzerrt. */
    w = Math.max(16, gerade(grundW / zoom));
    h = Math.max(16, gerade(grundH / zoom));
  }
  const x = cx == null ? (srcW - w) / 2 : cx - anker * w;
  const y = cy == null ? (h >= srcH ? 0 : (srcH - h) / 2) : cy - AUGENLINIE * h;
  return {
    x: Math.max(0, Math.min(rundenWiePython(x), srcW - w)),
    y: Math.max(0, Math.min(rundenWiePython(y), srcH - h)),
    w,
    h,
  };
}
