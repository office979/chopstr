import type { ReactNode } from "react";
import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/components/ui/cn";
import type { Session } from "@/lib/session";
import { can, type Action } from "@/lib/auth/permissions";

export type SettingsTab = "allgemein" | "mitglieder" | "abrechnung" | "sicherheit" | "loeschung" | "audit";

const TABS: { key: SettingsTab; href: string; label: string; action?: Action }[] = [
  { key: "allgemein", href: "/einstellungen", label: "Allgemein" },
  { key: "mitglieder", href: "/einstellungen/mitglieder", label: "Mitglieder" },
  { key: "abrechnung", href: "/einstellungen/abrechnung", label: "Abrechnung", action: "billing.manage" },
  { key: "sicherheit", href: "/einstellungen/sicherheit", label: "Sicherheit" },
  { key: "loeschung", href: "/einstellungen/loeschung", label: "Löschung" },
  { key: "audit", href: "/einstellungen/audit", label: "Audit-Log", action: "audit.read" },
];

interface Props {
  session: Session;
  tab: SettingsTab;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  width?: "narrow" | "default" | "wide";
  children: ReactNode;
}

/* Rahmen der Workspace-Einstellungen mit Reitern. Block B ergänzt hier Abrechnung und Rechtliches. */
export function SettingsShell({ session, tab, title, description, actions, width = "narrow", children }: Props) {
  const tabs = TABS.filter((t) => !t.action || can(session.role, t.action));
  return (
    <PageShell width={width} backgroundWord="EU">
      <PageHeader eyebrow={`Workspace · ${session.workspaceName}`} title={title} description={description} actions={actions} />
      <nav aria-label="Einstellungen" className="mb-6 flex flex-wrap gap-1">
        {tabs.map((t) => (
          <Link
            key={t.key}
            href={t.href}
            aria-current={t.key === tab ? "page" : undefined}
            className={cn(
              "transition-soft rounded-pill border px-4 py-2 text-sm font-medium",
              t.key === tab ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong hover:text-text",
            )}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {children}
    </PageShell>
  );
}
