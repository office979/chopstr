import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, Select } from "@/components/ui/Field";
import { Button, ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requirePageRole } from "@/lib/session";
import { formatDateTime } from "@/lib/format";
import { AUDIT_PAGE_SIZE, auditQueryString, parseAuditQuery, toAuditFilter } from "@/lib/audit/query";
import { SettingsShell } from "../SettingsShell";

export const dynamic = "force-dynamic";
export const metadata = { title: "Audit-Log" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function payloadPreview(payload: Record<string, unknown> | null): string {
  if (!payload) return "";
  const text = JSON.stringify(payload);
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

export default async function AuditPage({ searchParams }: { searchParams: SearchParams }) {
  const session = await requirePageRole("audit.read");
  const q = parseAuditQuery(await searchParams);
  const repo = getRepo();
  const [page, actions, actors] = await Promise.all([repo.listAudit(toAuditFilter(q)), repo.listAuditActions(), repo.listAuditActors()]);
  const pages = Math.max(1, Math.ceil(page.total / AUDIT_PAGE_SIZE));
  const csvHref = `/api/audit.csv${auditQueryString({ ...q, page: 1 })}`;

  return (
    <SettingsShell
      session={session}
      tab="audit"
      title="Audit-Log"
      description="Jede Aktion mit Akteur, Zeitpunkt und Nutzlast. Löschnachweise und Rechtebestätigungen bleiben hier dauerhaft."
      actions={
        <ButtonLink href={csvHref} variant="ghost" size="sm">
          CSV exportieren
        </ButtonLink>
      }
    >
      <GlassCard padding="md" className="mb-5">
        <form method="get" className="grid gap-4 sm:grid-cols-[1fr_1fr_auto_auto_auto] sm:items-end">
          <Field label="Aktion" htmlFor="aktion">
            <Select id="aktion" name="aktion" defaultValue={q.action}>
              <option value="">Alle Aktionen</option>
              {actions.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Akteur" htmlFor="akteur">
            <Select id="akteur" name="akteur" defaultValue={q.actor}>
              <option value="">Alle Akteure</option>
              {actors.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Von" htmlFor="von">
            <Input id="von" name="von" type="date" defaultValue={q.from} />
          </Field>
          <Field label="Bis" htmlFor="bis">
            <Input id="bis" name="bis" type="date" defaultValue={q.to} />
          </Field>
          <div className="flex gap-2">
            <Button type="submit" size="sm" className="h-11">
              Filtern
            </Button>
            <ButtonLink href="/einstellungen/audit" variant="ghost" size="sm" className="h-11">
              Zurücksetzen
            </ButtonLink>
          </div>
        </form>
      </GlassCard>

      <GlassCard padding="none" className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 text-sm text-text-2">
          <span>
            {page.total.toLocaleString("de-AT")} {page.total === 1 ? "Eintrag" : "Einträge"}
          </span>
          <span>
            Seite {q.page} von {pages}
          </span>
        </div>
        {page.rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-text-2">Keine Einträge für diesen Filter.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-text-2">
                <tr>
                  <th className="px-5 py-3 font-medium">Zeitpunkt</th>
                  <th className="px-3 py-3 font-medium">Aktion</th>
                  <th className="px-3 py-3 font-medium">Akteur</th>
                  <th className="px-3 py-3 font-medium">Objekt</th>
                  <th className="px-3 py-3 font-medium">Nutzlast</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {page.rows.map((r) => (
                  <tr key={r.id} className="align-top">
                    <td className="whitespace-nowrap px-5 py-3 font-mono text-xs text-text-2">{formatDateTime(r.at)}</td>
                    <td className="px-3 py-3">
                      <Badge tone={/delete|removed|revoked|failed/.test(r.action) ? "attention" : "neutral"}>{r.action}</Badge>
                    </td>
                    <td className="px-3 py-3 text-text">
                      {r.actor_label ?? (r.actor_type === "system" ? "System" : r.actor_type === "guest" ? "Gast" : r.actor_id ?? "")}
                      {r.actor_type !== "user" && <span className="ml-1 text-xs text-text-2">({r.actor_type})</span>}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-text-2">
                      {r.entity ?? ""}
                      {r.entity_id ? ` ${r.entity_id.slice(0, 8)}` : ""}
                    </td>
                    <td className="max-w-[320px] px-3 py-3 font-mono text-xs text-text-2" title={r.payload ? JSON.stringify(r.payload, null, 2) : undefined}>
                      {payloadPreview(r.payload)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="flex items-center justify-between border-t border-line px-5 py-4 text-sm">
            {q.page > 1 ? (
              <Link href={`/einstellungen/audit${auditQueryString({ ...q, page: q.page - 1 })}`} className="text-text hover:underline">
                Neuere
              </Link>
            ) : (
              <span className="text-text-3">Neuere</span>
            )}
            {q.page < pages ? (
              <Link href={`/einstellungen/audit${auditQueryString({ ...q, page: q.page + 1 })}`} className="text-text hover:underline">
                Ältere
              </Link>
            ) : (
              <span className="text-text-3">Ältere</span>
            )}
          </div>
        )}
      </GlassCard>
    </SettingsShell>
  );
}
