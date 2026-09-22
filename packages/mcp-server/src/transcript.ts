/* Transkript als Text mit Sprechern und Timecodes, Fensterung nach Sekunden, Kurzfassung. */

import { formatSeconds, firstWords } from "./format.js";
import type { Transcript, TranscriptWord } from "./types.js";

export const SUMMARY_WORDS = 200;

export interface TranscriptSummary {
  duration_s: number;
  word_count: number;
  speakers: Array<{ id: string; name: string | null; words: number; seconds: number }>;
  version: number | null;
  language: string | null;
  preview: string;
  preview_truncated: boolean;
}

export function speakerNames(transcript: Transcript): Record<string, string> {
  return { ...(transcript.stats?.speaker_names ?? {}), ...(transcript.speaker_names ?? {}) };
}

export function speakerLabel(id: string | undefined, names: Record<string, string>): string {
  if (!id) return "Sprecher";
  const name = names[id];
  return name ? name : id;
}

export function transcriptDuration(words: TranscriptWord[]): number {
  let max = 0;
  for (const w of words) if (Number.isFinite(w.end) && w.end > max) max = w.end;
  return max;
}

export function windowWords(words: TranscriptWord[], startS?: number | null, endS?: number | null): TranscriptWord[] {
  const from = startS ?? Number.NEGATIVE_INFINITY;
  const to = endS ?? Number.POSITIVE_INFINITY;
  return words.filter((w) => w.end > from && w.start < to);
}

/* Absätze je Sprecherwechsel, jeweils mit Startzeit. Neue Zeile auch nach etwa 40 Wörtern desselben Sprechers. */
export function renderTranscriptText(words: TranscriptWord[], names: Record<string, string>): string {
  const lines: string[] = [];
  let current: { speaker: string | undefined; start: number; parts: string[] } | null = null;
  const flush = () => {
    if (!current || current.parts.length === 0) return;
    lines.push(`[${formatSeconds(current.start)}] ${speakerLabel(current.speaker, names)}: ${current.parts.join(" ")}`);
    current = null;
  };
  for (const w of words) {
    const text = (w.text ?? "").trim();
    if (!text) continue;
    if (!current || current.speaker !== w.speaker || current.parts.length >= 40) {
      flush();
      current = { speaker: w.speaker, start: w.start, parts: [] };
    }
    current.parts.push(text);
  }
  flush();
  return lines.join("\n");
}

export function summarizeTranscript(transcript: Transcript): TranscriptSummary {
  const words = transcript.words ?? [];
  const names = speakerNames(transcript);
  const perSpeaker = new Map<string, { words: number; seconds: number }>();
  for (const w of words) {
    const id = w.speaker ?? "SPEAKER_?";
    const entry = perSpeaker.get(id) ?? { words: 0, seconds: 0 };
    entry.words += 1;
    entry.seconds += Math.max(0, (w.end ?? 0) - (w.start ?? 0));
    perSpeaker.set(id, entry);
  }
  const speakers = [...perSpeaker.entries()]
    .map(([id, v]) => ({ id, name: names[id] ?? null, words: v.words, seconds: Math.round(v.seconds) }))
    .sort((a, b) => b.words - a.words);
  const plain = words.map((w) => w.text).join(" ");
  const preview = firstWords(plain, SUMMARY_WORDS);
  return {
    duration_s: Math.round(transcriptDuration(words)),
    word_count: words.length,
    speakers,
    version: typeof transcript.version === "number" ? transcript.version : null,
    language: transcript.language ?? null,
    preview: preview.text,
    preview_truncated: preview.truncated,
  };
}
