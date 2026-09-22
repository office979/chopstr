import type { ReactNode } from "react";
import Link from "next/link";
import { Wordmark } from "@/components/brand/Wordmark";
import { BlueBubbles } from "@/components/ui/BlueBubbles";
import { GlassCard } from "@/components/ui/GlassCard";

interface AuthShellProps {
  title: string;
  description?: ReactNode;
  /* Veraltet, wird ignoriert */
  backgroundWord?: string;
  children: ReactNode;
  footer?: ReactNode;
  /* Demo-Modus: Hinweis über der Karte */
  demo?: boolean;
}

/* Rahmen für Anmelden, Registrieren, Magic-Link, Passwort, Einladung: ohne Navigation, eine Glas-Karte mittig */
export function AuthShell({ title, description, children, footer, demo }: AuthShellProps) {
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <BlueBubbles />
      <main className="relative z-10 mx-auto flex w-full max-w-[520px] flex-col px-4 pb-16 pt-16 sm:px-6 sm:pt-24">
        <Link href="/" aria-label="chopstr" className="mb-10 inline-flex w-fit">
          <Wordmark width={140} className="opacity-95" />
        </Link>
        {demo && (
          <p className="mb-4 rounded-inner border border-line px-4 py-3 text-sm text-text-2">
            Demo-Modus ohne Datenbank: Du bist automatisch als „Demo“ (Inhaber) angemeldet. Anmeldung und Registrierung sind hier ohne Wirkung.
          </p>
        )}
        <GlassCard padding="lg" className="flex flex-col gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] text-text sm:text-3xl">{title}</h1>
            {description && <p className="mt-2 text-[15px] text-text-2">{description}</p>}
          </div>
          {children}
        </GlassCard>
        {footer && <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm text-text-2">{footer}</div>}
      </main>
      <footer className="relative z-10 mx-auto flex w-full max-w-[520px] px-4 pb-8 text-xs text-text-3 sm:px-6">
        chopstr · EU-verarbeitet · Mensch gibt frei
      </footer>
    </div>
  );
}
