import type { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "ai" | "attention" | "danger" | "ok";

const tones: Record<Tone, string> = {
  neutral: "border-line text-text-2",
  ai: "border-ai-soft/50 text-ai-soft",
  attention: "border-attention/60 text-attention",
  danger: "border-danger/60 text-danger",
  ok: "border-line-strong text-text",
};

export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center rounded-pill border px-3 text-xs font-medium tracking-wide",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
