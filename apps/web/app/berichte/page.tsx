import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireSession } from "@/lib/session";
import { canExt } from "@/lib/auth/permissions-publishing";
import { formatDate, formatDateTime } from "@/lib/format";
import type { WeeklyReportClipEntry } from "@/lib/repo/types-publishing";
import { ReportSettings } from "./ReportSettings";

export const dynamic = "force-dynamic";
export const metadata = { title: "Berichte" };

function Entry({ e, tone }: { e: WeeklyReportClipEntry; tone: "ok" | "attention" }) {
  return (
    <li className="rounded-inner border border-line p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{e.title ?? `Clip ${e.clip_id.slice(0, 8)}`}</span>
        <span className="flex items-center gap-2">
          {e.platform && <Badge className="h-6 px-2.5 text-[11px]">{e.platform}</Badge>}
          <Badge tone={tone} className="h-6 px-2.5 font-mono text-[11px]">
            {e.follows_per_1k != null ? `${e.follows_per_1k.toLocaleString("de-AT", { maximumFractionDigits: 2 })} Folgen / 1.000` : "keine Folgequote"}
          </Badge>
        </span>
      </div>
      {e.views != null && <p className="mt-1 font-mono text-xs text-text-3">{e.views.toLocaleString("de-AT")} Views</p>}
      {e.cause && (
        <p className="mt-2 text-text-2">
          <span className="text-text">Ursache:</span> {e.cause}
        </p>
      )}
      {e.change && (
        <p className="mt-1 text-text-2">
          <span className="text-text">Änderung:</span> {e.change}
        </p>
      )}
    </li>
  );
}

/* Wochenberichte des Workspace: 3 beste und 3 schwächste Clips nach Folgequote mit Ursache und Änderung */
export default async function ReportsPage() {
  const session = await requireSession();
  const pub = getPublishingRepo();
  const [reports, enabled] = await Promise.all([pub.listWeeklyReports(), pub.getWeeklyReportEnabled()]);
  const canManage = canExt(session.role, "publishing.manage");

  return (
    <PageShell width="default" backgroundWord="Woche">
      <PageHeader eyebrow={`Workspace · ${session.workspaceName}`} title="Berichte" description="Jeden Montag: drei beste und drei schwächste Clips nach Folgequote, je eine Ursache und eine Änderung." />
      <GlassCard padding="md" className="mb-5">
        <ReportSettings enabled={enabled} canManage={canManage} />
      </GlassCard>
      {reports.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch kein Bericht</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Der erste Wochenbericht entsteht am Montag nach der ersten Publikation mit Metriken.{" "}
            <Link href="/serien" className="text-text underline-offset-4 hover:underline">
              Serien
            </Link>{" "}
            und{" "}
            <Link href="/experimente" className="text-text underline-offset-4 hover:underline">
              Experimente
            </Link>{" "}
            liefern die Daten dafür.
          </p>
        </GlassCard>
      ) : (
        <ul className="flex flex-col gap-5">
          {reports.map((r) => (
            <li key={r.id}>
              <GlassCard padding="lg">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-lg font-medium">Woche ab {formatDate(r.week_start)}</h2>
                  <p className="text-xs text-text-2">
                    {r.report.publications != null ? `${r.report.publications} Publikationen · ` : ""}
                    {r.sent_at ? `versendet ${formatDateTime(r.sent_at)}` : "nicht versendet"}
                  </p>
                </div>
                {r.report.summary && <p className="mt-2 text-sm text-text-2">{r.report.summary}</p>}
                <div className="mt-4 grid gap-5 md:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-sm font-medium">Beste Clips</h3>
                    {(r.report.best ?? []).length === 0 ? <p className="text-sm text-text-2">Keine Daten.</p> : <ul className="flex flex-col gap-2">{(r.report.best ?? []).map((e) => <Entry key={e.clip_id} e={e} tone="ok" />)}</ul>}
                  </div>
                  <div>
                    <h3 className="mb-2 text-sm font-medium">Schwächste Clips</h3>
                    {(r.report.worst ?? []).length === 0 ? <p className="text-sm text-text-2">Keine Daten.</p> : <ul className="flex flex-col gap-2">{(r.report.worst ?? []).map((e) => <Entry key={e.clip_id} e={e} tone="attention" />)}</ul>}
                  </div>
                </div>
              </GlassCard>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}
