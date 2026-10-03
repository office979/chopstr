/* Untertitel-Karten: Gleichstand mit dem Worker (AP10a).
 *
 * Vorschau und Demo-Render bauen ihre Karten selbst, der Worker brennt sie ein. Laufen beide
 * auseinander, zeigt die Vorschau „40" und „Prozent" auf zwei Karten, das Video aber eine. Deshalb
 * lesen pytest (workers/tests/test_captions.py) und dieser Test dieselbe Datei mit gemeinsamen
 * Fällen: packages/editorial/parity/caption_cards_v1.json. */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildCaptionCards, groupCards, splitAtHyphens, type TimedWord, UNIT_WORDS, unitTokens } from "@/lib/clips/captions";

const ROOT = resolve(import.meta.dirname, "../../..");

interface Parity {
  unit_words: string[];
  unit_tokens: { text: string; limit: number | null; expected: string[][] }[];
  hyphen_words: { word: string; limit: number; expected: string[] }[];
  cards: { text: string; limit: number; max_lines: number; words: TimedWord[]; expected: string[][] }[];
}

const PARITY: Parity = JSON.parse(
  readFileSync(resolve(ROOT, "packages/editorial/parity/caption_cards_v1.json"), "utf8"),
);

function timed(text: string): TimedWord[] {
  return text.split(" ").map((t, i) => ({ text: t, start: i * 0.35, end: i * 0.35 + 0.3 }));
}

describe("Gleichstand mit captions_de", () => {
  it("kennt dieselben Einheiten wie captions_de.UNIT_WORDS", () => {
    expect([...UNIT_WORDS].sort()).toEqual([...PARITY.unit_words].sort());
  });

  it.each(PARITY.unit_tokens)("hält Zahl plus Einheit zusammen: $text ($limit)", ({ text, limit, expected }) => {
    expect(unitTokens(timed(text), limit ?? Infinity).map((tok) => tok.map((w) => w.text))).toEqual(expected);
  });

  it.each(PARITY.hyphen_words)("trennt $word bei $limit Zeichen nur am Bindestrich", ({ word, limit, expected }) => {
    expect(splitAtHyphens(word, limit)).toEqual(expected);
  });

  it.each(PARITY.cards)("baut dieselben Karten: $text", ({ words, limit, max_lines, expected }) => {
    expect(groupCards(words, limit, max_lines).map((card) => card.map((w) => w.text))).toEqual(expected);
  });
});

describe("Zahl plus Einheit und Bindestrich in der Vorschau", () => {
  it("setzt „40 Prozent“ nie auf zwei Karten", () => {
    const { cards } = buildCaptionCards(timed("Das sind 40 Prozent mehr."), 12, 1);
    expect(cards.map((c) => c.lines.join(" "))).toEqual(["Das sind", "40 Prozent", "mehr."]);
  });

  it("verteilt Zahl plus Einheit nie über zwei Zeilen", () => {
    const { cards } = buildCaptionCards(timed("Es kostet 40 Prozent"), 15, 2);
    expect(cards[0].lines).toEqual(["Es kostet", "40 Prozent"]);
  });

  it("bricht ein Bindestrichwort nur am Bindestrich um", () => {
    const { cards } = buildCaptionCards(timed("Kunden-Anfrage-Bearbeitung"), 16, 2);
    expect(cards[0].lines).toEqual(["Kunden-Anfrage-", "Bearbeitung"]);
  });

  it("lässt Wörter ohne Bindestrich ganz", () => {
    expect(splitAtHyphens("Kundenanfragenbearbeitung", 10)).toEqual(["Kundenanfragenbearbeitung"]);
    expect(splitAtHyphens("kurz", 10)).toEqual(["kurz"]);
  });
});
