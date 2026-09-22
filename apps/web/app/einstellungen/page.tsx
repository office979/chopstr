import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getRepo } from "@/lib/repo";
import { formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Workspace" };

function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1 border-b border-line py-4 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <dt className="text-sm text-text-2">{label}</dt>
      <dd className={mono ? "font-mono text-sm text-text" : "text-[15px] text-text"}>{value}</dd>
    </div>
  );
}

export default async function SettingsPage() {
  const repo = getRepo();
  const ws = await repo.getWorkspace();

  return (
    <PageShell width="narrow" backgroundWord="EU">
      <PageHeader
        eyebrow="Workspace"
        title={ws.name}
        description="Diese Einstellungen sind nur lesbar. Änderungen an Tarif, Region und Aufbewahrung kommen in Phase 4 mit Rollen und Rechten."
      />
      <GlassCard padding="lg">
        <dl>
          <Row
            label="Tarif"
            value={
              <span className="flex items-center gap-2">
                <span>{ws.tier === "sovereign" ? "Sovereign" : "Standard"}</span>
                <Badge>{ws.plan}</Badge>
              </span>
            }
          />
          <Row label="Datenregion" value={ws.data_region} mono />
          <Row label="Aufbewahrung Quellmaterial" value={`${ws.retention_days} Tage`} />
          <Row label="Aufbewahrung Renders" value={`${ws.render_retention_days} Tage`} />
          <Row label="US-Subprozessoren erlaubt" value={ws.allow_us_subprocessors ? "ja" : "nein"} />
          <Row label="Training mit Kundendaten" value={ws.training_opt_in ? "an" : "aus"} />
          <Row label="AV-Vertrag unterzeichnet" value={ws.dpa_signed_at ? formatDate(ws.dpa_signed_at) : "noch nicht"} />
          <Row label="Workspace-ID" value={ws.id} mono />
        </dl>
      </GlassCard>
      <p className="mt-6 text-sm text-text-2">
        Videos liegen nie in der Datenbank, nur im EU-Objektspeicher. Nach Ablauf der Aufbewahrung werden Quellen automatisch gelöscht, der Löschnachweis bleibt im Audit-Log.
      </p>
    </PageShell>
  );
}
