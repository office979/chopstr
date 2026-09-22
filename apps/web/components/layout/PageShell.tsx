import type { ReactNode } from "react";
import Link from "next/link";
import { PillNav, type NavUser } from "@/components/ui/PillNav";
import { LightCone } from "@/components/ui/LightCone";
import { BackgroundWord } from "@/components/ui/BackgroundWord";
import { cn } from "@/components/ui/cn";
import { getAuthUser, getSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { getRepo } from "@/lib/repo";
import { formatDate } from "@/lib/format";

interface PageShellProps {
  children: ReactNode;
  backgroundWord?: string;
  lightTone?: "brand" | "ai";
  width?: "narrow" | "default" | "wide";
  className?: string;
  /* Seite ist auch ohne aktiven Workspace erreichbar (/workspaces) */
  allowWithoutWorkspace?: boolean;
}

const widths = {
  narrow: "max-w-[760px]",
  default: "max-w-[1120px]",
  wide: "max-w-[1440px]",
};

/* Seitenrahmen: Hintergrundwort → Lichtkegel mit Körnung → Glas → Inhalt. Liest die Sitzung für die Navigation. */
export async function PageShell({ children, backgroundWord, lightTone = "brand", width = "default", className }: PageShellProps) {
  const [session, user] = await Promise.all([getSession(), getAuthUser()]);
  const navUser: NavUser | null = session
    ? {
        name: session.displayName,
        email: session.email,
        workspaceName: session.workspaceName,
        role: session.role,
        demo: session.demo,
        canUpload: can(session.role, "source.upload"),
        canBrand: can(session.role, "brand.edit"),
        canAudit: can(session.role, "audit.read"),
        canBilling: can(session.role, "billing.manage"),
      }
    : user
      ? { name: user.displayName, email: user.email, workspaceName: null, role: null, demo: user.demo, canUpload: false, canBrand: false, canAudit: false, canBilling: false }
      : null;

  /* Banner nur für owner/admin: AVV noch nicht angenommen, Workspace-Löschung eingeplant (Mensch muss prüfen) */
  let dpaBanner = false;
  let deletionBanner: string | null = null;
  if (session && (can(session.role, "dpa.accept") || can(session.role, "workspace.delete"))) {
    try {
      const ws = await getRepo().getWorkspace();
      dpaBanner = can(session.role, "dpa.accept") && !ws.dpa_signed_at;
      deletionBanner = ws.deletion_scheduled_for ? formatDate(ws.deletion_scheduled_for) : null;
    } catch {
      /* ohne Workspace kein Banner */
    }
  }

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <LightCone tone={lightTone} />
      {backgroundWord && <BackgroundWord word={backgroundWord} />}
      <PillNav user={navUser} />
      <main className={cn("relative z-10 mx-auto w-full px-4 pb-24 pt-28 sm:px-6 sm:pt-32", widths[width], className)}>
        {(dpaBanner || deletionBanner) && (
          <div className="print:hidden mb-6 flex flex-col gap-2">
            {deletionBanner && (
              <p role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-inner border border-attention/50 bg-attention/10 px-4 py-2.5 text-sm text-text">
                <span>
                  <span className="font-medium text-attention">Löschung des Workspace eingeplant</span> für {deletionBanner}. Bis dahin kannst du sie zurücknehmen.
                </span>
                <Link href="/einstellungen/loeschung" className="text-text underline-offset-4 hover:underline">
                  Zur Löschung
                </Link>
              </p>
            )}
            {dpaBanner && (
              <p role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-inner border border-attention/40 px-4 py-2.5 text-sm text-text-2">
                <span>
                  <span className="text-attention">Ein Vertrag fehlt noch.</span> Hochladen geht schon, zum Posten brauchst du ihn.
                </span>
                <Link href="/rechtliches/avv" className="text-text underline-offset-4 hover:underline">
                  Vertrag lesen und annehmen
                </Link>
              </p>
            )}
          </div>
        )}
        {children}
      </main>
      <footer className="relative z-10 mx-auto flex w-full max-w-[1120px] flex-wrap items-center justify-between gap-3 px-4 pb-8 text-xs text-text-3 sm:px-6">
        <span>chopstr · EU-verarbeitet · Mensch gibt frei</span>
        <span className="flex gap-4">
          <Link href="/rechtliches/avv" className="hover:text-text-2">
            Rechtliches
          </Link>
          <Link href="/einstellungen" className="hover:text-text-2">
            Workspace
          </Link>
          <span className="font-mono">v{process.env.APP_VERSION ?? "0.1.0"}</span>
        </span>
      </footer>
    </div>
  );
}
