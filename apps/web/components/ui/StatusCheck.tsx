import { cn } from "./cn";

export type StatusCheckState = "idle" | "active" | "done" | "error";

interface StatusCheckProps {
  state: StatusCheckState;
  size?: number;
  label?: string;
  className?: string;
}

/* Status-Check: helles Icon im #27272A-Kreis. Aktiv = KI-Glühen, Fehler = Orange (Mensch muss prüfen). */
export function StatusCheck({ state, size = 28, label, className }: StatusCheckProps) {
  const iconSize = Math.round(size * 0.5);
  return (
    <span
      role="img"
      aria-label={label ?? stateLabel(state)}
      className={cn(
        "transition-soft inline-flex shrink-0 items-center justify-center rounded-full bg-line-mute",
        state === "active" && "ai-pulse bg-brand-deep",
        state === "error" && "bg-attention/20",
        className,
      )}
      style={{ width: size, height: size }}
    >
      {state === "done" && (
        <svg width={iconSize} height={iconSize} viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M3 8.5l3 3 7-7" stroke="var(--ok)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {state === "active" && (
        <svg width={iconSize} height={iconSize} viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="5.5" stroke="var(--ai-soft)" strokeWidth="1.5" strokeDasharray="6 4" />
          <circle cx="8" cy="8" r="1.8" fill="var(--text)" />
        </svg>
      )}
      {state === "error" && (
        <svg width={iconSize} height={iconSize} viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M8 3.5v5.5M8 11.6v.4" stroke="var(--attention)" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      )}
      {state === "idle" && (
        <svg width={iconSize} height={iconSize} viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="2" fill="var(--text-3)" />
        </svg>
      )}
    </span>
  );
}

function stateLabel(state: StatusCheckState): string {
  switch (state) {
    case "done":
      return "Abgeschlossen";
    case "active":
      return "Läuft";
    case "error":
      return "Fehler, bitte prüfen";
    default:
      return "Ausstehend";
  }
}
