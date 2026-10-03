/* Claim-Check: Spiegel von workers/chopstr_worker/pipeline/fidelity.hook_claim_check.
 * Ein Hook darf keine Zahlen oder Zuspitzungen enthalten, die im Clip nicht vorkommen (UWG: Irreführung). */

export const SUPERLATIVES = ["beste", "einzige", "garantiert", "immer", "100 %", "100%", "sofort", "heilt", "nie wieder", "jeder"];

export function hookClaimCheck(hookText: string, clipText: string): string[] {
  const issues: string[] = [];
  for (const num of hookText.match(/\d[\d.,]*/g) ?? []) {
    if (!clipText.includes(num)) issues.push(`Zahl '${num}' steht nicht im Clip`);
  }
  const lowHook = hookText.toLowerCase();
  const lowClip = clipText.toLowerCase();
  for (const sup of SUPERLATIVES) {
    if (lowHook.includes(sup) && !lowClip.includes(sup)) issues.push(`Zuspitzung '${sup}' nicht durch Clip gedeckt`);
  }
  return issues;
}

/* Claim-Check v2: Port von workers/chopstr_worker/pipeline/fidelity.hook_claim_check_v2 (AP6a).
 * Zahlen als Menge von (Wert, Einheit) statt Teilstring („40 Euro“ ist nicht „40.000 Euro“, „4“ steckt
 * nicht in „2024“), Zahlwörter („vier“, „einundzwanzig“, „vierzigtausend“), Uhrzeiten, Geltungsbereich
 * (Verallgemeinerer im Hook gegen Einschränker im Clip) und unsicher erkannte Zahlen. Beide Seiten prüfen
 * gegen packages/editorial/parity/claim_check_v1.json.
 *
 * Manuell bearbeitete Hooks prüft das Web weiter mit hookClaimCheck (v1), siehe lib/copy/hooks.ts. */

const UNIT_NUMBER_WORDS: Record<string, number> = { eins: 1, zwei: 2, drei: 3, vier: 4, fünf: 5, sechs: 6, sieben: 7, acht: 8, neun: 9 };
const UNIT_PREFIXES: Record<string, number> = { ein: 1, zwei: 2, drei: 3, vier: 4, fünf: 5, sechs: 6, sieben: 7, acht: 8, neun: 9 };
const TEEN_NUMBER_WORDS: Record<string, number> = {
  zehn: 10, elf: 11, zwölf: 12, dreizehn: 13, vierzehn: 14, fünfzehn: 15, sechzehn: 16, siebzehn: 17, achtzehn: 18, neunzehn: 19,
};
const TEN_NUMBER_WORDS: Record<string, number> = {
  zwanzig: 20, dreißig: 30, dreissig: 30, vierzig: 40, fünfzig: 50, sechzig: 60, siebzig: 70, achtzig: 80, neunzig: 90,
};
const AMBIGUOUS_NUMBER_WORDS = new Set(["null", "eins", "acht", "elf"]);
const ARTICLE_ONE = new Set(["ein", "eine", "einen", "einem", "einer"]);
const NUMBER_WORD_STEMS = ["ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf", "zwanzig", "hundert", "tausend"];
const NUMBER_WORD_PARTS = ["zig", "ßig", "ssig", "hundert", "tausend", "zehn"];
const MULTIPLIERS: Record<string, number> = {
  hundert: 1e2, tausend: 1e3, tsd: 1e3, "tsd.": 1e3, mio: 1e6, "mio.": 1e6, million: 1e6, millionen: 1e6,
  mrd: 1e9, "mrd.": 1e9, milliarde: 1e9, milliarden: 1e9,
};
const UNIT_WORDS: Record<string, string> = { "%": "%", prozent: "%", euro: "EUR", eur: "EUR", "€": "EUR", franken: "CHF", chf: "CHF" };
const UNIT_LABELS: Record<string, string> = { "%": "Prozent", EUR: "Euro", CHF: "Franken", time: "Uhr" };
export const GENERALIZERS = [
  "jedes unternehmen", "jede firma", "jeder betrieb", "für jeden", "für jede", "für alle", "alle", "immer",
  "grundsätzlich", "überall", "jeder", "jede", "jedes",
];
export const RESTRICTORS = [
  "bei uns", "bei mir", "bei einem kunden", "bei einer kundin", "in unserem fall", "in meinem fall",
  "in unserem betrieb", "für uns", "damals",
];

export interface NumberMention {
  raw: string;
  value: number;
  unit: string | null;
}

const W = "[\\p{L}\\p{N}_]";
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const MENTION = new RegExp(
  `(?<![\\p{L}\\p{N}_.,:])(?<time>\\d{1,2}[:.]\\d{2})(?=\\s*Uhr(?!${W}))` +
    `|(?<![\\p{L}\\p{N}_.,])(?<num>\\d{1,3}(?:[.'\\u202f\\u00a0 ]\\d{3})+(?:,\\d+)?(?!\\d)|\\d+(?:[.,]\\d+)?)` +
    `|(?<!${W})(?<word>\\p{L}+)(?!${W})`,
  "gu",
);
const NEXT_TOKEN = /\s*(%|€|[^\s,;:!?()]+)/uy;
const THOUSANDS = /^\d{1,3}(?:\.\d{3})+(?:,\d+)?$/;
const CLIP_SENTENCE = /(?<=[.!?])\s+/u;

const round6 = (x: number) => Math.round(x * 1e6) / 1e6;

function numberValue(raw: string): number {
  let s = raw.replace(/[  ' ]/g, "");
  if (THOUSANDS.test(s)) s = s.replace(/\./g, "");
  return round6(parseFloat(s.replace(",", ".")));
}

function wordKey(token: string): string {
  return token.toLowerCase().replace(/^[.,;:!?"'»«“”‘’()]+|[.,;:!?"'»«“”‘’()]+$/g, "");
}

function belowHundred(s: string): number | null {
  if (s in TEEN_NUMBER_WORDS) return TEEN_NUMBER_WORDS[s] ?? null;
  if (s in TEN_NUMBER_WORDS) return TEN_NUMBER_WORDS[s] ?? null;
  if (s in UNIT_NUMBER_WORDS) return UNIT_NUMBER_WORDS[s] ?? null;
  for (const [ten, value] of Object.entries(TEN_NUMBER_WORDS)) {
    const suffix = `und${ten}`;
    if (s.endsWith(suffix)) {
      const head = s.slice(0, -suffix.length);
      if (head in UNIT_PREFIXES) return (UNIT_PREFIXES[head] ?? 0) + value;
    }
  }
  return null;
}

function partition(s: string, sep: string): [string, string] {
  const i = s.indexOf(sep);
  return [s.slice(0, i), s.slice(i + sep.length)];
}

function belowThousand(s: string): number | null {
  if (!s.includes("hundert")) return belowHundred(s);
  const [head, tailRaw] = partition(s, "hundert");
  const hundreds = head === "" ? 1 : (UNIT_PREFIXES[head] ?? null);
  if (hundreds === null) return null;
  const tail = tailRaw.startsWith("und") ? tailRaw.slice(3) : tailRaw;
  const rest = tail === "" ? 0 : belowHundred(tail);
  return rest === null ? null : hundreds * 100 + rest;
}

export function parseNumberWord(word: string): number | null {
  const s = word.toLowerCase();
  if (s === "null") return 0;
  if (!s.includes("tausend")) return belowThousand(s);
  const [head, tailRaw] = partition(s, "tausend");
  const thousands = head === "" ? 1 : (UNIT_PREFIXES[head] || belowThousand(head));
  if (thousands === null || thousands === undefined) return null;
  const tail = tailRaw.startsWith("und") ? tailRaw.slice(3) : tailRaw;
  const rest = tail === "" ? 0 : belowThousand(tail);
  return rest === null ? null : thousands * 1000 + rest;
}

function unitOf(token: string): string | null {
  const key = token === "%" || token === "€" ? token : wordKey(token);
  if (key in UNIT_WORDS) return UNIT_WORDS[key] ?? null;
  const first = token.slice(0, 1);
  if (first !== first.toLowerCase() && first === first.toUpperCase() && /^\p{L}+$/u.test(wordKey(token))) return `noun:${wordKey(token)}`;
  return null;
}

function nextToken(text: string, pos: number): { token: string; end: number } | null {
  NEXT_TOKEN.lastIndex = pos;
  const m = NEXT_TOKEN.exec(text);
  return m ? { token: m[1] ?? "", end: NEXT_TOKEN.lastIndex } : null;
}

export function numberMentions(text: string): NumberMention[] {
  const out: NumberMention[] = [];
  let consumed = 0;
  for (const m of text.matchAll(MENTION)) {
    const start = m.index ?? 0;
    if (start < consumed) continue;
    let pos = start + m[0].length;
    const time = m.groups?.time;
    if (time) {
      const [h, mi] = time.split(/[:.]/);
      out.push({ raw: time, value: Number(h) * 60 + Number(mi), unit: "time" });
      consumed = pos;
      continue;
    }
    let nxt = nextToken(text, pos);
    const nxtKey = nxt ? wordKey(nxt.token) : "";
    const num = m.groups?.num;
    let raw: string;
    let value: number;
    if (num) {
      raw = num.trim();
      value = numberValue(raw);
    } else {
      raw = m.groups?.word ?? "";
      const low = raw.toLowerCase();
      let parsed = parseNumberWord(low);
      if (parsed === null) {
        if (!(ARTICLE_ONE.has(low) && nxtKey in MULTIPLIERS)) continue;
        parsed = 1;
      } else if (AMBIGUOUS_NUMBER_WORDS.has(low) && !(nxt && (nxtKey in MULTIPLIERS || unitOf(nxt.token)))) {
        continue;
      }
      value = parsed;
    }
    if (nxt && nxtKey in MULTIPLIERS) {
      value = round6(value * (MULTIPLIERS[nxtKey] ?? 1));
      pos = nxt.end;
      nxt = nextToken(text, pos);
    }
    let unit = nxt ? unitOf(nxt.token) : null;
    if (unit === null) {
      const before = text.slice(0, start).trimEnd();
      if (before.endsWith("€")) unit = "EUR";
      else if (before.toLowerCase().endsWith("chf")) unit = "CHF";
    }
    out.push({ raw, value, unit });
    consumed = pos;
  }
  return out;
}

export function unrecognizedNumberWords(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(/(?<![\p{L}\p{N}_])\p{L}+(?![\p{L}\p{N}_])/gu)) {
    const low = m[0].toLowerCase();
    if (parseNumberWord(low) !== null || low.startsWith("einzig")) continue;
    if (NUMBER_WORD_STEMS.some((p) => low.startsWith(p)) && NUMBER_WORD_PARTS.some((p) => low.includes(p))) out.push(m[0]);
  }
  return out;
}

function sameStem(a: string, b: string): boolean {
  let common = 0;
  while (common < a.length && common < b.length && a[common] === b[common]) common++;
  return a === b || (common >= 4 && common >= Math.min(a.length, b.length) - 2);
}

function covered(h: NumberMention, clip: NumberMention[], lowWords: Set<string>): boolean {
  const same = clip.filter((c) => c.value === h.value);
  if (h.unit === null) return same.length > 0;
  if (!h.unit.startsWith("noun:")) return same.some((c) => c.unit === h.unit);
  const noun = h.unit.slice("noun:".length);
  return same.some(
    (c) =>
      (c.unit !== null && c.unit.startsWith("noun:") && sameStem(c.unit.slice("noun:".length), noun)) ||
      (c.unit === null && [...lowWords].some((w) => sameStem(w, noun))),
  );
}

function phraseHits(phrases: string[], low: string): string[] {
  return phrases.filter((p) => new RegExp(`(?<!${W})${escapeRe(p)}(?!${W})`, "u").test(low));
}

/* Python: str.capitalize() senkt den Rest; .title() wäre falsch. */
function unitLabel(unit: string | null): string {
  if (unit === null) return "";
  const label = UNIT_LABELS[unit];
  if (label) return ` (${label})`;
  const k = unit.replace(/^noun:/, "");
  return ` (${k.slice(0, 1).toUpperCase()}${k.slice(1).toLowerCase()})`;
}

function scopeIssues(lowHook: string, clipText: string): [string, string][] {
  const restrictors = phraseHits(RESTRICTORS, clipText.toLowerCase());
  if (!restrictors.length || phraseHits(RESTRICTORS, lowHook).length) return [];
  const sentences = clipText
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .split(CLIP_SENTENCE)
    .filter((x) => x.trim())
    .map((x) => x.toLowerCase());
  const hits = phraseHits(GENERALIZERS, lowHook);
  const out: [string, string][] = [];
  for (const gen of hits.filter((g) => !hits.some((o) => o !== g && o.includes(g)))) {
    if (sentences.some((x) => phraseHits([gen], x).length && !phraseHits(RESTRICTORS, x).length)) continue;
    out.push([gen, restrictors[0] ?? ""]);
  }
  return out;
}

export function hookClaimCheckV2(hookText: string, clipText: string, uncertainTokens: string[] = []): string[] {
  const issues: string[] = [];
  const clipMentions = numberMentions(clipText);
  const lowWords = new Set(clipText.split(/\s+/).filter(Boolean).map(wordKey));
  const uncertain = new Set(uncertainTokens.flatMap((t) => numberMentions(String(t)).map((m) => m.value)));
  for (const h of numberMentions(hookText)) {
    if (uncertain.has(h.value)) {
      issues.push(`Zahl '${h.raw}' ist im Clip unsicher erkannt und darf nicht in den Hook (am Audio prüfen)`);
    } else if (!covered(h, clipMentions, lowWords)) {
      issues.push(`Zahl '${h.raw}'${unitLabel(h.unit)} steht so nicht im Clip`);
    }
  }
  for (const word of unrecognizedNumberWords(hookText)) issues.push(`Zahlwort '${word}' nicht erkannt, am Clip prüfen`);
  const lowHook = hookText.toLowerCase();
  const lowClip = clipText.toLowerCase();
  const scope = scopeIssues(lowHook, clipText);
  const scoped = new Set(scope.map(([g]) => g));
  for (const sup of SUPERLATIVES) {
    if (!scoped.has(sup) && phraseHits([sup], lowHook).length && !phraseHits([sup], lowClip).length) {
      issues.push(`Zuspitzung '${sup}' nicht durch Clip gedeckt`);
    }
  }
  for (const [gen, restrictor] of scope) issues.push(`Geltungsbereich: '${gen}' im Hook, der Clip schränkt ein ('${restrictor}')`);
  return issues;
}
