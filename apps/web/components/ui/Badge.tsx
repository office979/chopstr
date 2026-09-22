import type { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "ai" | "attention" | "danger" | "ok";

/* Status-Label, kein Button: eckiger Radius, kein Rand, Punkt davor. So verwechselt niemand es mit einer Aktion. */
const tones: Record<Tone, { box: string; dot: string }> = {
  neutral: { box: "bg-white/[0.06] text-text-2", dot: "bg-text-3" },
  ai: { box: "bg-ai/15 text-ai-soft", dot: "bg-ai-soft" },
  attention: { box: "bg-attention/15 text-attention", dot: "bg-attention" },
  danger: { box: "bg-danger/15 text-danger", dot: "bg-danger" },
  ok: { box: "bg-white/10 text-text", dot: "bg-text" },
};

export function Badge({ tone = "neutral", className, title, children }: { tone?: Tone; className?: string; title?: string; children: ReactNode }) {
  const t = tones[tone];
  return (
    <span
      title={title}
      className={cn("inline-flex h-6 cursor-default select-none items-center gap-1.5 rounded-md px-2 text-xs font-medium", t.box, className)}
    >
      <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", t.dot)} />
      {children}
    </span>
  );
}
