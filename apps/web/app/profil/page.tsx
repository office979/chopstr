import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { requireSession } from "@/lib/session";
import { ROLE_LABELS } from "@/lib/auth/permissions";
import { ProfileForm } from "./ProfileForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Profil" };

export default async function ProfilePage() {
  const session = await requireSession();
  return (
    <PageShell width="narrow" backgroundWord="Profil">
      <PageHeader
        eyebrow="Konto"
        title={session.displayName}
        description={`${session.email} · ${ROLE_LABELS[session.role]} in ${session.workspaceName}`}
      />
      <ProfileForm
        displayName={session.displayName}
        email={session.email}
        emailVerified={session.emailVerified}
        locale={session.locale}
        demo={session.demo}
      />
    </PageShell>
  );
}
