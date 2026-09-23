import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ConfirmForm } from "@/components/ui/ConfirmForm";
import { getRepo } from "@/lib/repo";
import { getSession, requireAuthUser } from "@/lib/session";
import { ROLE_LABELS } from "@/lib/auth/permissions";
import { switchWorkspaceAction } from "./actions";

export const dynamic = "force-dynamic";
export const metadata = { title: "Teams" };

export default async function WorkspacesPage() {
  const me = await requireAuthUser();
  const [memberships, session] = await Promise.all([getRepo().listMemberships(me.userId), getSession()]);

  return (
    <PageShell width="narrow" backgroundWord="Team" allowWithoutWorkspace>
      <PageHeader
        eyebrow="Konto"
        title="Deine Teams"
        description="Jede Mitgliedschaft hat ihre eigene Rolle. Der Wechsel gilt für diese Sitzung."
      />
      {memberships.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Du bist in keinem Team</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Bitte jemanden um eine Einladung oder leg dein eigenes Team an.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/registrieren" className="text-text hover:underline">
              Team anlegen
            </Link>
          </div>
        </GlassCard>
      ) : (
        <ul className="grid gap-4">
          {memberships.map((m) => {
            const active = session?.workspaceId === m.workspace_id;
            return (
              <li key={m.workspace_id}>
                <GlassCard padding="lg" selected={active} className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="truncate text-lg font-medium text-text">{m.workspace_name}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-2">
                      <span className="font-mono">{m.workspace_slug}</span>
                      <Badge>{ROLE_LABELS[m.role]}</Badge>
                      {active && <Badge tone="ok">Aktiv</Badge>}
                    </p>
                  </div>
                  {!active && (
                    <ConfirmForm action={switchWorkspaceAction} label="Wechseln" pendingLabel="Wird gewechselt" hidden={{ workspace_id: m.workspace_id }} variant="ghost" />
                  )}
                </GlassCard>
              </li>
            );
          })}
        </ul>
      )}
    </PageShell>
  );
}
