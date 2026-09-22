"use client";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { formatTimecode } from "@/lib/format";
import type { Candidate } from "@/lib/repo/types";
import { countGates } from "@/lib/candidates/gates";
import { VERDICT_LABELS, formatTotal, structureLabel, warningsOf } from "@/lib/candidates/labels";

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
      aria-label={`Kandidat ${index}: ${structureLabel(c.structure)}, ${durationLabel}, DACH-Qualität ${formatTotal(c.total)}`}
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
        <div className="shrink-0 text-right">
          <p className="text-4xl font-light leading-none tabular-nums tracking-[var(--tracking-display)] text-text">
            {formatTotal(c.total)}
          </p>
          <p className="mt-1 text-[11px] uppercase tracking-wide text-text-2">DACH-Qualität</p>
        </div>
      </div>

      <p className="mt-3 line-clamp-2 text-[15px] leading-relaxed text-text">{snippet(c.rubric.text)}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex h-6 items-center rounded-pill border px-2.5 font-mono text-[11px] tabular-nums",
            c.gate_passed ? "border-line-strong text-text" : "border-line text-text-2",
          )}
        >
          {gates.passed} von {gates.total} Pflichtkriterien
        </span>
        {warnings.map((w) => (
          <span
            key={w.key}
            className="inline-flex h-6 items-center rounded-pill border border-attention/60 bg-attention/10 px-2.5 text-[11px] font-medium text-attention"
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
