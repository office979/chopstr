import type { CandidateSegment, CaptionCard } from "@/lib/repo/types";
import { NEGATIONS } from "@/lib/transcript/fillers";
import { MAX_CPS } from "@/lib/clips/presets";

/* Caption-Karten für die stumme Vorschau und den Demo-Render: Spiegel von captions_de.build_cards
 * und wrap_lines (Umbruch an Satzzeichen, Konjunktionen, Pausen; eine Negation steht nie allein in
 * einer neuen Zeile). Zeiten liegen auf der Ausgabe-Timeline (Sekunde 0 = Clip-Start). */

const BREAK_WORDS = new Set(["und", "aber", "weil", "dass", "denn", "oder", "wenn", "sondern", "also", "obwohl", "damit"]);

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

/* Gruppiert Wörter zu Karten: Bruch an Satzzeichen, Konjunktionen, Pausen ab 0,4 s und vor langen Komposita */
export function groupCards(words: TimedWord[], limit: number, maxLines = 2): TimedWord[][] {
  const cap = limit * maxLines;
  const cards: TimedWord[][] = [];
  let cur: TimedWord[] = [];
  let curLen = 0;
  words.forEach((w, i) => {
    const t = w.text;
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
    cur.push(w);
    curLen += t.length + 1;
    const nxt = words[i + 1];
    if (isLong || /[.!?,]$/.test(t) || (nxt && nxt.start - w.end > 0.4)) {
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
      lines: wrapLines(g.map((w) => w.text), limit, maxLines),
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
