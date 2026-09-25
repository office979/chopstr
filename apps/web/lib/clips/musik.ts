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

/* ---------------------------------------------------------------------------------------------
 * Die Musik in der Vorschau
 *
 * Die Vorschau spielt das QUELLVIDEO ab, nicht den fertigen Clip - nur so ist jede Änderung sofort
 * zu sehen, ohne zu clippen. Die Musik steckt aber erst im fertigen Clip. Wer sie einstellt und
 * dann auf Abspielen drückt, hört deshalb nichts und hält das Feature für kaputt.
 *
 * Also läuft in der Vorschau ein zweites Tonelement mit der Musikdatei mit. Damit das nicht nach
 * „irgendwas spielt" klingt, sondern nach dem, was später herauskommt, rechnen die folgenden
 * Funktionen dieselben Hüllkurven wie die Filterkette im Renderer.
 * ------------------------------------------------------------------------------------------- */

/* Ein- und Ausblenden an den Rändern des Clips. Spiegel von pipeline/musik.EINBLENDE_S/AUSBLENDE_S. */
export const EINBLENDE_S = 0.8;
export const AUSBLENDE_S = 1.2;

/* Wie weit die Musik unter der Stimme weicht - und warum hier eine feste Zahl steht.
 *
 * Im fertigen Clip macht das `sidechaincompress`: es misst den Pegel der Stimme und senkt die
 * Musik um so mehr, je lauter gesprochen wird. Die Vorschau kann das nicht messen, sie kennt nur
 * die Wortzeiten aus dem Transkript. Aus Schwelle (0,06 ≈ -24,4 dB) und Verhältnis (8:1) ergibt
 * sich bei üblichen Sprachpegeln zwischen -15 und -9 dBFS eine Absenkung von acht bis vierzehn
 * Dezibel; zehn ist die Mitte davon.
 *
 * Das ist eine SCHÄTZUNG, keine Messung. Sie reicht, um zu beurteilen, ob die Musik im Weg ist -
 * auf das Dezibel genau ist nur der geclippte Clip. */
export const DUCK_ABSENKUNG_DB = -10;
export const DUCK_ATTACK_MS = 20;
export const DUCK_RELEASE_MS = 600;

/* Dezibel in einen Faktor. -6 dB ist die halbe Amplitude, -20 dB ein Zehntel. */
export function ausDezibel(db: number): number {
  return Math.pow(10, db / 20);
}

/* Wo in den Blenden liegt diese Stelle? 0 = still, 1 = voller Pegel. */
export function blende(clipzeit: number, clipDauer: number): number {
  if (!(clipDauer > 0)) return 0;
  const t = Math.min(Math.max(clipzeit, 0), clipDauer);
  const ein = EINBLENDE_S > 0 ? t / EINBLENDE_S : 1;
  const aus = AUSBLENDE_S > 0 ? (clipDauer - t) / AUSBLENDE_S : 1;
  return Math.max(0, Math.min(1, ein, aus));
}

/* Ein Schritt der Absenkung, `dtMs` Millisekunden nach dem letzten.
 *
 * Nicht springen, sondern gleiten: ein harter Wechsel zwischen laut und leise pumpt hörbar. Der
 * Weg nach unten ist kurz (20 ms, sonst rutscht der Wortanfang durch), der Weg nach oben lang
 * (600 ms, sonst hebt sich die Musik in jeder Atempause). */
export function duckingSchritt(jetzt: number, spricht: boolean, dtMs: number): number {
  const ziel = spricht ? ausDezibel(DUCK_ABSENKUNG_DB) : 1;
  const zeit = spricht ? DUCK_ATTACK_MS : DUCK_RELEASE_MS;
  if (!(dtMs > 0)) return jetzt;
  if (!(zeit > 0)) return ziel;
  const anteil = Math.min(1, 1 - Math.exp(-dtMs / zeit));
  return jetzt + (ziel - jetzt) * anteil;
}

/* Wie laut das Tonelement der Vorschau an dieser Stelle stehen soll: eingestellte Lautstärke mal
 * Blende mal Absenkung. Begrenzt auf 0 … 1, weil `HTMLMediaElement.volume` nichts anderes nimmt. */
export function vorschauPegel(m: Musik, clipzeit: number, clipDauer: number, absenkung: number): number {
  const roh = ausDezibel(m.lautstaerke_db) * blende(clipzeit, clipDauer) * (m.ducking ? absenkung : 1);
  return Math.min(1, Math.max(0, roh));
}

/* Ab wann die Stelle im Stück nachgezogen wird.
 *
 * Jedes Setzen von ``currentTime`` ist ein Sprung im Ton, den man als Knacksen hört. Solange Bild
 * und Ton beide in Echtzeit laufen, bleiben sie von selbst zusammen; nachgezogen wird nur, wenn
 * wirklich etwas passiert ist - ein Sprung in der Zeitleiste, eine übersprungene Lücke, ein Ruckler. */
export const NACHZIEH_SCHWELLE_S = 0.25;

export interface TonEingabe {
  musik: Musik;
  /* Wo der Clip steht, in CLIPZEIT - nicht in Quellzeit. Entfernte Stellen kommen im fertigen
   * Clip nicht vor, also darf die Musik dort auch nicht weiterlaufen. */
  clipzeit: number;
  clipDauer: number;
  /* Spricht an dieser Stelle jemand? Aus den Wortzeiten des Transkripts. */
  spricht: boolean;
  /* Die Absenkung aus dem letzten Bild, damit die Hüllkurve weiterläuft. */
  absenkung: number;
  /* Wie lange das letzte Bild her ist, in Millisekunden. */
  dtMs: number;
  /* Wo das Tonelement gerade steht. */
  tonZeit: number;
  /* Wie lang das Stück ist. Null, solange der Browser es nicht gelesen hat. */
  tonLaenge: number | null;
}

export interface TonLage {
  /* Wo das Stück stehen sollte. */
  stelle: number;
  /* Soll die Stelle gesetzt werden? Nur, wenn sie zu weit auseinanderläuft. */
  nachziehen: boolean;
  /* Lautstärke für das Tonelement, 0 … 1. */
  pegel: number;
  /* Die Absenkung für das nächste Bild. */
  absenkung: number;
  /* Das Stück ist zu Ende, bevor der Clip es ist. Im geclippten Clip füllt ``apad`` mit Stille;
   * hier heisst das anhalten - und NICHT von vorn beginnen, das täte kein Renderer. */
  zuEnde: boolean;
}

/* Ein Bild der Musikwiedergabe in der Vorschau: wo das Stück stehen und wie laut es sein soll.
 *
 * Hier steht alles, was man falsch machen kann, an einer Stelle - und nichts davon berührt den
 * Browser. Das Tonelement bekommt nur das Ergebnis. */
export function tonLage(e: TonEingabe): TonLage {
  const stelle = e.musik.ab_s + Math.max(0, e.clipzeit);
  const zuEnde = e.tonLaenge != null && stelle >= e.tonLaenge - 0.02;
  const absenkung = e.musik.ducking ? duckingSchritt(e.absenkung, e.spricht, e.dtMs) : 1;
  return {
    stelle,
    nachziehen: !zuEnde && Math.abs(e.tonZeit - stelle) > NACHZIEH_SCHWELLE_S,
    pegel: zuEnde ? 0 : vorschauPegel(e.musik, e.clipzeit, e.clipDauer, absenkung),
    absenkung,
    zuEnde,
  };
}
