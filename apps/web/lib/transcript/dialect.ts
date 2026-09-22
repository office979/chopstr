import type { TranscriptStats, TranscriptWord } from "@/lib/repo/types";
import type { DialectStats, TranscriptStatsExt, TranscriptWordExt } from "@/lib/repo/types-api";

/* Schweizerdeutsch-Beta (PHASE5.md, 5c): Dialekthinweis aus transcript_versions.stats.dialect und Umschalter
 * Original / Standard über words[].text_norm (nur gesetzt, wenn das CH-Modell oder das Lexikon eine sichere
 * Entsprechung liefert). Ohne Server-Abhängigkeiten, im Client nutzbar. */

export type TextMode = "original" | "standard";

export function dialectOf(stats: TranscriptStats | null | undefined): DialectStats | null {
  const d = (stats as TranscriptStatsExt | undefined)?.dialect;
  if (!d || typeof d !== "object" || typeof d.variant !== "string") return null;
  return { variant: d.variant, confidence: Number(d.confidence ?? 0), markers: Array.isArray(d.markers) ? d.markers : [] };
}

export function textNorm(word: TranscriptWord): string | null {
  const n = (word as TranscriptWordExt).text_norm;
  return typeof n === "string" && n.trim() ? n : null;
}

export function hasNormalizedWords(words: TranscriptWord[]): boolean {
  return words.some((w) => textNorm(w) !== null);
}

export function countNormalizedWords(words: TranscriptWord[]): number {
  return words.reduce((n, w) => n + (textNorm(w) ? 1 : 0), 0);
}

/* Anzeige-Text je Modus: Standard nutzt text_norm, sonst das Original */
export function displayText(word: TranscriptWord, mode: TextMode): string {
  if (mode === "standard") return textNorm(word) ?? word.text;
  return word.text;
}

export interface DialectHint {
  tone: "attention" | "neutral";
  text: string;
  detail: string | null;
}

/* Hinweis für den Editor: CH ohne CH-Modell → orange (Mensch prüft), sonst grau */
export function dialectHint(dialect: DialectStats | null, asrVariant: string | null | undefined): DialectHint | null {
  if (!dialect || dialect.variant === "de") return null;
  const pct = Math.round(dialect.confidence * 100);
  const markers = dialect.markers.slice(0, 5).join(", ");
  const detail = markers ? `Marker: ${markers}${pct ? ` (Sicherheit ${pct} %)` : ""}` : pct ? `Sicherheit ${pct} %` : null;
  if (dialect.variant === "de-CH") {
    if (asrVariant !== "de-CH") {
      return { tone: "attention", text: "Schweizerdeutsch erkannt, CH-Modell empfohlen, Beta", detail };
    }
    return { tone: "neutral", text: "Schweizerdeutsch (CH-Modell, Beta)", detail };
  }
  return { tone: "neutral", text: "Österreichisches Deutsch erkannt", detail };
}
