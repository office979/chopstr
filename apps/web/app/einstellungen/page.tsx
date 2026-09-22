import { GlassCard } from "@/components/ui/GlassCard";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { formatDate } from "@/lib/format";
import { getQuota, formatHours } from "@/lib/billing/quota";
import { SettingsShell } from "./SettingsShell";
import { GeneralForm } from "./GeneralForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Workspace" };

function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1 border-b border-line py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <dt className="text-sm text-text-2">{label}</dt>
      <dd className={mono ? "font-mono text-sm text-text" : "text-[15px] text-text"}>{value}</dd>
    </div>
  );
}

export default async function SettingsPage() {
  const session = await requireSession();
  const repo = getRepo();
  const [ws, quota] = await Promise.all([repo.getWorkspace(), getQuota(repo)]);
  const editable = can(session.role, "workspace.update");

  return (
    <SettingsShell session={session} tab="allgemein" title="Einstellungen" description="Name, Region und Aufbewahrung des Workspaces. Tarif und Slug sind fest.">
      <div className="flex flex-col gap-5">
        <GeneralForm workspace={ws} planName={quota.plan?.name ?? ws.plan} editable={editable} />
        <GlassCard padding="lg">
          <h2 className="mb-2 text-lg font-medium">Kontingent und Datenschutz</h2>
          <dl>
            <Row
              label="Stunden Quellmaterial diesen Monat"
              value={`${formatHours(quota.used_minutes)} von ${formatHours(quota.included_minutes)} h${quota.allow_overage ? " (Mehrverbrauch erlaubt)" : ""}`}
            />
            <Row label="Abo-Status" value={quota.subscription ? quota.subscription.status : "kein Abo"} mono />
            <Row label="US-Subprozessoren erlaubt" value={ws.allow_us_subprocessors ? "ja" : "nein"} />
            <Row label="Training mit Kundendaten" value={ws.training_opt_in ? "an" : "aus"} />
            <Row label="AV-Vertrag angenommen" value={ws.dpa_signed_at ? formatDate(ws.dpa_signed_at) : "noch nicht"} />
            <Row label="Workspace-ID" value={ws.id} mono />
          </dl>
        </GlassCard>
        <p className="text-sm text-text-2">
          Videos liegen nie in der Datenbank, nur im EU-Objektspeicher. Nach Ablauf der Aufbewahrung werden Quellen automatisch gelöscht, der Löschnachweis bleibt im Audit-Log.
        </p>
      </div>
    </SettingsShell>
  );
}
