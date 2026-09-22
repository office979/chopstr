import { Grain } from "./Grain";
import { cn } from "./cn";

/* Lichtkegel: Licht als einzige Farbe, mit Körnung */
export function LightCone({ className, tone = "brand" }: { className?: string; tone?: "brand" | "ai" }) {
  const color = tone === "ai" ? "rgba(47, 107, 255, 0.34)" : "rgba(2, 12, 245, 0.30)";
  return (
    <div aria-hidden="true" className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)}>
      <div
        className="absolute left-1/2 top-[-40vh] h-[110vh] w-[140vw] -translate-x-1/2 sm:w-[90vw]"
        style={{
          background: `radial-gradient(ellipse at 50% 0%, ${color} 0%, rgba(27, 26, 98, 0.22) 28%, rgba(0, 0, 0, 0) 62%)`,
        }}
      />
      <Grain />
    </div>
  );
}
