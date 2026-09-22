import { Grain } from "./Grain";
import { cn } from "./cn";

/* Weichgezeichnete Blasen in Brand-Blau hinter dem Inhalt. Fest am Viewport, damit sie beim Scrollen stehen bleiben.
 * tone="ai" hellt sie Richtung AI-Blau auf, solange die KI arbeitet. */
export function BlueBubbles({ className, tone = "brand" }: { className?: string; tone?: "brand" | "ai" }) {
  const main = tone === "ai" ? "rgba(47, 107, 255, 0.5)" : "rgba(2, 12, 245, 0.55)";
  return (
    <div aria-hidden="true" className={cn("pointer-events-none fixed inset-0 z-0 overflow-hidden print:hidden", className)}>
      <div className="bubble bubble-a" style={{ background: main }} />
      <div className="bubble bubble-b" style={{ background: "rgba(2, 12, 245, 0.42)" }} />
      <div className="bubble bubble-c" style={{ background: "rgba(27, 26, 98, 0.7)" }} />
      <div className="bubble bubble-d" style={{ background: "rgba(47, 107, 255, 0.28)" }} />
      <Grain />
    </div>
  );
}
