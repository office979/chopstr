/* Was an den eingestellten Untertiteln nicht aufgeht. Reine Rechnung, deshalb hier.
 *
 * Der Punkt dieser Prüfung ist, dass sie am EINGESTELLTEN Stil hängt und nicht am letzten Render:
 * eine Warnung muss verschwinden, sobald ihre Ursache weg ist. Sonst steht sie da, ohne dass
 * jemand etwas dagegen tun kann, und wird zu Rauschen. */

import { describe, expect, it } from "vitest";
import { befundSatz, karten, MAX_CPS, pruefen, tempo } from "@/lib/clips/untertitel-pruefung";
import { LOOKS } from "@/lib/clips/caption-style";
import type { TranscriptWord } from "@/lib/repo/types";

/* Wörter mit fester Dauer bauen. ``proSekunde`` steuert, wie schnell gesprochen wird. */
function woerter(texte: string[], proSekunde = 2): TranscriptWord[] {
  const d = 1 / proSekunde;
  return texte.map((text, i) => ({
    text,
    start: i * d,
    end: (i + 1) * d,
    prob: 1,
    speaker: "SPEAKER_00",
    filler: null,
    negation: false,
    sentence_idx: 0,
  }));
}

describe("karten", () => {
  it("gruppiert bei fester Wortzahl genau so", () => {
    const k = karten(woerter(["a", "b", "c", "d", "e"]), 2, 100);
    expect(k.map((x) => x.text)).toEqual(["a b", "c d", "e"]);
  });

  it("nimmt Anfang und Ende aus den Wörtern", () => {
    const k = karten(woerter(["a", "b"], 1), 2, 100);
    expect(k[0].von).toBe(0);
    expect(k[0].bis).toBe(2);
  });

  it("füllt ohne feste Wortzahl bis zum Zeichenbudget", () => {
    const k = karten(woerter(["aaaa", "bbbb", "cccc"]), undefined, 10);
    expect(k.map((x) => x.text)).toEqual(["aaaa bbbb", "cccc"]);
  });

  it("gibt bei leerer Eingabe nichts aus", () => {
    expect(karten([], 2, 100)).toEqual([]);
  });
});

describe("pruefen", () => {
  it("meldet nichts bei ruhigem Sprechtempo", () => {
    expect(pruefen(woerter(["Wir", "haben", "nachgerechnet"], 1.5), LOOKS[0].stil)).toEqual([]);
  });

  it("schweigt beim Tempo, wenn ein Wort je Einblendung steht", () => {
    /* Wort für Wort ist ein Stil und kein Fehler: jedes Wort steht so lange, wie es gesprochen
     * wird, und niemand liest voraus. An echtem Material lagen sonst 1574 von 2007 Wörtern über
     * der Grenze. */
    const schnell = woerter(["Der", "Empfänger", "prüft", "zuerst"], 8);
    expect(pruefen(schnell, { ...LOOKS[0].stil, words_per_card: 1, font_px: 60 })).toEqual([]);
  });

  it("sortiert die schnellsten Stellen nach vorn", () => {
    const w = [
      ...woerter(["Unternehmensberatungsgesellschaft", "Personalgewinnung"], 12),
      ...woerter(["kurz", "gut"], 1).map((x) => ({ ...x, start: x.start + 10, end: x.end + 10 })),
    ];
    const b = pruefen(w, { ...LOOKS[0].stil, words_per_card: 2, font_px: 40, max_lines: 4 });
    const schnell = b.filter((x) => x.grund === "zu_schnell");
    for (let i = 1; i < schnell.length; i += 1) {
      expect(schnell[i - 1].cps ?? 0).toBeGreaterThanOrEqual(schnell[i].cps ?? 0);
    }
  });

  it("meldet eine Stelle, die zu schnell durchläuft", () => {
    /* Zwei lange Wörter in einer Zehntelsekunde: weit über dem, was sich lesen lässt. Die Schrift
     * ist klein genug, dass der Text in die Zeilen passt - sonst wäre das der andere Befund, und
     * der geht vor: was gar nicht ins Bild passt, ist das größere Problem. */
    const schnell = woerter(["Unternehmensberatung", "Personalgewinnung"], 20);
    const b = pruefen(schnell, { ...LOOKS[0].stil, words_per_card: 2, font_px: 40, max_lines: 4 });
    expect(b).toHaveLength(1);
    expect(b[0].grund).toBe("zu_schnell");
    expect(b[0].cps).toBeGreaterThan(MAX_CPS);
    expect(befundSatz(b[0])).toContain("Zeichen je Sekunde");
  });

  it("nennt zuerst, was gar nicht ins Bild passt", () => {
    /* Beides zugleich: die Karte ist zu schnell UND zu lang. Der Nutzer kann nur das zweite
     * beheben, deshalb steht es vorn. */
    const b = pruefen(woerter(["Unternehmensberatung", "Personalgewinnung"], 20), {
      ...LOOKS[0].stil,
      words_per_card: 2,
      font_px: 140,
      max_lines: 1,
    });
    expect(b[0].grund).toBe("passt_nicht");
  });

  it("verschwindet, wenn die Ursache weg ist", () => {
    /* Der Kern: dieselbe Stelle, langsamer gesprochen, ergibt keinen Tempo-Befund mehr. Eine
     * Warnung, die immer dasteht, ist keine Hilfe. */
    const text = ["Unternehmensberatung", "Personalgewinnung"];
    const stil = { ...LOOKS[0].stil, words_per_card: 2, font_px: 40, max_lines: 4 };
    expect(pruefen(woerter(text, 20), stil).filter((b) => b.grund === "zu_schnell")).toHaveLength(1);
    expect(pruefen(woerter(text, 0.4), stil).filter((b) => b.grund === "zu_schnell")).toHaveLength(0);
  });

  it("meldet Text, der nicht in die erlaubten Zeilen passt", () => {
    /* Sechs lange Wörter auf einer Zeile bei großer Schrift: der Renderer lässt weg, was nicht
     * mehr hineinpasst, und das muss dastehen. */
    const lang = woerter(["Personalgewinnungsstrategie", "Unternehmensberatung", "Wirtschaftsprüfung"], 0.25);
    const b = pruefen(lang, { ...LOOKS[0].stil, words_per_card: 3, max_lines: 1, font_px: 140 });
    expect(b.map((x) => x.grund)).toContain("passt_nicht");
  });

  it("behebt sich mit mehr Zeilen", () => {
    const lang = woerter(["Personalgewinnungsstrategie", "Unternehmensberatung", "Wirtschaftsprüfung"], 0.25);
    const eng = { ...LOOKS[0].stil, words_per_card: 3, max_lines: 1, font_px: 140 };
    expect(pruefen(lang, eng).length).toBeGreaterThan(0);
    expect(pruefen(lang, { ...eng, max_lines: 4, font_px: 60 })).toEqual([]);
  });

  it("rechnet Großbuchstaben mit, weil sie mehr Platz brauchen", () => {
    /* „ß" wird zu „SS": ein Zeichen mehr. Wer all_caps einstellt, bekommt also mehr Text, und
     * die Prüfung muss das sehen. */
    const w = woerter(["Straßenverkehrsordnungsmaßnahme"], 3);
    const ohne = pruefen(w, { ...LOOKS[0].stil, words_per_card: 1, all_caps: false });
    const mit = pruefen(w, { ...LOOKS[0].stil, words_per_card: 1, all_caps: true });
    expect(mit.length).toBeGreaterThanOrEqual(ohne.length);
  });

  it("meldet jede Stelle nur einmal", () => {
    const w = woerter(["Unternehmensberatung", "Personalgewinnung"], 20);
    const b = pruefen(w, { ...LOOKS[0].stil, words_per_card: 2 });
    const zeiten = b.map((x) => x.karte.von);
    expect(new Set(zeiten).size).toBe(zeiten.length);
  });

  it("kommt mit einem leeren Clip zurecht", () => {
    expect(pruefen([], LOOKS[0].stil)).toEqual([]);
  });
});

describe("tempo", () => {
  it("nennt das mittlere Lesetempo des Clips", () => {
    /* Damit sich ein Tempo-Hinweis einordnen lässt: liegt schon der Mittelwert darüber, ist nicht
     * eine Stelle zu schnell, sondern der Sprecher zügig. */
    const t = tempo(woerter(["Unternehmensberatung", "Personalgewinnung"], 12), {
      ...LOOKS[0].stil,
      words_per_card: 2,
      font_px: 40,
      max_lines: 4,
    });
    expect(t.mittel).toBeGreaterThan(MAX_CPS);
    expect(t.ueberGrenze).toBe(true);
  });

  it("gibt bei Wort für Wort nichts aus, weil es dort kein Lesetempo gibt", () => {
    expect(tempo(woerter(["Der", "Empfänger"], 8), { ...LOOKS[0].stil, words_per_card: 1 })).toEqual({
      mittel: 0,
      ueberGrenze: false,
    });
  });
});
