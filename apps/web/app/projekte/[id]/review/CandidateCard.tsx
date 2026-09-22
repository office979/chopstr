"use client";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { formatTimecode } from "@/lib/format";
import type { Candidate } from "@/lib/repo/types";
import { countGates } from "@/lib/candidates/gates";
import { VERDICT_LABELS, formatTotal, qualityWord, structureLabel, warningsOf } from "@/lib/candidates/labels";

interface Props {
  candidate: Candidate;
  index: number;
  selected: boolean;
  glitch: boolean;
  onSelect: () => void;
  cardRef: (el: HTMLButtonElement | null) => void;
}

function snippet(text: string, max = 150): string {
  const plain = text.replace(/^SPEAKER_\d+:\s*/gm, "").replace(/\s+/g, " ").trim();
  return plain.length > max ? `${plain.slice(0, max).replace(/\s+\S*$/, "")} …` : plain;
}

/* Glas-Karte eines Kandidaten: Struktur, Dauer, DACH-Qualität groß, Gate-Zähler klein, Warnungen orange */
export function CandidateCard({ candidate: c, index, selected, glitch, onSelect, cardRef }: Props) {
  const gates = countGates(c.gates);
  const warnings = warningsOf(c);
  const durationLabel = `${c.rubric.duration_s.toLocaleString("de-AT", { maximumFractionDigits: 0 })} s`;

  return (
    <button
      ref={cardRef}
      type="button"
      data-card="true"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Moment ${index}: ${structureLabel(c.structure)}, ${durationLabel}, Bewertung ${qualityWord(c.total)}`}
      className={cn(
        "glass transition-soft relative w-full rounded-card p-5 text-left hover:border-white/25",
        selected && "glass-selected",
        glitch && "spectrum-glitch",
        c.human_verdict === "rejected" && !selected && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <Badge tone={selected ? "ai" : "neutral"}>{structureLabel(c.structure)}</Badge>
          <span className="font-mono text-xs tabular-nums text-text-2">
            {formatTimecode(c.start_s)} bis {formatTimecode(c.end_s)}
          </span>
          <span className="font-mono text-xs tabular-nums text-text-2">{durationLabel}</span>
          {c.version > 1 && <Badge>Version {c.version}</Badge>}
        </div>
        <div className="shrink-0 text-right" title={`Bewertung ${formatTotal(c.total)} von 10`}>
          <p className="text-2xl font-light leading-tight tracking-[var(--tracking-display)] text-text">
            {qualityWord(c.total)}
          </p>
        </div>
      </div>

      <p className="mt-3 line-clamp-2 text-[15px] leading-relaxed text-text">{snippet(c.rubric.text)}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex h-6 items-center rounded-md px-2 font-mono text-[11px] tabular-nums",
            c.gate_passed ? "bg-white/10 text-text" : "bg-white/[0.06] text-text-2",
          )}
        >
          {c.gate_passed ? "Alles geprüft" : `${gates.passed} von ${gates.total} geprüft`}
        </span>
        {warnings.map((w) => (
          <span
            key={w.key}
            className="inline-flex h-6 items-center rounded-md bg-attention/15 px-2 text-[11px] font-medium text-attention"
          >
            {w.label}
          </span>
        ))}
        {c.human_verdict && c.human_verdict !== "edited" && (
          <Badge tone={c.human_verdict === "accepted" ? "ok" : "neutral"} className="ml-auto">
            {VERDICT_LABELS[c.human_verdict]}
          </Badge>
        )}
      </div>
    </button>
  );
}
