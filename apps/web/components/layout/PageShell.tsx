import type { ReactNode } from "react";
import Link from "next/link";
import { PillNav } from "@/components/ui/PillNav";
import { LightCone } from "@/components/ui/LightCone";
import { BackgroundWord } from "@/components/ui/BackgroundWord";
import { cn } from "@/components/ui/cn";

interface PageShellProps {
  children: ReactNode;
  backgroundWord?: string;
  lightTone?: "brand" | "ai";
  width?: "narrow" | "default" | "wide";
  className?: string;
}

const widths = {
  narrow: "max-w-[760px]",
  default: "max-w-[1120px]",
  wide: "max-w-[1440px]",
};

/* Seitenrahmen: Hintergrundwort → Lichtkegel mit Körnung → Glas → Inhalt */
export function PageShell({ children, backgroundWord, lightTone = "brand", width = "default", className }: PageShellProps) {
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <LightCone tone={lightTone} />
      {backgroundWord && <BackgroundWord word={backgroundWord} />}
      <PillNav />
      <main className={cn("relative z-10 mx-auto w-full px-4 pb-24 pt-28 sm:px-6 sm:pt-32", widths[width], className)}>
        {children}
      </main>
      <footer className="relative z-10 mx-auto flex w-full max-w-[1120px] flex-wrap items-center justify-between gap-3 px-4 pb-8 text-xs text-text-3 sm:px-6">
        <span>chopstr · EU-verarbeitet · Mensch gibt frei</span>
        <span className="flex gap-4">
          <Link href="/einstellungen" className="hover:text-text-2">
            Workspace
          </Link>
          <span className="font-mono">v{process.env.APP_VERSION ?? "0.1.0"}</span>
        </span>
      </footer>
    </div>
  );
}
