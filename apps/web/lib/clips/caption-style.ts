/* Untertitel-Stil je Clip.
 *
 * Spiegel von workers/chopstr_worker/pipeline/captions_de.py (STIL_GRENZEN, style_anwenden). Die
 * Grenzen stehen an beiden Stellen, weil beide Seiten sie brauchen: der Renderer verlaesst sich
 * nicht auf die Oberflaeche, und die Oberflaeche soll gar nicht erst etwas anbieten, was der
 * Renderer hinterher zurechtstutzt. test_caption_style.py haelt die Python-Seite fest,
 * caption-style.test.ts diese hier, und ein Test vergleicht beide Zahlen miteinander.
 *
 * Alle Groessen gelten fuer 1080x1920. Der Worker rechnet sie auf die tatsaechliche Ausgabegroesse
 * um; die Oberflaeche zeigt immer hochkant. */

import fontsJson from "../../../../packages/design/caption_fonts.json";
import { zahlImRahmen } from "@/lib/zahl";

/* Bewusst ein Typ-Alias und keine Schnittstelle: nur ein Alias laesst sich an ein
 * ``Record<string, unknown>`` uebergeben, und genau das ist die Form, in der der Stil als jsonb in
 * der Datenbank landet. Eine Schnittstelle scheitert dort an der fehlenden Indexsignatur. */
export type CaptionStyle = {
  /* Welches eingebaute Preset die Grundlage ist. Leer heisst: das Format entscheidet. */
  preset?: string;
  font?: string;
  font_px?: number;
  bold?: boolean;
  all_caps?: boolean;
  /* Woerter je Einblendung, 1 bis 6. 1 ist der Karaoke-Stil der Kurzformate. */
  words_per_card?: number;
  max_lines?: number;
  base_color?: string;
  highlight_color?: string;
  /* Farbe der Kontur und des Kastens dahinter. Beides war lange fest schwarz. */
  outline_color?: string;
  box_color?: string;
  highlight_words?: boolean;
  outline_px?: number;
  box?: boolean;
  /* Abstand der Textunterkante zur Unterkante der sicheren Flaeche. Groesser heisst hoeher im Bild. */
  bottom_margin_px?: number;
};

export interface CaptionFont {
  id: string;
  beschreibung: string;
  datei: string;
  grossbuchstaben_empfohlen: boolean;
}

export const FONTS: CaptionFont[] = (fontsJson.schriften as CaptionFont[]).map((f) => ({
  id: f.id,
  beschreibung: f.beschreibung,
  datei: f.datei,
  grossbuchstaben_empfohlen: Boolean(f.grossbuchstaben_empfohlen),
}));
export const FONT_RUECKLAUF = String(fontsJson.ruecklauf);

export const GRENZEN = {
  font_px: [28, 180],
  words_per_card: [1, 6],
  max_lines: [1, 4],
  outline_px: [0, 20],
  bottom_margin_px: [0, 900],
} as const satisfies Record<string, readonly [number, number]>;

/* Die eingebauten Presets als Ausgangspunkt. Die Beschreibung sagt, wofuer der Stil gedacht ist,
 * nicht wie er heisst: „linkedin_static" hilft niemandem bei der Wahl. */
export const BASIS_PRESETS = [
  { id: "", name: "Automatisch", hinweis: "Hochkant wortweise, quer ruhig" },
  { id: "tiktok_words", name: "Ein Wort, groß", hinweis: "Der übliche Kurzformat-Stil" },
  { id: "tiktok_bold", name: "Mehrere Wörter, fett", hinweis: "Zwei Zeilen, kräftig" },
  { id: "reels_clean", name: "Ruhig", hinweis: "Kleiner, dünnere Kontur" },
  { id: "linkedin_static", name: "Sachlich mit Kasten", hinweis: "Ohne Hervorhebung" },
] as const;

/* Vier Looks statt einer Liste von Schriften, Staerken und Konturen.
 *
 * „Welche Schrift, wie fett, wie dick die Kontur" sind drei Fragen, die niemand beantworten will,
 * der einen Clip fertig machen moechte. „Wie soll es aussehen" ist eine. Jeder Look ist ein Buendel
 * von Einstellungen; wer danach etwas Einzelnes aendern will, findet alles unter „Mehr einstellen".
 *
 * Die Looks sind an dem abgelesen, was in Kurzformaten tatsaechlich vorkommt: die neutrale
 * Grotesk, die schwere Versalien-Schrift, der ruhige Kasten und der laute Karaoke-Stil. */
export interface Look {
  id: string;
  name: string;
  hinweis: string;
  stil: CaptionStyle;
}

export const LOOKS: Look[] = [
  {
    id: "klar",
    name: "Klar",
    hinweis: "Neutral, gut lesbar",
    stil: { preset: "tiktok_words", font: "Inter", bold: true, all_caps: false, outline_px: 5, box: false, base_color: "#ffffff", highlight_color: "#ffd700" },
  },
  {
    id: "laut",
    name: "Laut",
    hinweis: "Schwer, Großbuchstaben",
    stil: { preset: "tiktok_words", font: "Anton", bold: true, all_caps: true, outline_px: 9, box: false, base_color: "#ffffff", highlight_color: "#00e5a0" },
  },
  {
    id: "ruhig",
    name: "Ruhig",
    hinweis: "Mit Kasten, ohne Blinken",
    stil: { preset: "linkedin_static", font: "Inter", bold: false, all_caps: false, outline_px: 0, box: true, highlight_words: false, base_color: "#ffffff", words_per_card: 4, max_lines: 2 },
  },
  {
    id: "signal",
    name: "Signal",
    hinweis: "Kräftig, farbige Hervorhebung",
    stil: { preset: "tiktok_words", font: "Archivo Black", bold: true, all_caps: true, outline_px: 7, box: false, base_color: "#ffffff", highlight_color: "#ff3b6b" },
  },
];

/* Fuenf Farben fuer die Hervorhebung. Eine Reihe Punkte statt eines Farbwaehlers: die Wahl ist in
 * einer Sekunde getroffen, und es kommt nichts heraus, was auf dunklem Bild untergeht. Der freie
 * Waehler bleibt unter „Mehr einstellen". */
export const HIGHLIGHT_FARBEN = ["#ffd700", "#00e5a0", "#ff3b6b", "#5b8cff", "#ffffff"] as const;

/* Welcher Look sitzt gerade? Verglichen wird ueber die Felder, die den Look ausmachen; alles
 * andere (Groesse, Wortzahl, Hoehe) darf abweichen, ohne dass die Auswahl verspringt. */
const LOOK_FELDER = ["font", "all_caps", "box", "outline_px"] as const;

export function aktiverLook(stil: CaptionStyle): string | null {
  const s = mitVorgabe(stil);
  const treffer = LOOKS.find((l) => {
    const v = mitVorgabe(l.stil);
    return LOOK_FELDER.every((f) => v[f] === s[f]);
  });
  return treffer?.id ?? null;
}

/* ``#RRGGBB`` in die ASS-Schreibweise ``&H00BBGGRR``. Spiegel von captions_de.ass_farbe.
 *
 * ASS dreht die Reihenfolge um und stellt die Deckkraft voran. Gebraucht wird das hier, um den
 * eingestellten Stil mit dem zu vergleichen, was im Renderplan steht: dort stehen ASS-Werte. */
export function assFarbe(wert: string): string | null {
  let w = (wert || "").trim();
  if (!w) return null;
  if (w.toUpperCase().startsWith("&H")) return w.toUpperCase();
  if (w.startsWith("#")) w = w.slice(1);
  if (!/^[0-9a-fA-F]{6}$/.test(w)) return null;
  return `&H00${w.slice(4, 6)}${w.slice(2, 4)}${w.slice(0, 2)}`.toUpperCase();
}

/* ``&H00BBGGRR`` zurueck nach ``#rrggbb``. Gegenstueck zu assFarbe. */
export function hexFarbe(wert: unknown): string | null {
  const w = String(wert ?? "").trim().toUpperCase();
  const m = /^&H[0-9A-F]{2}([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})$/.exec(w);
  if (!m) return null;
  const [, bb, gg, rr] = m;
  return `#${rr}${gg}${bb}`.toLowerCase();
}

/* Der Stil, der im gebauten Video wirklich steckt, aus dem Renderplan zurueckgelesen.
 *
 * Gebraucht fuer Clips ohne eigenen Stil. Die zeigten bisher die Vorgaben der Oberflaeche, gebaut
 * wurde aber mit dem Plattform-Preset - andere Schriftgroesse, andere Konturstaerke. Die Folge:
 * ein Clip, an dem niemand etwas geaendert hatte, meldete sich als veraltet, und der Regler stand
 * auf einem Wert, der im Bild nicht vorkam. */
export function stilAusPlan(geplant: Record<string, unknown> | null | undefined): CaptionStyle {
  if (!geplant) return {};
  const aus: CaptionStyle = {};
  const zahl = (k: string) => (typeof geplant[k] === "number" ? (geplant[k] as number) : null);
  const bool = (k: string) => (typeof geplant[k] === "boolean" ? (geplant[k] as boolean) : null);
  if (typeof geplant.font === "string" && geplant.font) aus.font = geplant.font;
  for (const k of ["font_px", "words_per_card", "max_lines", "outline_px"] as const) {
    const v = zahl(k);
    if (v != null) aus[k] = v;
  }
  for (const [hier, dort] of [["bold", "bold"], ["all_caps", "all_caps"], ["box", "box"], ["highlight_words", "highlight"]] as const) {
    const v = bool(dort);
    if (v != null) aus[hier] = v;
  }
  for (const [hier, dort] of [["base_color", "base_color"], ["highlight_color", "highlight_color"], ["outline_color", "outline_color"]] as const) {
    const v = hexFarbe(geplant[dort]);
    if (v) aus[hier] = v;
  }
  /* Der Abstand nach unten steckt im Plan als Grundlinie: Bildhoehe minus Grundlinie. */
  const grundlinie = zahl("baseline_y");
  const safe = (geplant.safe_zone as { bottom?: number } | undefined)?.bottom;
  if (grundlinie != null && typeof safe === "number") aus.bottom_margin_px = Math.round(1920 - safe - grundlinie);
  return stilPruefen(aus);
}

/* Zeigt das gerenderte Video noch dieselben Untertitel, die jetzt eingestellt sind?
 *
 * Im fertigen Clip sind die Untertitel eingebrannt. Wer den Stil danach aendert, sieht im Bild
 * weiter die alten - ohne diesen Vergleich wirkt es, als sei die Aenderung folgenlos geblieben.
 *
 * Verglichen wird gegen den ``captions``-Block des Renderplans, der seit dem Anschluss der
 * Untertitel den ANGEWENDETEN Stil traegt und nicht mehr die Preset-Vorgaben.
 *
 * Felder, die im Plan gar nicht vorkommen, werden uebersprungen. Ein Plan aus der Zeit vor einer
 * Einstellung kann ueber sie nichts aussagen, und ein Vergleich gegen "fehlt" haette jeden aelteren
 * Clip fuer immer als veraltet gemeldet - eine Warnung, die immer dasteht, liest niemand mehr. */
export function passtZumRender(stil: CaptionStyle, geplant: Record<string, unknown> | null | undefined): boolean {
  if (!geplant) return true; // noch nichts gerendert: es gibt nichts, was veraltet sein koennte
  const s = mitVorgabe(stil);
  const zahlen: [keyof typeof s, string][] = [
    ["font_px", "font_px"],
    ["words_per_card", "words_per_card"],
    ["max_lines", "max_lines"],
    ["outline_px", "outline_px"],
  ];
  for (const [hier, dort] of zahlen) {
    if (!(dort in geplant)) continue;
    if (Number(geplant[dort] ?? NaN) !== Number(s[hier])) return false;
  }
  for (const [hier, dort] of [["bold", "bold"], ["all_caps", "all_caps"], ["box", "box"], ["highlight_words", "highlight"]] as const) {
    if (!(dort in geplant)) continue;
    if (Boolean(geplant[dort]) !== Boolean(s[hier])) return false;
  }
  if ("font" in geplant && String(geplant.font ?? "") !== s.font) return false;
  for (const [hier, dort] of [["base_color", "base_color"], ["highlight_color", "highlight_color"], ["outline_color", "outline_color"]] as const) {
    if (!(dort in geplant)) continue;
    if (String(geplant[dort] ?? "").toUpperCase() !== assFarbe(s[hier])) return false;
  }
  /* Die Hoehe steckt im Plan als Grundlinie, also Safe-Zone-Unterkante minus Abstand. */
  const safe = (geplant.safe_zone as { bottom?: number } | undefined)?.bottom;
  const grundlinie = Number(geplant.baseline_y ?? NaN);
  if (Number.isFinite(grundlinie) && typeof safe === "number") {
    const gemeint = 1920 - safe - s.bottom_margin_px;
    if (Math.abs(grundlinie - gemeint) > 2) return false;
  }
  return true;
}

/* Mittlere Zeichenbreite in em, gemessen an Inter Bold. Spiegel von captions_de.AVG_CHAR_EM. */
export const AVG_CHAR_EM = 0.56;
export const SAFE_BREITE_STANDARD = 1080 - 180;

/* Zeichen, die bei dieser Schriftgroesse in eine Zeile passen. Spiegel von captions_de.max_chars. */
export function maxZeichen(fontPx: number, safeBreite = SAFE_BREITE_STANDARD): number {
  return Math.max(8, Math.floor(safeBreite / (Math.max(fontPx, 1) * AVG_CHAR_EM)));
}

function inGrenzen(wert: unknown, [unten, oben]: readonly [number, number]): number | null {
  return zahlImRahmen(wert, unten, oben);
}

const HEX = /^#[0-9a-fA-F]{6}$/;

/* Einen Stil aus fremder Hand auf das Erlaubte zurechtschneiden.
 *
 * Wird an der Schnittstelle benutzt, damit in der Datenbank nur landet, was der Renderer auch
 * annimmt. Unbekannte Felder fliegen raus, statt als Altlast mitzureisen. */
export function stilPruefen(roh: unknown): CaptionStyle {
  if (!roh || typeof roh !== "object" || Array.isArray(roh)) return {};
  const q = roh as Record<string, unknown>;
  const aus: CaptionStyle = {};

  if (typeof q.preset === "string" && BASIS_PRESETS.some((p) => p.id === q.preset && p.id)) aus.preset = q.preset;
  if (typeof q.font === "string" && FONTS.some((f) => f.id === q.font)) aus.font = q.font;

  for (const feld of ["font_px", "words_per_card", "max_lines", "outline_px", "bottom_margin_px"] as const) {
    if (!(feld in q)) continue;
    const z = inGrenzen(q[feld], GRENZEN[feld]);
    if (z != null) aus[feld] = z;
  }
  for (const feld of ["bold", "all_caps", "highlight_words", "box"] as const) {
    if (typeof q[feld] === "boolean") aus[feld] = q[feld] as boolean;
  }
  for (const feld of ["base_color", "highlight_color", "outline_color", "box_color"] as const) {
    const w = q[feld];
    if (typeof w === "string" && HEX.test(w)) aus[feld] = w.toLowerCase();
  }
  /* Ein Wort kann keine zweite Zeile fuellen. Gleiche Regel wie im Worker. */
  if (aus.words_per_card === 1) aus.max_lines = 1;
  return aus;
}

/* Was die Vorschau zeigt, wenn am Clip nichts eingestellt ist. Entspricht dem Preset
 * „tiktok_words", das hochkant ohnehin greift. */
export const VORGABE: Required<Omit<CaptionStyle, "preset">> = {
  font: "Inter",
  font_px: 104,
  bold: true,
  all_caps: false,
  words_per_card: 1,
  max_lines: 1,
  base_color: "#ffffff",
  highlight_color: "#ffd700",
  outline_color: "#000000",
  box_color: "#000000",
  highlight_words: true,
  outline_px: 5,
  box: false,
  bottom_margin_px: 260,
};

export function mitVorgabe(stil: CaptionStyle | null | undefined): Required<Omit<CaptionStyle, "preset">> & { preset?: string } {
  return { ...VORGABE, ...(stil ?? {}) };
}
