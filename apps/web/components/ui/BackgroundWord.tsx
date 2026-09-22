import { cn } from "./cn";

/* Riesiges, halb verdecktes Hintergrundwort */
export function BackgroundWord({ word, className }: { word: string; className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "bg-word pointer-events-none absolute left-1/2 top-[6vh] -translate-x-1/2 select-none whitespace-nowrap leading-none",
        "text-[46vw] sm:text-[30vw] lg:text-[22vw]",
        className,
      )}
    >
      {word}
    </div>
  );
}
