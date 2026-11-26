import { GlassCard } from "@/components/ui/GlassCard";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { formatDate } from "@/lib/format";
import { getQuota, formatHours } from "@/lib/billing/quota";
import { SettingsShell } from "./SettingsShell";
import { GeneralForm } from "./GeneralForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Team" };

function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1 border-b border-line py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <dt className="text-sm text-text-2">{label}</dt>
      <dd className={mono ? "font-mono text-sm text-text" : "text-[15px] text-text"}>{value}</dd>
    </div>
  );
}

/* Stripe meldet den Status auf Englisch („trialing"). Hier steht, was er für das Team heisst. */
const ABO_STATUS: Record<string, string> = {
  trialing: "Testphase",
  active: "Aktiv",
  past_due: "Zahlung offen",
  unpaid: "Unbezahlt",
  canceled: "Gekündigt",
  incomplete: "Noch nicht abgeschlossen",
  incomplete_expired: "Abgelaufen",
  paused: "Pausiert",
};
function aboStatus(status: string): string {
  return ABO_STATUS[status] ?? status;
}

export default async function SettingsPage() {
  const session = await requireSession();
  const repo = getRepo();
  const [ws, quota] = await Promise.all([repo.getWorkspace(), getQuota(repo)]);
  const editable = can(session.role, "workspace.update");

  return (
    <SettingsShell session={session} tab="allgemein" title="Einstellungen" description="Name und Aufbewahrung deines Teams.">
      <div className="flex flex-col gap-5">
        <GeneralForm workspace={ws} planName={quota.plan?.name ?? ws.plan} editable={editable} />
        <GlassCard padding="lg">
          <h2 className="mb-2 text-lg font-medium">Kontingent und Datenschutz</h2>
          <dl>
            <Row
              label="Stunden Quellmaterial diesen Monat"
              value={`${formatHours(quota.used_minutes)} von ${formatHours(quota.included_minutes)} h${quota.allow_overage ? " (Mehrverbrauch erlaubt)" : ""}`}
            />
            <Row label="Abo" value={quota.subscription ? aboStatus(quota.subscription.status) : "kein Abo"} />
            <Row label="US-Subprozessoren erlaubt" value={ws.allow_us_subprocessors ? "ja" : "nein"} />
            <Row label="Training mit Kundendaten" value={ws.training_opt_in ? "an" : "aus"} />
            <Row label="AV-Vertrag angenommen" value={ws.dpa_signed_at ? formatDate(ws.dpa_signed_at) : "noch nicht"} />
          </dl>
          <details className="mt-3">
            <summary className="transition-soft cursor-pointer text-sm text-text-2 underline underline-offset-4 hover:text-text">
              Team-ID für den Support
            </summary>
            <p className="mt-2 font-mono text-sm text-text">{ws.id}</p>
          </details>
        </GlassCard>
        <p className="text-sm text-text-2">
          Videos liegen nie in der Datenbank, nur im EU-Objektspeicher. Nach Ablauf der Aufbewahrung werden Quellen automatisch gelöscht, der Löschnachweis bleibt im Audit-Log.
        </p>
      </div>
    </SettingsShell>
  );
}
