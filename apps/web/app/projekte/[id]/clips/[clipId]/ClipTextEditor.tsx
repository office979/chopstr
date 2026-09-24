"use client";

import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Select } from "@/components/ui/Field";
import { Timecode } from "@/components/ui/Timecode";
import { cn } from "@/components/ui/cn";
import type { TranscriptWord } from "@/lib/repo/types";

/* Zusammenhängende Wörter desselben Sprechers. Geht aus review/ClipText.tsx hervor, dort waren
 * die Blöcke nur zum Lesen da; hier lässt sich jedes Wort ändern und jeder Block einem anderen
 * Sprecher zuordnen. */
interface Block {
  speaker: string;
  start: number;
  end: number;
  indices: number[];
}

const LOW_CONFIDENCE = 0.9;

export function blocksInRange(words: TranscriptWord[], from: number, to: number): Block[] {
  const out: Block[] = [];
  for (let i = from; i <= to; i += 1) {
    const w = words[i];
    if (!w) continue;
    const last = out[out.length - 1];
    if (last && last.speaker === w.speaker) {
      last.indices.push(i);
      last.end = w.end;
    } else {
      out.push({ speaker: w.speaker, start: w.start, end: w.end, indices: [i] });
    }
  }
  return out;
}

interface Props {
  words: TranscriptWord[];
  original: TranscriptWord[];
  wordFrom: number;
  wordTo: number;
  speakers: string[];
  speakerNames: Record<string, string>;
  /* Stelle im ganzen Video, die gerade läuft */
  currentTime: number;
  canEdit: boolean;
  onEditWord: (index: number, text: string) => void;
  onChangeSpeaker: (indices: number[], speaker: string) => void;
  onSeek: (secondsInSource: number) => void;
}

/* Text des Clips: Wortlaut ändern und zuordnen, wer spricht. */
export function ClipTextEditor({
  words,
  original,
  wordFrom,
  wordTo,
  speakers,
  speakerNames,
  currentTime,
  canEdit,
  onEditWord,
  onChangeSpeaker,
  onSeek,
}: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [ganz, setGanz] = useState(false);
  const blocks = blocksInRange(words, wordFrom, wordTo);
  const kasten = useRef<HTMLDivElement | null>(null);
  const aktivesWort = useRef<HTMLButtonElement | null>(null);

  /* Das gesprochene Wort in Sicht halten. Der Text ist lang, die Stelle wandert, und wer zusieht
   * soll nicht scrollen muessen um zu lesen, was gerade gesagt wird.
   *
   * Gescrollt wird im Kasten selbst und nicht mit scrollIntoView: das zieht sonst die ganze Seite
   * mit, und die Vorschau oben springt aus dem Bild. */
  useEffect(() => {
    if (ganz || editingIndex != null) return;
    const box = kasten.current;
    const wort = aktivesWort.current;
    if (!box || !wort) return;
    const ziel = wort.offsetTop - box.clientHeight / 2 + wort.offsetHeight / 2;
    box.scrollTo({ top: Math.max(0, ziel), behavior: "smooth" });
  }, [currentTime, ganz, editingIndex]);

  if (blocks.length === 0) {
    return (
      <GlassCard padding="md">
        <p className="text-sm text-text-2">Zu diesem Clip steht kein Text bereit.</p>
      </GlassCard>
    );
  }

  return (
    <GlassCard padding="md">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Text</h2>
        <button
          type="button"
          onClick={() => setGanz((v) => !v)}
          className="transition-soft text-sm text-text-2 underline underline-offset-4 hover:text-text"
        >
          {ganz ? "Nur die Stelle zeigen" : "Ganzen Text zeigen"}
        </button>
      </div>
      <p className="mb-3 text-sm text-text-2">
        {canEdit
          ? "Klick ein Wort an, um dorthin zu springen. Doppelklick, wenn du es ändern willst."
          : "Klick ein Wort an, um dorthin zu springen."}
      </p>

      {/* Zusammengeklappt nur rund drei Zeilen, die mit dem Ton mitlaufen. Der ganze Text stand
        * vorher offen da und hat die halbe Seite gefuellt, obwohl fast immer nur die Stelle
        * interessiert, die gerade laeuft. */}
      <div
        ref={kasten}
        className={cn(
          "flex flex-col gap-5 overflow-y-auto pr-1",
          ganz ? "max-h-[60dvh]" : "max-h-[8.6rem]",
        )}
      >
        {blocks.map((b, bi) => {
          const label = speakerNames[b.speaker] ?? b.speaker;
          return (
            <section key={`${b.speaker}-${bi}`} aria-label={`${label} ab ${Math.floor(b.start)} Sekunden`}>
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <div className="w-[150px]">
                  <Select
                    aria-label={`Wer spricht ab ${Math.floor(b.start)} Sekunden`}
                    value={b.speaker}
                    disabled={!canEdit}
                    onChange={(e) => onChangeSpeaker(b.indices, e.target.value)}
                  >
                    {speakers.map((s) => (
                      <option key={s} value={s}>
                        {speakerNames[s] ?? s}
                      </option>
                    ))}
                  </Select>
                </div>
                <button
                  type="button"
                  onClick={() => onSeek(b.start)}
                  className="font-mono text-xs text-text-2 hover:text-text"
                  aria-label={`Zu ${Math.floor(b.start)} Sekunden springen`}
                >
                  <Timecode seconds={b.start} className="text-inherit" />
                </button>
              </div>

              <p className="text-[16px] leading-[1.75] text-text">
                {b.indices.map((i) => {
                  const w = words[i];
                  const changed = original[i] != null && original[i].text !== w.text;
                  const low = w.prob < LOW_CONFIDENCE;
                  const active = currentTime >= w.start && currentTime < w.end + 0.15;
                  if (editingIndex === i) {
                    return (
                      <input
                        key={i}
                        autoFocus
                        defaultValue={w.text}
                        aria-label={`Wort ändern: ${w.text}`}
                        size={Math.max(3, w.text.length + 1)}
                        onFocus={(e) => e.currentTarget.select()}
                        className="mx-0.5 inline-block rounded-md border border-white/60 bg-black/70 px-1.5 py-0.5 font-sans text-[17px] text-text focus:outline-none"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            onEditWord(i, e.currentTarget.value);
                            setEditingIndex(null);
                          } else if (e.key === "Escape") {
                            setEditingIndex(null);
                          }
                        }}
                        onBlur={(e) => {
                          onEditWord(i, e.currentTarget.value);
                          setEditingIndex(null);
                        }}
                      />
                    );
                  }
                  return (
                    <button
                      key={i}
                      ref={active ? aktivesWort : undefined}
                      type="button"
                      onClick={() => onSeek(w.start)}
                      onDoubleClick={() => canEdit && setEditingIndex(i)}
                      onKeyDown={(e) => {
                        if (canEdit && e.key === "Enter") {
                          e.preventDefault();
                          setEditingIndex(i);
                        }
                      }}
                      title={changed ? `Vorher: ${original[i].text}` : low ? "Der Computer war sich hier nicht sicher" : undefined}
                      className={cn(
                        "transition-soft mx-px inline rounded-md px-0.5 py-0.5 text-left align-baseline hover:bg-white/10",
                        low && "word-low",
                        changed && "text-ai-soft",
                        active && "word-active",
                      )}
                    >
                      {w.text}
                    </button>
                  );
                })}
              </p>
            </section>
          );
        })}
      </div>
    </GlassCard>
  );
}
