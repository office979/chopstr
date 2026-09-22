/* Farbwerkzeuge für das CI im Markenprofil: Hex-Prüfung und WCAG-Kontrast */

export function normalizeHex(input: string): string | null {
  const v = input.trim().replace(/^#/, "");
  if (/^[0-9a-f]{3}$/i.test(v)) {
    return `#${v
      .split("")
      .map((c) => c + c)
      .join("")
      .toLowerCase()}`;
  }
  if (/^[0-9a-f]{6}$/i.test(v)) return `#${v.toLowerCase()}`;
  return null;
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const n = normalizeHex(hex);
  if (!n) return 0;
  const r = parseInt(n.slice(1, 3), 16);
  const g = parseInt(n.slice(3, 5), 16);
  const b = parseInt(n.slice(5, 7), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

export interface ContrastVerdict {
  white: number;
  black: number;
  /* AA für normalen Text: 4,5 : 1 */
  aaOnWhite: boolean;
  aaOnBlack: boolean;
  /* beste Textfarbe auf dieser Fläche */
  textOn: "white" | "black";
}

export function contrastVerdict(hex: string): ContrastVerdict | null {
  const n = normalizeHex(hex);
  if (!n) return null;
  const white = contrastRatio(n, "#ffffff");
  const black = contrastRatio(n, "#000000");
  return {
    white,
    black,
    aaOnWhite: white >= 4.5,
    aaOnBlack: black >= 4.5,
    textOn: white >= black ? "white" : "black",
  };
}

export function formatRatio(r: number): string {
  return `${r.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} : 1`;
}
