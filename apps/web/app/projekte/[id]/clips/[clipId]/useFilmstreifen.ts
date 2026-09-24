"use client";

import { useEffect, useState } from "react";

/* Einzelbilder aus dem Video im Browser zeichnen, wenn es noch keinen gerenderten Filmstreifen gibt.
 *
 * Der Grund: der Streifen entsteht beim Render, aber gebraucht wird er VORHER. Wer einen Clip
 * zurechtschiebt, will sehen, wo er landet, und nicht erst rendern muessen, um navigieren zu
 * koennen. Das Video liegt ohnehin schon im Player; ein verstecktes zweites Element zieht daraus
 * die Bilder.
 *
 * Gezeichnet wird eines nach dem anderen und das Ergebnis nach jedem Bild gemeldet, damit der
 * Streifen von links nach rechts auffuellt statt am Ende auf einmal dazustehen. Ein Abbruch
 * (Seite gewechselt, Bereich geaendert) stoppt die Schleife.
 */
export function useFilmstreifen(src: string | null, vonS: number, bisS: number, bilder = 20): string[] {
  const [streifen, setStreifen] = useState<string[]>([]);

  useEffect(() => {
    if (!src || !(bisS > vonS)) {
      /* Ohne Video gibt es nichts zu zeichnen. Das Leeren gehoert in den Lauf unten, nicht hierher:
       * setState direkt im Effekt loest eine zweite Runde aus, bevor ueberhaupt etwas passiert ist. */
      return undefined;
    }

    let abgebrochen = false;
    const video = document.createElement("video");
    video.src = src;
    video.muted = true;
    video.preload = "auto";
    /* Ohne playsInline zieht iOS das Video in den Vollbildplayer, sobald es laedt. */
    video.playsInline = true;

    const lauf = async () => {
      try {
        await new Promise<void>((fertig, schiefgegangen) => {
          if (video.readyState >= 1) return fertig();
          video.addEventListener("loadedmetadata", () => fertig(), { once: true });
          video.addEventListener("error", () => schiefgegangen(new Error("Video nicht lesbar")), { once: true });
        });
        if (abgebrochen) return;

        const hoehe = 108;
        const breite = Math.max(2, Math.round((hoehe * video.videoWidth) / Math.max(1, video.videoHeight)));
        const leinwand = document.createElement("canvas");
        leinwand.width = breite;
        leinwand.height = hoehe;
        const stift = leinwand.getContext("2d");
        if (!stift) return;

        const gesammelt: string[] = [];
        setStreifen([]);
        for (let i = 0; i < bilder && !abgebrochen; i += 1) {
          /* In die Mitte des jeweiligen Abschnitts, nicht an dessen Anfang: am Anfang steht oft
           * noch das letzte Bild der vorigen Einstellung. */
          const t = vonS + ((i + 0.5) / bilder) * (bisS - vonS);
          const ok = await new Promise<boolean>((fertig) => {
            const zeit = setTimeout(() => fertig(false), 4000);
            video.addEventListener(
              "seeked",
              () => {
                clearTimeout(zeit);
                fertig(true);
              },
              { once: true },
            );
            video.currentTime = t;
          });
          if (!ok || abgebrochen) break;
          stift.drawImage(video, 0, 0, breite, hoehe);
          gesammelt.push(leinwand.toDataURL("image/jpeg", 0.6));
          setStreifen([...gesammelt]);
        }
      } catch {
        /* Kein Streifen ist kein Fehler: die Zeitleiste bleibt bedienbar, nur ohne Bilder. */
      } finally {
        video.removeAttribute("src");
        video.load();
      }
    };
    void lauf();
    return () => {
      abgebrochen = true;
    };
  }, [src, vonS, bisS, bilder]);

  return streifen;
}
