import type { ReactNode } from "react";
import { cn } from "./cn";

/* „Details für Profis“: ein aufklappbarer Bereich, überall gleich beschriftet und an derselben
 * Stelle (docs/BEDIENKONZEPT.md, Abschnitt 9). Hier landet alles, was keine Entscheidung auslöst:
 * Messwerte, Prüfsummen, Modellnamen, Serverzustand.
 *
 * Bewusst <details> statt eigener Zustand: funktioniert ohne JavaScript, ist von Haus aus
 * tastaturbedienbar und wird von Screenreadern als aufklappbar angesagt. Zugeklappt als
 * Voreinstellung, und es merkt sich den Zustand nicht: wer die Seite neu öffnet, sieht wieder
 * die ruhige Fassung. */
export function ProDetails({
  children,
  label = "Details für Profis",
  className,
}: {
  children: ReactNode;
  label?: string;
  className?: string;
}) {
  return (
    <details className={cn("group border-t border-line pt-3", className)}>
      <summary className="transition-soft inline-flex cursor-pointer list-none items-center gap-1.5 text-xs text-text-3 hover:text-text-2 [&::-webkit-details-marker]:hidden">
        <svg
          width="10"
          height="10"
          viewBox="0 0 16 16"
          fill="none"
          aria-hidden="true"
          className="transition-soft group-open:rotate-90"
        >
          <path d="m6 3 5 5-5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {label}
      </summary>
      <div className="mt-3 flex flex-col gap-2 text-xs text-text-2">{children}</div>
    </details>
  );
}

/* Eine Zeile darin: Bezeichnung links, Wert rechts, Zahlen monospaced damit Spalten stehen. */
export function ProRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
      <span className="text-text-3">{label}</span>
      <span className="min-w-0 break-all text-right font-mono text-text-2">{children}</span>
    </div>
  );
}
