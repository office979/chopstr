import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { assignableRoles, can } from "@/lib/auth/permissions";
import { appBaseUrl } from "@/lib/auth/url";
import { SettingsShell } from "../SettingsShell";
import { MembersPanel } from "./MembersPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Mitglieder" };

export default async function MembersPage() {
  const session = await requireSession();
  const repo = getRepo();
  const canManage = can(session.role, "members.manage");
  const [members, invites, brands, baseUrl] = await Promise.all([
    repo.listMembers(),
    canManage ? repo.listInvites() : Promise.resolve([]),
    repo.listBrandProfiles(),
    appBaseUrl(),
  ]);

  return (
    <SettingsShell
      session={session}
      tab="mitglieder"
      title="Mitglieder"
      description={canManage ? "Lade Kolleginnen, Reviewer oder Kunden ein. Kunden sind immer an eine Marke gebunden." : "Wer in diesem Workspace arbeitet. Einladen dürfen Inhaber und Admins."}
    >
      <MembersPanel
        members={members}
        invites={invites}
        brands={brands.map((b) => ({ id: b.id, name: b.name }))}
        assignable={assignableRoles(session.role)}
        canManage={canManage}
        myUserId={session.userId}
        myRole={session.role}
        baseUrl={baseUrl}
      />
    </SettingsShell>
  );
}
