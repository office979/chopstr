"use client";

import { useEffect, useRef, useState } from "react";

export interface WellenformDaten {
  bin_s: number;
  dauer_s: number;
  werte: number[];
}

/* Die Lautstärke über die Zeit, damit Schnitte an hörbaren Pausen möglich sind.
 *
 * Die Werte kommen aus derselben Audiospur, die auch die Analyse benutzt (signals.wellenform,
 * 25 Werte je Sekunde). Gezeichnet wird nur, was im sichtbaren Zeitfenster liegt; bei einem
 * zehnminütigen Video wären das sonst fünfzehntausend Striche für ein paar hundert Bildpunkte.
 *
 * Es wird bewusst NICHT geglättet oder verschönert: wer an einer Pause schneiden will, muss die
 * Pause sehen, und eine dekorative Welle zeigt sie nicht. */
export function Wellenform({
  daten,
  vonS,
  bisS,
  hoehe = 44,
}: {
  daten: WellenformDaten | null;
  vonS: number;
  bisS: number;
  hoehe?: number;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const [breite, setBreite] = useState(0);

  useEffect(() => {
    const el = ref.current?.parentElement;
    if (!el) return undefined;
    const messen = () => setBreite(el.clientWidth);
    messen();
    const beobachter = new ResizeObserver(messen);
    beobachter.observe(el);
    return () => beobachter.disconnect();
  }, []);

  useEffect(() => {
    const leinwand = ref.current;
    if (!leinwand || breite <= 0) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    leinwand.width = Math.round(breite * dpr);
    leinwand.height = Math.round(hoehe * dpr);
    const stift = leinwand.getContext("2d");
    if (!stift) return;
    stift.setTransform(dpr, 0, 0, dpr, 0, 0);
    stift.clearRect(0, 0, breite, hoehe);
    if (!daten || daten.werte.length === 0 || bisS <= vonS) return;

    const mitte = hoehe / 2;
    stift.fillStyle = "rgba(255,255,255,0.55)";
    /* Je Bildpunktspalte der lauteste Wert aus dem zugehörigen Zeitfenster: so verschwindet ein
     * kurzer Einsatz nicht zwischen zwei Abtastpunkten. */
    for (let px = 0; px < breite; px += 1) {
      const t0 = vonS + ((bisS - vonS) * px) / breite;
      const t1 = vonS + ((bisS - vonS) * (px + 1)) / breite;
      const i0 = Math.max(0, Math.floor(t0 / daten.bin_s));
      const i1 = Math.min(daten.werte.length - 1, Math.ceil(t1 / daten.bin_s));
      let spitze = 0;
      for (let i = i0; i <= i1; i += 1) spitze = Math.max(spitze, daten.werte[i] ?? 0);
      const h = Math.max(1, (spitze / 255) * (hoehe - 2));
      stift.fillRect(px, mitte - h / 2, 1, h);
    }
  }, [daten, vonS, bisS, breite, hoehe]);

  return (
    <div className="relative w-full" style={{ height: hoehe }}>
      <canvas ref={ref} className="block h-full w-full" aria-hidden="true" />
      {!daten && (
        <span className="absolute inset-0 flex items-center justify-center text-xs text-text-3">
          Tonspur wird beim Verarbeiten erzeugt
        </span>
      )}
    </div>
  );
}
