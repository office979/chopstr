/* Satzende im Web gleich wie im Worker (AP2).
 *
 * Die Falldatei packages/editorial/parity/sentence_end_v1.json liest auch der Worker
 * (workers/tests/test_sentence_end_parity.py). Steht hier eine andere Art als dort, zerlegen Web und
 * Worker dasselbe Transkript verschieden, und die Satzindizes eines Kandidaten zeigen im Review auf
 * andere Sätze als bei der Analyse.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  bracketHeuristic,
  cutBoundaryKind,
  isSentenceEnd,
  resolveSentenceRule,
  sentenceEndKinds,
  sentenceRuleFromStats,
  sentenceEndKind,
  sentencesFromWords,
  type SentenceEndKind,
  type SentenceRule,
  type WordLike,
} from "@/lib/transcript/sentences";
import type { TranscriptWord } from "@/lib/repo/types";

const WURZEL = resolve(import.meta.dirname, "../../..");

interface ParityCase {
  id: string;
  note: string;
  words: WordLike[];
  expected: Record<SentenceRule | "cut_v2", SentenceEndKind[]>;
}

const datei = JSON.parse(readFileSync(resolve(WURZEL, "packages/editorial/parity/sentence_end_v1.json"), "utf8")) as {
  version: number;
  max_sentence_s: number;
  max_sentence_words: number;
  kinds: SentenceEndKind[];
  cases: ParityCase[];
};

function woerter(text: string, pauseNach: Record<number, number> = {}): WordLike[] {
  let t = 0;
  return text.split(" ").map((w, k) => {
    const wort = { text: w, start: t, end: t + 0.3, speaker: "SPEAKER_00" };
    t += 0.32 + (pauseNach[k] ?? 0);
    return wort;
  });
}

describe("Paritätsdatei sentence_end_v1", () => {
  it("hat Fälle und nur bekannte Arten", () => {
    expect(datei.version).toBe(1);
    expect(datei.cases.length).toBeGreaterThan(15);
    expect(datei.kinds).toEqual(["punct", "speaker_change", "pause_candidate", "length_cap", "end_of_text", "none"]);
  });

  for (const fall of datei.cases) {
    for (const rule of ["v1", "v2", "v1_fallback_no_punct"] as SentenceRule[]) {
      it(`${fall.id} unter ${rule}`, () => {
        const limits = { maxS: datei.max_sentence_s, maxWords: datei.max_sentence_words };
        const art = fall.words.map((_w, i) => sentenceEndKind(fall.words, i, rule, limits));
        expect(art).toEqual(fall.expected[rule]);
        expect(sentenceEndKinds(fall.words, rule, limits)).toEqual(fall.expected[rule]);
      });
    }
    it(`${fall.id} für Schnitte (cut_v2)`, () => {
      const art = fall.words.map((_w, i) => cutBoundaryKind(fall.words, i, "v2"));
      expect(art).toEqual(fall.expected.cut_v2);
    });
  }
});

describe("Regel v2", () => {
  it("„Das ist so.“ endet einen Satz, unter v1 nicht", () => {
    const w = woerter("Das ist so. Deshalb machen wir das.");
    expect(sentenceEndKind(w, 2, "v2")).toBe("punct");
    expect(sentenceEndKind(w, 2, "v1")).toBe("none");
  });

  it("eine Pause vor kleingeschriebenem Wort ist keine Grenze", () => {
    const w = woerter("Das bringt bei uns nicht viel.", { 3: 0.9 });
    expect(sentenceEndKind(w, 3, "v2")).toBe("none");
    expect(isSentenceEnd(w, 3)).toBe(true);
  });

  it("eine Pause mit offenem Hilfsverb ist keine Grenze", () => {
    const w = woerter("Wir haben dann stattdessen Newsletter gemacht.", { 3: 0.9 });
    expect(sentenceEndKind(w, 3, "v2")).toBe("none");
  });

  it("die Verbklammer-Heuristik erkennt „Wir haben das letzte Jahr | nicht gemacht.“", () => {
    const w = woerter("Wir haben das letzte Jahr nicht gemacht.");
    const r = bracketHeuristic(w.slice(0, 5), w.slice(5));
    expect(r.open).toBe(true);
    expect(r.signal).toBe("auxiliary_bracket");
  });

  it("Rückfall ohne sentence_idx bleibt standardmäßig v1 und kann v2", () => {
    const w = woerter("Das bringt bei uns nicht viel.", { 3: 0.9 }).map(
      (x) => ({ ...x, prob: 1, filler: null, negation: false }) as unknown as TranscriptWord,
    );
    expect(sentencesFromWords(w).length).toBe(2);
    expect(sentencesFromWords(w, "v2").length).toBe(1);
  });
});

describe("Nacharbeit: Satzlänge, Abkürzungen, Fehlalarme", () => {
  function teile(links: string, rechts: string) {
    const w = woerter(`${links} ${rechts}`);
    const n = links.split(" ").length;
    return bracketHeuristic(w.slice(0, n), w.slice(n));
  }

  it("die Probe aus dem Review wird kein Satz von 1214 s", () => {
    const w: TranscriptWord[] = [];
    let t = 0;
    for (let k = 0; k < 3000; k += 1) {
      w.push({ text: k % 3 ? "wir" : "reden", start: t, end: t + 0.3, speaker: "S0" } as unknown as TranscriptWord);
      t += 0.4045;
    }
    expect(sentencesFromWords(w).length).toBe(1);
    const rule = resolveSentenceRule(w, "v2");
    expect(rule).toBe("v1_fallback_no_punct");
    const saetze = sentencesFromWords(w, rule);
    expect(saetze.length).toBeGreaterThan(60);
    expect(Math.max(...saetze.map((s) => s.end - s.start))).toBeLessThanOrEqual(50);
  });

  it("Abkürzungen und Ordinalzahlen beenden den Teilsatz nicht", () => {
    expect(teile("Wir haben am 3. Oktober das Projekt", "gestartet.").open).toBe(true);
    expect(teile("Wir haben mit Dr. Müller", "gesprochen.").open).toBe(true);
    expect(teile("Wir haben z. B. das Team", "umgebaut.").open).toBe(true);
  });

  it("findet Klammern mit Vorsilben und starken Partizipien", () => {
    expect(teile("Ich bin gestern", "angekommen.").open).toBe(true);
    expect(teile("Wir haben alles", "vorbereitet.").open).toBe(true);
    expect(teile("Ich bin", "überzeugt.").open).toBe(true);
    expect(teile("Er hat den Vertrag", "unterschrieben.").open).toBe(true);
    expect(teile("Wir haben einen großen", "Fehler gemacht.").open).toBe(true);
  });

  it("meldet keine Fehlalarme bei neuem Satz rechts", () => {
    expect(teile("Das ist teuer", "Und wir wachsen.").open).toBe(false);
    expect(teile("Er hat recht", "Die Kunden warten.").open).toBe(false);
    expect(teile("Als Gründer kennt man das Problem", "Jeder hat es.").open).toBe(false);
    expect(teile("Damit sind wir am Ziel", "Jetzt kommt der zweite Teil.").open).toBe(false);
  });

  it("liest die Regel aus stats.sentence_rule", () => {
    expect(sentenceRuleFromStats({ sentence_rule: "v2" })).toBe("v2");
    expect(sentenceRuleFromStats({ sentence_rule: "v1_fallback_no_punct" })).toBe("v1_fallback_no_punct");
    expect(sentenceRuleFromStats({})).toBe("v1");
    expect(sentenceRuleFromStats(null)).toBe("v1");
  });

  it("nummeriert Sätze aus sentence_idx fortlaufend ab 0", () => {
    const w = woerter("Das ist gut. Wir machen weiter.").map(
      (x, k) => ({ ...x, sentence_idx: k < 3 ? 4 : 7 }) as unknown as TranscriptWord,
    );
    expect(sentencesFromWords(w).map((s) => s.idx)).toEqual([0, 1]);
  });
});

describe("„Mag.“ unter v2", () => {
  it("ist Titel vor großgeschriebenem Namen, nach Personalpronomen oder vor Pause Satzende", () => {
    const titel = woerter("Ich bin Mag. Huber und arbeite hier.");
    expect(sentenceEndKind(titel, 2, "v2")).toBe("none");
    const verb = woerter("Ich mag. Das mag. Aber egal.", { 3: 0.9 });
    expect(sentenceEndKind(verb, 1, "v2")).toBe("punct");
    expect(sentenceEndKind(verb, 3, "v2")).toBe("punct");
  });
});
