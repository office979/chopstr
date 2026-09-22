import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { checkHookLimits, styleNotes } from "../src/hooks.js";
import { parseArgs, readConfig, normalizeApiUrl, ConfigError } from "../src/config.js";
import { HOOKS_V1_RULES } from "../src/prompts.js";
import { renderTranscriptText, summarizeTranscript, windowWords } from "../src/transcript.js";
import { describeHttpError } from "../src/api.js";

describe("Hook-Wortlimits", () => {
  it("erlaubt 12 und 9 Wörter, meldet 13 und 10", () => {
    expect(checkHookLimits({ spoken_hook: "a b c d e f g h i j k l", onscreen_hook: "a b c d e f g h i" })).toEqual([]);
    const v = checkHookLimits({ spoken_hook: "a b c d e f g h i j k l m", onscreen_hook: "a b c d e f g h i j" });
    expect(v.map((x) => x.field)).toEqual(["spoken_hook", "onscreen_hook"]);
  });
  it("zählt Wörter unabhängig von Mehrfach-Leerzeichen", () => {
    expect(checkHookLimits({ spoken_hook: "  eins   zwei  " })).toEqual([]);
  });
  it("Stilhinweise erkennen Gedankenstrich, Emoji und abgenutzte Muster", () => {
    expect(styleNotes("Du glaubst nicht – was passiert")).toHaveLength(2);
    expect(styleNotes("Marge weg")).toEqual([]);
  });
});

describe("Transkript", () => {
  const words = [
    { text: "Hallo", start: 0, end: 0.5, speaker: "SPEAKER_00" },
    { text: "Welt.", start: 0.5, end: 1, speaker: "SPEAKER_00" },
    { text: "Servus", start: 61, end: 61.5, speaker: "SPEAKER_01" },
  ];
  it("fenstert nach Sekunden", () => {
    expect(windowWords(words, 60, 70).map((w) => w.text)).toEqual(["Servus"]);
    expect(windowWords(words, undefined, 1).map((w) => w.text)).toEqual(["Hallo", "Welt."]);
  });
  it("rendert Sprecherwechsel mit Timecodes und Namen", () => {
    expect(renderTranscriptText(words, { SPEAKER_01: "Max" })).toBe("[0:00] SPEAKER_00: Hallo Welt.\n[1:01] Max: Servus");
  });
  it("fasst zusammen", () => {
    const s = summarizeTranscript({ words, version: 2, stats: { speaker_names: { SPEAKER_00: "Anna" } } });
    expect(s.duration_s).toBe(62);
    expect(s.speakers[0]).toMatchObject({ id: "SPEAKER_00", name: "Anna", words: 2 });
    expect(s.preview_truncated).toBe(false);
  });
});

describe("Konfiguration", () => {
  it("verlangt CHOPSTR_API_KEY mit Präfix", () => {
    expect(() => readConfig({})).toThrow(ConfigError);
    expect(() => readConfig({ CHOPSTR_API_KEY: "falsch" })).toThrow(/Format/);
    const c = readConfig({ CHOPSTR_API_KEY: "chp_live_abc", CHOPSTR_API_URL: "https://app.example/api/v1/" });
    expect(c.apiUrl).toBe("https://app.example/api/v1");
    expect(c.timeoutMs).toBe(30000);
  });
  it("hat einen Standard für die URL", () => {
    expect(normalizeApiUrl(undefined)).toBe("http://localhost:3000/api/v1");
    expect(() => normalizeApiUrl("ftp://x")).toThrow(ConfigError);
  });
  it("parst --http und --host", () => {
    expect(parseArgs([])).toEqual({ http: null, host: "127.0.0.1", help: false });
    expect(parseArgs(["--http", "8765", "--host", "0.0.0.0"])).toMatchObject({ http: 8765, host: "0.0.0.0" });
    expect(parseArgs(["--http=8765"])).toMatchObject({ http: 8765 });
    expect(() => parseArgs(["--http", "abc"])).toThrow(ConfigError);
    expect(() => parseArgs(["--foo"])).toThrow(/Unbekannte Option/);
  });
});

describe("Fehlerübersetzung", () => {
  it("deckt alle Statuscodes ab", () => {
    expect(describeHttpError(402, null, null, "/sources").kind).toBe("quota");
    expect(describeHttpError(403, null, null, "/x").message).toMatch(/Scope/);
    expect(describeHttpError(409, "guest_approval_missing", null, "/clips/1/publish").message).toMatch(/Gast-Freigabe/);
    expect(describeHttpError(409, null, "bereits ersetzt", "/candidates/1/verdict").message).not.toMatch(/Gast-Freigabe/);
    expect(describeHttpError(418, null, null, "/x").kind).toBe("bad_request");
    expect(describeHttpError(503, null, null, "/x").kind).toBe("server");
  });
});

describe("hooks_v1 Spiegel", () => {
  it("entspricht packages/prompts/hooks_v1.md", () => {
    const file = readFileSync(resolve(import.meta.dirname, "../../prompts/hooks_v1.md"), "utf8");
    const body = file.replace(/^---[\s\S]*?---\s*/, "").trim();
    expect(HOOKS_V1_RULES.trim()).toBe(body);
  });
});
