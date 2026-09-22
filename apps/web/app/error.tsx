"use client";

import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button, ButtonLink } from "@/components/ui/Button";
import { LightCone } from "@/components/ui/LightCone";
import { BackgroundWord } from "@/components/ui/BackgroundWord";

/* Globale Fehlergrenze: 403 aus requireRole() (ForbiddenError) und sonstige Serverfehler in Lichtbruch-Optik */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string; status?: number }; reset: () => void }) {
  const forbidden = error.name === "ForbiddenError" || error.status === 403 || /nicht freigegeben|vorbehalten|dürfen nur|keinen Zugriff/i.test(error.message);
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <LightCone tone="brand" />
      <BackgroundWord word={forbidden ? "403" : "Fehler"} />
      <main className="relative z-10 mx-auto w-full max-w-[640px] px-4 pb-24 pt-28 sm:px-6 sm:pt-32">
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">{forbidden ? "Kein Zugriff" : "Da ist etwas schiefgelaufen"}</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            {forbidden ? error.message : "Bitte versuch es noch einmal. Wenn es wieder passiert, hilft die Serverkonsole weiter."}
          </p>
          {!forbidden && error.digest && <p className="mt-2 font-mono text-xs text-text-3">{error.digest}</p>}
          <div className="mt-6 flex justify-center gap-3">
            <ButtonLink href="/">Zu den Projekten</ButtonLink>
            {!forbidden && (
              <Button variant="ghost" onClick={reset}>
                Erneut versuchen
              </Button>
            )}
          </div>
          {forbidden && (
            <p className="mt-6 text-sm text-text-2">
              Falsche Rolle?{" "}
              <Link href="/workspaces" className="text-text hover:underline">
                Workspace wechseln
              </Link>
            </p>
          )}
        </GlassCard>
      </main>
    </div>
  );
}
