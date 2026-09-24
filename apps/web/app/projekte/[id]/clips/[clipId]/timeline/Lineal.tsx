"use client";

import { useMemo } from "react";

export function timecode(t: number, mitZehntel = false): string {
  const s = Math.max(0, t);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const sek = Math.floor(rest);
  if (!mitZehntel) return `${m}:${String(sek).padStart(2, "0")}`;
  return `${m}:${String(sek).padStart(2, "0")},${Math.floor((rest - sek) * 10)}`;
}

/* Welcher Abstand zwischen zwei beschrifteten Strichen? Gesucht ist der kleinste Wert aus einer
 * festen Liste, bei dem die Beschriftungen noch Platz haben. Frei gerechnete Abstaende ergeben
 * Werte wie „alle 3,7 s", und die liest niemand. */
const STUFEN = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

export function schrittweite(sichtbarS: number, breitePx: number, mindestAbstandPx = 64): number {
  const proSekunde = breitePx / Math.max(sichtbarS, 1e-6);
  for (const stufe of STUFEN) {
    if (stufe * proSekunde >= mindestAbstandPx) return stufe;
  }
  return STUFEN[STUFEN.length - 1];
}

/* Das Zeitlineal ueber der Spur. Beschriftet wird in Quellzeit, weil alles andere in der Leiste
 * auch in Quellzeit liegt; die Dauer des fertigen Clips steht daneben. */
export function Lineal({ vonS, bisS, breitePx }: { vonS: number; bisS: number; breitePx: number }) {
  const striche = useMemo(() => {
    const sichtbar = bisS - vonS;
    if (sichtbar <= 0 || breitePx <= 0) return [];
    const schritt = schrittweite(sichtbar, breitePx);
    const erster = Math.ceil(vonS / schritt) * schritt;
    const aus: { t: number; anteil: number }[] = [];
    for (let t = erster; t <= bisS + 1e-6; t += schritt) {
      aus.push({ t, anteil: (t - vonS) / sichtbar });
    }
    return aus;
  }, [vonS, bisS, breitePx]);

  return (
    <div className="relative h-5 w-full select-none" aria-hidden="true">
      {striche.map((s) => {
        /* Am Rand wird die Beschriftung nach innen gesetzt, sonst waere sie abgeschnitten. */
        const amAnfang = s.anteil < 0.03;
        const amEnde = s.anteil > 0.95;
        return (
          <div key={s.t} className="absolute top-0 flex h-full flex-col" style={{ left: `${s.anteil * 100}%` }}>
            <span className="h-2 w-px bg-white/25" />
            <span
              className="mt-0.5 whitespace-nowrap text-[10px] tabular-nums leading-none text-text-3"
              style={{ transform: amAnfang ? "none" : amEnde ? "translateX(-100%)" : "translateX(-50%)" }}
            >
              {timecode(s.t)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
