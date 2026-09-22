import { cn } from "./cn";

/* Körnung als SVG-Noise. Liegt nur über dem Lichtkegel, nie über Text (pointer-events: none, z-Index unter Inhalt). */
export function Grain({ className, opacity }: { className?: string; opacity?: number }) {
  return (
    <svg
      aria-hidden="true"
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
      style={{ opacity: opacity ?? "var(--grain-opacity)", mixBlendMode: "screen" }}
    >
      <filter id="chopstr-grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#chopstr-grain)" />
    </svg>
  );
}
