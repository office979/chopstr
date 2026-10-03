import type { CandidateSegment, CaptionCard } from "@/lib/repo/types";
import { NEGATIONS } from "@/lib/transcript/fillers";
import { MAX_CPS } from "@/lib/clips/presets";

/* Caption-Karten für die stumme Vorschau und den Demo-Render: Spiegel von captions_de.build_cards
 * und wrap_lines (Umbruch an Satzzeichen, Konjunktionen, Pausen; eine Negation steht nie allein in
 * einer neuen Zeile). Zeiten liegen auf der Ausgabe-Timeline (Sekunde 0 = Clip-Start).
 *
 * AP10a, teilweise aus captions_de übernommen: Zahl plus Einheit („40 Prozent", „3,5 Mio. Euro",
 * „14.30 Uhr") ist ein Token, steht in einer Zeile und wird nie auf zwei Karten verteilt; ein
 * Bindestrichwort, das breiter als die Zeile ist, wird nur am vorhandenen Bindestrich getrennt.
 * Nicht übernommen: Morphem- und Silbentrennung eines Segments, das allein zu breit ist, der
 * Komma-Bruch P30 und die Ereigniszeiten (Brücke, Mindestdauer); die Vorschau gilt unabhängig von
 * der Policy-Fassung. Gemeinsame Fälle stehen in packages/editorial/parity/caption_cards_v1.json. */

const BREAK_WORDS = new Set(["und", "aber", "weil", "dass", "denn", "oder", "wenn", "sondern", "also", "obwohl", "damit"]);

/* Gleiche Liste wie captions_de.UNIT_WORDS (klein geschrieben). */
export const UNIT_WORDS: ReadonlySet<string> = new Set([
  "%", "prozent", "prozentpunkte", "promille",
  "€", "euro", "eur", "cent", "$", "dollar", "usd", "chf", "franken", "rappen", "£", "pfund",
  "tsd.", "tausend", "mio.", "mio", "million", "millionen", "mrd.", "mrd", "milliarde", "milliarden",
  "uhr", "sekunde", "sekunden", "minute", "minuten", "stunde", "stunden", "tag", "tage", "tagen",
  "woche", "wochen", "monat", "monate", "monaten", "jahr", "jahre", "jahren",
  "km", "m", "cm", "mm", "kg", "g", "kwh", "grad", "°c", "°", "km/h", "mal", "punkte",
]);
const NUMBER_RE = /^[+-]?\d+(?:[.,:]\d+)*$/; // 40, 3,5, 40.000, 14.30, 14:30
const MAX_UNITS_PER_NUMBER = 2;

export interface TimedWord {
  text: string;
  start: number;
  end: number;
}

function isNegationToken(token: string): boolean {
  return NEGATIONS.has(token.toLowerCase().replace(/^[.,!?;:]+|[.,!?;:]+$/g, ""));
}

export function wrapLines(tokens: string[], limit: number, maxLines = 2): string[] {
  const lines: string[][] = [];
  let cur: string[] = [];
  for (const tok of tokens) {
    if (cur.length && [...cur, tok].join(" ").length > limit) {
      lines.push(cur);
      cur = [tok];
    } else {
      cur.push(tok);
    }
  }
  if (cur.length) lines.push(cur);
  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i].length === 1 && isNegationToken(lines[i][0]) && lines[i - 1].length) {
      if (lines[i - 1].length > 1) {
        lines[i].unshift(lines[i - 1].pop() as string);
      } else {
        lines[i - 1].push(...lines[i]);
        lines[i] = [];
      }
    }
  }
  const out = lines.filter((l) => l.length).map((l) => l.join(" "));
  if (out.length > maxLines) {
    return [...out.slice(0, maxLines - 1), out.slice(maxLines - 1).join(" ")];
  }
  return out;
}

function isUnit(text: string): boolean {
  const key = text.toLowerCase().replace(/[,;:!?]+$/, "");
  return UNIT_WORDS.has(key) || UNIT_WORDS.has(key.replace(/\.+$/, ""));
}

/* Zahl plus bis zu zwei Einheiten bildet ein Token (wie captions_de._tokens). Eine Einheit mit
 * Satzzeichen, außer dem Punkt einer Abkürzung wie „Mio.", schließt das Token ab. Ist das Token
 * breiter als limit, bleibt Zahl plus erste Einheit oder die Zahl allein. */
export function unitTokens(words: TimedWord[], limit = Infinity): TimedWord[][] {
  const out: TimedWord[][] = [];
  let i = 0;
  while (i < words.length) {
    const tok = [words[i]];
    if (NUMBER_RE.test(words[i].text)) {
      while (tok.length <= MAX_UNITS_PER_NUMBER && i + tok.length < words.length) {
        if (tok.length > 1 && !UNIT_WORDS.has(tok[tok.length - 1].text.toLowerCase())) break;
        if (!isUnit(words[i + tok.length].text)) break;
        tok.push(words[i + tok.length]);
      }
      while (tok.length > 1 && tok.map((w) => w.text).join(" ").length > limit) tok.pop();
    }
    out.push(tok);
    i += tok.length;
  }
  return out;
}

/* Bindestrichwort, das breiter als die Zeile ist: nur am vorhandenen Bindestrich trennen (Netflix-Norm,
 * wie captions_de._hyphenate_v2). Ein Segment, das allein zu breit ist, und Wörter ohne Bindestrich
 * bleiben hier ganz; der Worker teilt sie weiter an Morphemgrenzen. */
export function splitAtHyphens(word: string, limit: number): string[] {
  if (word.length <= limit) return [word];
  const segments: string[] = [];
  let cur = "";
  for (let i = 0; i < word.length; i += 1) {
    const ch = word[i];
    cur += ch;
    if (ch === "-" && i > 0 && i < word.length - 1 && word[i + 1] !== "-" && cur.replace(/-/g, "")) {
      segments.push(cur);
      cur = "";
    }
  }
  if (cur) segments.push(cur);
  if (segments.length < 2) return [word];
  const lines: string[] = [];
  let line = "";
  for (const seg of segments) {
    if (line && line.length + seg.length > limit) {
      lines.push(line);
      line = seg;
    } else {
      line += seg;
    }
  }
  lines.push(line);
  return lines;
}

/* Gruppiert Wörter zu Karten: Bruch an Satzzeichen, Konjunktionen, Pausen ab 0,4 s und vor langen
 * Komposita. Zahl plus Einheit ist ein Token und landet immer in derselben Karte. */
export function groupCards(words: TimedWord[], limit: number, maxLines = 2): TimedWord[][] {
  const cap = limit * maxLines;
  const cards: TimedWord[][] = [];
  let cur: TimedWord[] = [];
  let curLen = 0;
  const tokens = unitTokens(words, limit);
  tokens.forEach((tok, i) => {
    const t = tok.map((w) => w.text).join(" ");
    const isLong = t.length > limit;
    if (isLong && cur.length && curLen > 8) {
      cards.push(cur);
      cur = [];
      curLen = 0;
    }
    const startsClause = BREAK_WORDS.has(t.toLowerCase().replace(/[,.]/g, ""));
    if (cur.length && !isLong && (curLen + t.length + 1 > cap || (startsClause && curLen > 8))) {
      cards.push(cur);
      cur = [];
      curLen = 0;
    }
    cur.push(...tok);
    curLen += t.length + 1;
    const nxt = tokens[i + 1]?.[0];
    if (isLong || /[.!?,]$/.test(t) || (nxt && nxt.start - tok[tok.length - 1].end > 0.4)) {
      cards.push(cur);
      cur = [];
      curLen = 0;
    }
  });
  if (cur.length) cards.push(cur);
  return cards;
}

/* Wörter der Komposition auf die Ausgabe-Timeline legen (Segmente hintereinander, Lücken entfallen) */
export function wordsOnOutputTimeline(words: TimedWord[], segments: CandidateSegment[]): TimedWord[] {
  const out: TimedWord[] = [];
  let offset = 0;
  for (const seg of segments) {
    for (const w of words) {
      if (w.start < seg.start - 0.05 || w.end > seg.end + 0.05) continue;
      out.push({
        text: w.text,
        start: Number((offset + Math.max(0, w.start - seg.start)).toFixed(2)),
        end: Number((offset + Math.min(seg.end - seg.start, w.end - seg.start)).toFixed(2)),
      });
    }
    offset += seg.end - seg.start;
  }
  return out;
}

/* Keyword einer Karte: längstes Wort ab 6 Zeichen (Gewichtswechsel bei linkedin_static, Highlight bei tiktok_bold) */
function keywordOf(words: TimedWord[]): string | undefined {
  const cleaned = words.map((w) => w.text.replace(/[.,!?;:]/g, "")).filter((t) => t.length >= 6);
  if (cleaned.length === 0) return undefined;
  return cleaned.reduce((a, b) => (b.length > a.length ? b : a));
}

/* Zeilen einer Karte: ein Token aus Zahl plus Einheit ist eine Umbrucheinheit (geschütztes
 * Leerzeichen für wrapLines), damit „40 Prozent" nie über zwei Zeilen verteilt wird. */
const TOKEN_JOINER = "\u00a0";

function cardLines(card: TimedWord[], limit: number, maxLines: number): string[] {
  const units = unitTokens(card, limit).flatMap((tok) =>
    tok.length > 1 ? [tok.map((w) => w.text).join(TOKEN_JOINER)] : splitAtHyphens(tok[0].text, limit),
  );
  return wrapLines(units, limit, maxLines).map((line) => line.split(TOKEN_JOINER).join(" "));
}

export interface BuiltCaptions {
  cards: CaptionCard[];
  cps_warnings: string[];
}

export function buildCaptionCards(words: TimedWord[], limit: number, maxLines = 2): BuiltCaptions {
  const groups = groupCards(words, limit, maxLines);
  const cards: CaptionCard[] = [];
  const warnings: string[] = [];
  for (const g of groups) {
    const text = g.map((w) => w.text).join(" ");
    const chars = g.reduce((acc, w) => acc + w.text.length, 0);
    const dur = Math.max(g[g.length - 1].end - g[0].start, 0.01);
    if (chars / dur > MAX_CPS) {
      warnings.push(`Zu schnell (${Math.round(chars / dur)} Z/s): '${text}'`);
    }
    cards.push({
      start: g[0].start,
      end: g[g.length - 1].end,
      lines: cardLines(g, limit, maxLines),
      keyword: keywordOf(g),
    });
  }
  return { cards, cps_warnings: warnings };
}

/* Ohne Wortzeiten (nur Text): Wörter gleichmäßig über die Clip-Dauer verteilen */
export function wordsFromText(text: string, durationS: number): TimedWord[] {
  const tokens = text
    .replace(/^SPEAKER_\d+:\s*/gm, "")
    .split(/\s+/)
    .filter(Boolean);
  if (tokens.length === 0) return [];
  const totalChars = tokens.reduce((acc, t) => acc + t.length + 1, 0);
  let t = 0;
  return tokens.map((tok) => {
    const dur = (durationS * (tok.length + 1)) / totalChars;
    const start = Number(t.toFixed(2));
    t += dur;
    return { text: tok, start, end: Number(t.toFixed(2)) };
  });
}

/* Karte, die zur Zeit t sichtbar ist */
export function cardAt(cards: CaptionCard[], t: number): CaptionCard | null {
  return cards.find((c) => t >= c.start && t < c.end) ?? null;
}
