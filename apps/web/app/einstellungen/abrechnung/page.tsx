import { getRepo } from "@/lib/repo";
import { requirePageRole } from "@/lib/session";
import { getQuota } from "@/lib/billing/quota";
import { billingProviderKind } from "@/lib/billing/provider";
import { SettingsShell } from "../SettingsShell";
import { BillingPanel } from "./BillingPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Abrechnung" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function BillingPage({ searchParams }: { searchParams: SearchParams }) {
  const session = await requirePageRole("billing.manage");
  const q = await searchParams;
  const repo = getRepo();
  const [quota, plans, history, workspace] = await Promise.all([getQuota(repo), repo.listPlans(), repo.listUsageHistory(), repo.getWorkspace()]);
  const checkout = typeof q.checkout === "string" ? q.checkout : null;
  const portal = typeof q.portal === "string" ? q.portal : null;
  const notice =
    checkout === "erfolg"
      ? "Zahlung bei Stripe abgeschlossen. Der Tarif wird aktualisiert, sobald der Webhook eintrifft."
      : checkout === "abbruch"
        ? "Checkout abgebrochen. Dein Tarif bleibt unverändert."
        : portal === "keins"
          ? "Für dieses Abo gibt es kein Kundenportal (kein Stripe-Kunde)."
          : portal === "fehler"
            ? "Das Kundenportal ist gerade nicht erreichbar."
            : null;

  return (
    <SettingsShell
      session={session}
      tab="abrechnung"
      title="Abrechnung"
      description="Abgerechnet werden Stunden Quellmaterial pro Monat. Kein Credit-System, keine versteckten Kosten."
    >
      <BillingPanel
        provider={billingProviderKind()}
        subscription={quota.subscription}
        plan={quota.plan}
        plans={plans}
        usage={quota.usage}
        history={history}
        workspaceName={workspace.name}
        workspaceTier={workspace.tier}
        notice={notice}
        demo={session.demo}
      />
    </SettingsShell>
  );
}
