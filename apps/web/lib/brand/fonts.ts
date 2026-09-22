import "server-only";

/* Familienname und Gewicht aus einer Font-Datei über fontkit; bei Fehlern Fallback auf den Dateinamen. */

export interface FontMeta {
  family: string;
  weight: number | null;
  /* true wenn die Werte aus der Datei kommen, false bei Fallback auf den Dateinamen */
  parsed: boolean;
}

const WEIGHT_WORDS: [RegExp, number][] = [
  [/thin|hairline/i, 100],
  [/extra ?light|ultra ?light/i, 200],
  [/light/i, 300],
  [/regular|normal|book/i, 400],
  [/medium/i, 500],
  [/semi ?bold|demi ?bold/i, 600],
  [/extra ?bold|ultra ?bold/i, 800],
  [/black|heavy/i, 900],
  [/bold/i, 700],
];

export function weightFromName(name: string): number | null {
  for (const [re, w] of WEIGHT_WORDS) {
    if (re.test(name)) return w;
  }
  return null;
}

function familyFromFilename(filename: string): string {
  const base = filename.replace(/\.[a-z0-9]+$/i, "");
  return base.replace(/[-_]?(thin|extra ?light|light|regular|medium|semi ?bold|bold|extra ?bold|black|italic|variable)+$/i, "").replace(/[-_]+/g, " ").trim() || base;
}

export async function readFontMeta(bytes: Uint8Array, filename: string): Promise<FontMeta> {
  try {
    const fontkit = await import("fontkit");
    const created = fontkit.create(Buffer.from(bytes));
    const font = "fonts" in created ? created.fonts[0] : created;
    const family = (font.familyName ?? "").trim();
    const os2 = (font as unknown as { "OS/2"?: { usWeightClass?: number } })["OS/2"];
    const weight = os2?.usWeightClass && os2.usWeightClass >= 100 && os2.usWeightClass <= 1000 ? os2.usWeightClass : weightFromName(font.subfamilyName ?? filename);
    if (family) return { family, weight: weight ?? null, parsed: true };
  } catch (error) {
    console.warn("[fonts] fontkit konnte die Datei nicht lesen:", error instanceof Error ? error.message : error);
  }
  return { family: familyFromFilename(filename), weight: weightFromName(filename), parsed: false };
}
