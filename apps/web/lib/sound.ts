/* Kurzer Klang, wenn die Analyse fertig ist. Nur Anzeige, kein Zustand.
 *
 * Browser lassen Ton erst zu, nachdem der Mensch die Seite einmal berührt hat. Schlägt das
 * Abspielen fehl, wird es still verworfen: ein fehlender Klang darf nie eine Weiterleitung
 * aufhalten oder eine Fehlermeldung erzeugen.
 *
 * Die drei Varianten liegen in public/sound. Welche gilt, steht in DONE_SOUND. */

export type DoneSound = "fertig-1" | "fertig-2" | "fertig-3";

/* Ausgewählte Variante. Zum Wechseln nur diese Zeile ändern. */
export const DONE_SOUND: DoneSound = "fertig-1";

/* Leise. Der Klang soll bestätigen, nicht erschrecken. */
const VOLUME = 0.35;

let cached: HTMLAudioElement | null = null;

export function playDoneSound(sound: DoneSound = DONE_SOUND): void {
  if (typeof window === "undefined") return;
  /* Wer Bewegung reduziert, will in der Regel auch keine akustischen Überraschungen. */
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  try {
    if (!cached || !cached.src.includes(sound)) {
      cached = new Audio(`/sound/${sound}.wav`);
      cached.preload = "auto";
    }
    cached.volume = VOLUME;
    cached.currentTime = 0;
    void cached.play().catch(() => {});
  } catch {
    /* Kein Ton ist kein Fehler */
  }
}
