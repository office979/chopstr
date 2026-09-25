import type { ReactNode } from "react";
import Link from "next/link";
import { Sidebar, type NavUser } from "@/components/layout/Sidebar";
import { BlueBubbles } from "@/components/ui/BlueBubbles";
import { cn } from "@/components/ui/cn";
import { getAuthUser, getSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { getRepo } from "@/lib/repo";
import { formatDate } from "@/lib/format";

interface PageShellProps {
  children: ReactNode;
  /* Veraltet: das Hintergrundwort ist mit der Seitenleiste entfallen, der Prop bleibt für bestehende Aufrufe */
  backgroundWord?: string;
  lightTone?: "brand" | "ai";
  width?: "narrow" | "default" | "wide" | "arbeit";
  className?: string;
  /* Seite ist auch ohne aktiven Workspace erreichbar (/workspaces) */
  allowWithoutWorkspace?: boolean;
}

const widths = {
  narrow: "max-w-[760px]",
  default: "max-w-[1120px]",
  wide: "max-w-[1440px]",
  /* Arbeitsseiten, die nebeneinander arbeiten: die Clip-Ansicht hat links ein festes Video und
   * rechts eine Arbeitsfläche. Bei 1440 Pixeln Deckel blieb auf einem breiten Bildschirm rechts
   * eine leere Hälfte, während die Timeline sich quetschte. Hier wächst die Arbeitsfläche mit,
   * bis 1920 - darüber werden Zeilen zu lang zum Lesen. */
  arbeit: "max-w-[1920px]",
};

/* Seitenrahmen: blaue Blasen → Seitenleiste links → Inhalt. Liest die Sitzung für die Navigation. */
export async function PageShell({ children, lightTone = "brand", width = "default", className }: PageShellProps) {
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

  /* Nur die geplante Workspace-Löschung steht hier: sie betrifft alles und läuft ab.
   *
   * Der Vertragshinweis (AVV) stand früher ebenfalls hier und damit über jeder Seite, dauerhaft und
   * nie erledigt. Er hat Nutzer darauf trainiert, orange zu übersehen, und entwertete damit die
   * Hinweise, bei denen wirklich etwas zu tun ist (docs/BEDIENKONZEPT.md, Abschnitt 7). Er erscheint
   * jetzt an den zwei Stellen, an denen er Folgen hat: als Karte auf der Startseite und als Punkt in
   * der Liste „Noch nicht bereit zum Posten“ am Clip. */
  let deletionBanner: string | null = null;
  if (session && can(session.role, "workspace.delete")) {
    try {
      const ws = await getRepo().getWorkspace();
      deletionBanner = ws.deletion_scheduled_for ? formatDate(ws.deletion_scheduled_for) : null;
    } catch {
      /* ohne Workspace kein Banner */
    }
  }

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <BlueBubbles tone={lightTone} />
      <Sidebar user={navUser} />
      {/* Platz für die Leiste: 64 für die schmale Schiene, 264 für die volle. Unter sm gibt es
          keine Leiste, sondern die Kopfzeile mit dem Menüknopf. */}
      <div className="relative z-10 flex min-h-dvh flex-col sm:pl-[64px] lg:pl-[264px]">
        <main className={cn("mx-auto w-full flex-1 px-4 pb-16 pt-8 sm:px-8 lg:pt-12", widths[width], className)}>
          {deletionBanner && (
            <div className="print:hidden mb-6">
              <p role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-inner border border-attention/50 bg-attention/10 px-4 py-2.5 text-sm text-text">
                <span>
                  <span className="font-medium text-attention">Löschung des Teams eingeplant</span> für {deletionBanner}. Bis dahin kannst du sie zurücknehmen.
                </span>
                <Link href="/einstellungen/loeschung" className="text-text underline-offset-4 hover:underline">
                  Zur Löschung
                </Link>
              </p>
            </div>
          )}
          {children}
        </main>
        <footer className="mx-auto flex w-full max-w-[1440px] items-center justify-between gap-3 px-4 pb-6 text-xs text-text-3 sm:px-8 print:hidden">
          <span>chopstr · EU-verarbeitet</span>
          <span className="font-mono">v{process.env.APP_VERSION ?? "0.1.0"}</span>
        </footer>
      </div>
    </div>
  );
}
