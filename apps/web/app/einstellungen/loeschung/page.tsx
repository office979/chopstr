import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { formatDateTime } from "@/lib/format";
import type { DeletionJob } from "@/lib/repo/types";
import { SettingsShell } from "../SettingsShell";
import { WorkspaceDeletionCard } from "./WorkspaceDeletionCard";

export const dynamic = "force-dynamic";
export const metadata = { title: "Löschung und Export" };

const ENTITY_LABELS: Record<DeletionJob["entity"], string> = { source: "Quelle", clip: "Clip", brand_profile: "Markenprofil", workspace: "Workspace" };
const REASON_LABELS: Record<DeletionJob["reason"], string> = { user_request: "Nutzeranfrage", retention: "Löschfrist", workspace_deleted: "Workspace gelöscht", gdpr_request: "DSGVO-Anfrage" };
const STATUS: Record<DeletionJob["status"], { label: string; tone: "neutral" | "attention" | "ok" | "ai" | "danger" }> = {
  queued: { label: "Eingeplant", tone: "attention" },
  running: { label: "Läuft", tone: "ai" },
  done: { label: "Gelöscht", tone: "ok" },
  failed: { label: "Fehlgeschlagen", tone: "danger" },
};

function rowsSummary(rows: Record<string, number>): string {
  const entries = Object.entries(rows).filter(([, n]) => n > 0);
  if (entries.length === 0) return "keine Zeilen";
  return entries.map(([t, n]) => `${t} ${n}`).join(", ");
}

export default async function DeletionPage() {
  const session = await requireSession();
  const repo = getRepo();
  const [jobs, workspace] = await Promise.all([repo.listDeletionJobs(), repo.getWorkspace()]);
  const canExport = can(session.role, "export.read");
  const canDeleteWorkspace = can(session.role, "workspace.delete");

  return (
    <SettingsShell
      session={session}
      tab="loeschung"
      title="Löschung und Export"
      description="Jede Löschung hinterlässt einen Nachweis: welche Objektspeicher-Keys und welche Zeilen entfernt wurden."
      width="default"
    >
      <div className="flex flex-col gap-5">
        {canExport && (
          <GlassCard padding="lg" className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-medium">Datenexport</h2>
              <p className="mt-1 max-w-xl text-sm text-text-2">
                ZIP mit einer JSON-Datei je Tabelle deines Workspace (Art. 15 und 20 DSGVO) und der Liste aller Medien-Keys. Videos liegen im Objektspeicher und sind nicht enthalten.
              </p>
            </div>
            <ButtonLink href="/api/export" prefetch={false}>
              Export herunterladen
            </ButtonLink>
          </GlassCard>
        )}

        <WorkspaceDeletionCard workspace={workspace} canDelete={canDeleteWorkspace} demo={session.demo} />

        <GlassCard padding="none" className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
            <div>
              <h2 className="text-lg font-medium">Lösch-Aufträge</h2>
              <p className="mt-1 text-sm text-text-2">Eingeplante Aufträge führt der Worker aus, spätestens im täglichen Retention-Lauf um 03:00 Uhr.</p>
            </div>
            <span className="text-sm text-text-2">{jobs.length} {jobs.length === 1 ? "Auftrag" : "Aufträge"}</span>
          </div>
          {jobs.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-text-2">Noch keine Löschung angefordert.</p>
          ) : (
            <ul className="divide-y divide-line">
              {jobs.map((j) => {
                const st = STATUS[j.status];
                return (
                  <li key={j.id} className="flex flex-col gap-2 px-5 py-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={st.tone}>{st.label}</Badge>
                      <span className="font-medium text-text">
                        {ENTITY_LABELS[j.entity]}
                        {j.entity_label ? `: ${j.entity_label}` : ""}
                      </span>
                      <span className="font-mono text-xs text-text-3">{j.entity_id.slice(0, 8)}</span>
                    </div>
                    <p className="text-sm text-text-2">
                      {REASON_LABELS[j.reason]}
                      {j.requested_by_label ? ` durch ${j.requested_by_label}` : ""} · angefordert {formatDateTime(j.requested_at)}
                      {j.finished_at ? ` · abgeschlossen ${formatDateTime(j.finished_at)}` : j.status === "queued" ? " · Nachweis folgt" : ""}
                    </p>
                    {j.status === "done" && (
                      <details className="text-sm">
                        <summary className="cursor-pointer text-text-2 hover:text-text">
                          Nachweis: {j.keys_deleted.length} {j.keys_deleted.length === 1 ? "Objekt" : "Objekte"}, {rowsSummary(j.rows_deleted)}
                        </summary>
                        <div className="mt-2 flex flex-col gap-1 rounded-inner border border-line p-3 font-mono text-xs text-text-2">
                          {j.keys_deleted.length === 0 && <span>Keine Objektspeicher-Keys.</span>}
                          {j.keys_deleted.map((k, i) => (
                            <span key={`${k.key}-${i}`} className="break-all">
                              {k.bucket ? `${k.bucket}/` : ""}
                              {k.key}
                              {k.existed === false ? " (war schon weg)" : ""}
                              {k.deleted_at ? ` · ${formatDateTime(k.deleted_at)}` : ""}
                            </span>
                          ))}
                          <span className="mt-1 text-text">Zeilen: {JSON.stringify(j.rows_deleted)}</span>
                          <span className="text-text-3">Auftrag {j.id}</span>
                        </div>
                      </details>
                    )}
                    {j.status === "failed" && j.error && <p className="text-sm text-attention">{j.error}</p>}
                  </li>
                );
              })}
            </ul>
          )}
        </GlassCard>
      </div>
    </SettingsShell>
  );
}
