import { formatTimecode } from "@/lib/format";
import { cn } from "./cn";

interface TimecodeProps {
  seconds: number | null | undefined;
  withMillis?: boolean;
  className?: string;
}

/* Timecodes immer in Geist Mono mit Tabellenziffern */
export function Timecode({ seconds, withMillis = false, className }: TimecodeProps) {
  return (
    <span className={cn("font-mono tabular-nums text-text-2", className)}>
      {formatTimecode(seconds, withMillis)}
    </span>
  );
}
