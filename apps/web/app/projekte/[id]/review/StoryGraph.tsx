"use client";

import type { StoryGraphFlag } from "@/lib/repo/types";
import { formatSeconds } from "@/lib/candidates/labels";

interface Props {
  first: number;
  last: number;
  flag: StoryGraphFlag;
}

const W = 440;
const H = 84;
const Y = 36;
const CLIP_X0 = 18;
const CLIP_X1 = 262;
const FLAG_X = 410;

/* Haarlinien-Graph: graue Satz-Knoten des Clips, dann Abstand in Sekunden, dann der orange Knoten der Relativierung */
export function StoryGraph({ first, last, flag }: Props) {
  const n = Math.max(1, last - first + 1);
  const xs = Array.from({ length: n }, (_, i) => (n === 1 ? (CLIP_X0 + CLIP_X1) / 2 : CLIP_X0 + ((CLIP_X1 - CLIP_X0) * i) / (n - 1)));
  const dense = n > 12;
  const gapMid = (CLIP_X1 + FLAG_X) / 2;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full"
      role="img"
      aria-label={`Story-Graph: Clip von Satz ${first} bis ${last}, Relativierung in Satz ${flag.sentence_idx} nach ${formatSeconds(flag.seconds_after)}`}
    >
      {/* Clip-Linie */}
      <line x1={xs[0]} y1={Y} x2={xs[xs.length - 1]} y2={Y} stroke="var(--line-strong)" strokeWidth="1" />
      {/* Abstand zur Relativierung */}
      <line x1={CLIP_X1} y1={Y} x2={FLAG_X} y2={Y} stroke="var(--attention)" strokeWidth="1" strokeDasharray="3 5" opacity="0.8" />
      {/* Satz-Knoten des Clips */}
      {xs.map((x, i) => (
        <circle
          key={i}
          cx={x}
          cy={Y}
          r={dense ? 3 : 5}
          fill="var(--line-mute)"
          stroke={i === 0 || i === xs.length - 1 ? "var(--text-2)" : "var(--text-3)"}
          strokeWidth="1"
        />
      ))}
      {/* Relativierung */}
      <circle cx={FLAG_X} cy={Y} r="8" fill="rgba(255,122,69,0.18)" stroke="var(--attention)" strokeWidth="1.2" />
      <circle cx={FLAG_X} cy={Y} r="2.5" fill="var(--attention)" />

      <g fontFamily="var(--font-geist-mono), var(--font-mono)" fontSize="13" fill="var(--text-2)">
        <text x={xs[0]} y={Y + 28} textAnchor={n === 1 ? "middle" : "start"}>
          Satz {first}
        </text>
        {n > 1 && (
          <text x={xs[xs.length - 1]} y={Y + 28} textAnchor="end">
            Satz {last}
          </text>
        )}
        <text x={gapMid} y={Y - 14} textAnchor="middle" fill="var(--attention)">
          +{formatSeconds(flag.seconds_after)}
        </text>
        <text x={FLAG_X} y={Y + 28} textAnchor="end" fill="var(--attention)">
          Satz {flag.sentence_idx}
        </text>
      </g>
      <text
        x={(xs[0] + xs[xs.length - 1]) / 2}
        y={Y - 14}
        textAnchor="middle"
        fontSize="13"
        fill="var(--text-3)"
        fontFamily="var(--font-geist-sans), var(--font-sans)"
      >
        Clip
      </text>
    </svg>
  );
}
