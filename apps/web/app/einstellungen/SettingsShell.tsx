import type { ReactNode } from "react";
import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/components/ui/cn";
import type { Session } from "@/lib/session";
import { can, type Action } from "@/lib/auth/permissions";

export type SettingsTab = "allgemein" | "mitglieder" | "abrechnung" | "sicherheit" | "loeschung" | "audit" | "entwickler" | "api" | "webhooks" | "verbindungen";

/* Vorne nur, was ein Team wirklich pflegt. Alles Weitere liegt unter „Für Profis": aufgeklappt,
 * sobald man auf einer dieser Seiten ist, damit der aktive Reiter nie versteckt ist. */
const HAUPT: SettingsTab[] = ["allgemein", "mitglieder", "abrechnung"];

const TABS: { key: SettingsTab; href: string; label: string; action?: Action }[] = [
  { key: "allgemein", href: "/einstellungen", label: "Allgemein" },
  { key: "mitglieder", href: "/einstellungen/mitglieder", label: "Mitglieder" },
  { key: "abrechnung", href: "/einstellungen/abrechnung", label: "Abrechnung", action: "billing.manage" },
  { key: "sicherheit", href: "/einstellungen/sicherheit", label: "Sicherheit" },
  { key: "loeschung", href: "/einstellungen/loeschung", label: "Löschung" },
  { key: "audit", href: "/einstellungen/audit", label: "Audit-Log", action: "audit.read" },
  /* Phase 5: API-Schlüssel und Webhooks (5a), Plattform-Verbindungen (5b) */
  /* „Für Entwickler" lag als gleichrangiger Punkt in der Hauptnavigation. Hier steht es bei
   * allem anderen Technischen und bleibt für die, die es brauchen, einen Klick entfernt. */
  { key: "entwickler", href: "/entwickler", label: "Für Entwickler", action: "api.manage" },
  { key: "api", href: "/einstellungen/api", label: "API", action: "api.manage" },
  { key: "webhooks", href: "/einstellungen/webhooks", label: "Webhooks", action: "api.manage" },
  { key: "verbindungen", href: "/einstellungen/verbindungen", label: "Verbindungen", action: "api.manage" },
];

interface Props {
  session: Session;
  tab: SettingsTab;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /* Das Wort im Hintergrund. Standard ist „EU"; die Entwicklerseite behält ihr eigenes, damit die
   * Seite beim Wechsel in den Rahmen nicht anders aussieht als vorher. */
  backgroundWord?: string;
  lightTone?: "ai";
  children: ReactNode;
}

/* Rahmen der Workspace-Einstellungen mit Reitern. Block B ergänzt hier Abrechnung und Rechtliches.
 *
 * Alle Reiter teilen dieselbe Breite. Vorher setzten Abrechnung, Audit-Log, Löschung, Webhooks und
 * Verbindungen "default", der Rest blieb auf "narrow"; beim Reiterwechsel sprang das Layout. */
export function SettingsShell({ session, tab, title, description, actions, backgroundWord = "EU", lightTone, children }: Props) {
  const tabs = TABS.filter((t) => !t.action || can(session.role, t.action));
  const haupt = tabs.filter((t) => HAUPT.includes(t.key));
  const profi = tabs.filter((t) => !HAUPT.includes(t.key));
  const profiAktiv = profi.some((t) => t.key === tab);
  const reiter = (t: (typeof TABS)[number]) => (
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
  );
  return (
    <PageShell width="default" backgroundWord={backgroundWord} lightTone={lightTone}>
      <PageHeader eyebrow={`Team · ${session.workspaceName}`} title={title} description={description} actions={actions} />
      <nav aria-label="Einstellungen" className="mb-6 flex flex-col gap-2">
        <div className="flex flex-wrap gap-1">{haupt.map((t) => reiter(t))}</div>
        {profi.length > 0 && (
          <details open={profiAktiv} className="group">
            <summary className="transition-soft cursor-pointer py-1 text-sm text-text-2 underline underline-offset-4 hover:text-text">
              Für Profis
            </summary>
            <div className="mt-2 flex flex-wrap gap-1">{profi.map((t) => reiter(t))}</div>
          </details>
        )}
      </nav>
      {children}
    </PageShell>
  );
}
