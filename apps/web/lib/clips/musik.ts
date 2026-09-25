/* Musik unter dem Clip: welches Stück, welche Stelle, wie laut.
 *
 * Dieselben Regeln wie workers/chopstr_worker/pipeline/musik.py. Dort ist die Wahrheit - der
 * Renderer entscheidet, was zu hören ist - und hier steht die Fassung, die die Oberfläche zum
 * Anzeigen und Bearbeiten braucht.
 *
 * „ab_s" ist die Sekunde IM STÜCK, an der die Wiedergabe beginnt. Nicht im Clip: die Musik läuft
 * immer von Anfang bis Ende des Clips. Ein Stück ist zwei bis drei Minuten lang, der Clip
 * dreissig Sekunden - welche dreissig Sekunden daraus darunter liegen, entscheidet alles. Wer die
 * Musikspur in der Zeitleiste verschiebt, ändert genau diese Zahl.
 */

export type MusikQuelle = "katalog" | "eigen";

export interface Musik {
  quelle: MusikQuelle;
  /* Ablageschlüssel (eigene Datei) oder Kennung im Katalog. */
  datei: string;
  name: string;
  ab_s: number;
  lautstaerke_db: number;
  ducking: boolean;
}

export type MusikEingabe = Partial<Record<keyof Musik, unknown>>;

/* Wie laut die Musik gegenüber der Sprache liegt. -18 ist der Wert aus der Erfahrung: hörbar,
 * aber nie im Weg. Spiegel von pipeline/musik.STANDARD_DB. */
export const STANDARD_DB = -18;
export const MIN_DB = -40;
export const MAX_DB = 0;

function zahl(v: unknown, ersatz: number): number {
  const f = typeof v === "number" ? v : Number(v);
  return Number.isFinite(f) ? f : ersatz;
}

/* Aus dem, was gespeichert ist, eine geprüfte Angabe machen - oder nichts. Grosszügig beim Lesen,
 * streng beim Ergebnis: ohne Datei gibt es keine Musik. */
export function lesen(roh: unknown): Musik | null {
  if (!roh || typeof roh !== "object") return null;
  const r = roh as MusikEingabe;
  const datei = String(r.datei ?? "").trim();
  if (!datei) return null;
  const quelle: MusikQuelle = r.quelle === "katalog" ? "katalog" : "eigen";
  return {
    quelle,
    datei,
    name: String(r.name ?? "").trim() || datei,
    ab_s: Math.max(0, Math.round(zahl(r.ab_s, 0) * 1000) / 1000),
    lautstaerke_db: Math.min(MAX_DB, Math.max(MIN_DB, Math.round(zahl(r.lautstaerke_db, STANDARD_DB) * 10) / 10)),
    ducking: r.ducking !== false,
  };
}

export function gleich(a: Musik | null, b: Musik | null): boolean {
  if (a == null || b == null) return a === b;
  return (
    a.datei === b.datei &&
    a.quelle === b.quelle &&
    Math.abs(a.ab_s - b.ab_s) < 0.01 &&
    Math.abs(a.lautstaerke_db - b.lautstaerke_db) < 0.05 &&
    a.ducking === b.ducking
  );
}

/* Die Lautstärke in Worten. „-18 dB" sagt einem Laien nichts; „leise" schon.
 *
 * Bewusst kein Prozentwert: Dezibel ist nicht linear, und „50 %" wäre eine Behauptung über
 * Lautheit, die nicht stimmt. */
export function lautstaerkeWort(db: number): string {
  if (db <= -30) return "sehr leise";
  if (db <= -20) return "leise";
  if (db <= -12) return "mittel";
  if (db <= -6) return "laut";
  return "sehr laut";
}
