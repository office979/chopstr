"use client";

import type { ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Timecode } from "@/components/ui/Timecode";
import { cn } from "@/components/ui/cn";
import type { Candidate } from "@/lib/repo/types";
import { groupBySpeaker, sentenceRange, type Sentence } from "@/lib/transcript/sentences";

interface Props {
  candidate: Candidate;
  sentences: Sentence[];
  speakerNames: Record<string, string>;
  currentTime: number;
  onSeek: (t: number) => void;
  preview: ReactNode;
}

/* Clip-Text mit Sprecherlabels und Timecodes; der gerade gespielte Satz ist hervorgehoben */
export function ClipText({ candidate: c, sentences, speakerNames, currentTime, onSeek, preview }: Props) {
  const range = c.first_sent != null && c.last_sent != null ? sentenceRange(sentences, c.first_sent, c.last_sent) : [];
  const blocks = groupBySpeaker(range);
  const titleCard = c.rubric.suggested_title_card?.trim();

  return (
    <GlassCard padding="md">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-mono text-xs tabular-nums text-text-2">
          <Timecode seconds={c.start_s} withMillis className="text-text" />
          <span className="text-text-3">bis</span>
          <Timecode seconds={c.end_s} withMillis className="text-text" />
          {c.first_sent != null && c.last_sent != null && (
            <span className="text-text-3">
              Satz {c.first_sent} bis {c.last_sent}
            </span>
          )}
        </div>
        {preview}
      </div>

      {titleCard && (
        <div className="mb-4 flex items-center gap-3 rounded-inner border border-line px-4 py-3">
          <span className="text-xs uppercase tracking-wide text-text-2">Titelkarte</span>
          <span className="text-[15px] font-medium text-text">{titleCard}</span>
        </div>
      )}

      {blocks.length === 0 ? (
        <p className="text-sm text-text-2">Die Sätze zu diesem Clip stehen nicht mehr im aktuellen Text.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {blocks.map((b, i) => {
            const label = speakerNames[b.speaker] ?? b.speaker;
            return (
              <section key={`${b.speaker}-${i}`} aria-label={`${label} ab ${Math.floor(b.start)} Sekunden`}>
                <div className="mb-1.5 flex items-center gap-3">
                  <span className="inline-flex h-6 items-center rounded-md bg-white/10 px-2 text-xs font-medium text-text">
                    {label}
                  </span>
                  <Timecode seconds={b.start} className="text-xs" />
                </div>
                <p className="text-[16px] leading-[1.8] text-text">
                  {b.sentences.map((s) => {
                    const active = currentTime >= s.start && currentTime < s.end + 0.3;
                    /* span statt button: Buttons sind in Chrome immer Inline-Block und würden pro Satz umbrechen */
                    return (
                      <span
                        key={s.idx}
                        role="button"
                        tabIndex={0}
                        onClick={() => onSeek(s.start)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            onSeek(s.start);
                          }
                        }}
                        className={cn(
                          "transition-soft mr-1 cursor-pointer rounded-md px-0.5 hover:bg-white/10",
                          active && "bg-white/15",
                        )}
                        aria-label={`Satz ${s.idx} abspielen`}
                      >
                        {s.text}
                      </span>
                    );
                  })}
                </p>
              </section>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
