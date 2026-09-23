import Link from "next/link";
import { AuthShell } from "@/components/layout/AuthShell";
import { ConfirmForm } from "@/components/ui/ConfirmForm";
import { Badge } from "@/components/ui/Badge";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { getAuthUser } from "@/lib/session";
import { ROLE_LABELS } from "@/lib/auth/permissions";
import { formatDate } from "@/lib/format";
import { acceptInviteAction } from "./actions";
import { InviteRegisterForm } from "./InviteRegisterForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Einladung" };

function isExpired(expiresAt: string): boolean {
  return Date.parse(expiresAt) <= Date.now();
}

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const demo = isDemoMode();
  const repo = getRepo();
  const [invite, me] = await Promise.all([repo.getInvite(token), getAuthUser()]);
  const expired = invite ? isExpired(invite.expires_at) : false;
  const usable = invite && !invite.accepted_at && !expired;

  const footer = me ? (
    <span>
      Angemeldet als {me.email}.{" "}
      <Link href="/workspaces" className="text-text hover:underline">
        Deine Teams
      </Link>
    </span>
  ) : (
    <>
      <span>Schon ein Konto?</span>
      <Link href={`/anmelden?next=${encodeURIComponent(`/einladung/${token}`)}`} className="text-text hover:underline">
        Anmelden und annehmen
      </Link>
    </>
  );

  if (!invite) {
    return (
      <AuthShell title="Einladung nicht gefunden" description="Der Link ist ungültig oder die Einladung wurde zurückgezogen." backgroundWord="Team" demo={demo} footer={footer}>
        <p className="text-sm text-text-2">Bitte die Person, die dich eingeladen hat, um einen neuen Link.</p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={`Einladung zu ${invite.workspace_name}`}
      description={`${invite.invited_by_name ?? "Ein Mitglied"} lädt dich als ${ROLE_LABELS[invite.role]} ein.`}
      backgroundWord="Team"
      demo={demo}
      footer={footer}
    >
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-text-2">E-Mail</dt>
          <dd className="text-text">{invite.email}</dd>
        </div>
        <div>
          <dt className="text-text-2">Rolle</dt>
          <dd className="flex items-center gap-2 text-text">
            <Badge>{ROLE_LABELS[invite.role]}</Badge>
            {invite.brand_profile_name && <span className="text-text-2">Marke {invite.brand_profile_name}</span>}
          </dd>
        </div>
        <div>
          <dt className="text-text-2">Gültig bis</dt>
          <dd className="text-text">{formatDate(invite.expires_at)}</dd>
        </div>
      </dl>

      {!usable ? (
        <p className="text-sm text-attention" role="alert">
          {invite.accepted_at ? "Diese Einladung wurde bereits angenommen." : "Diese Einladung ist abgelaufen."}
        </p>
      ) : me ? (
        <div className="flex flex-col gap-3">
          {me.email.toLowerCase() !== invite.email.toLowerCase() && (
            <p className="text-sm text-text-2">
              Die Einladung ging an {invite.email}, du bist als {me.email} angemeldet. Du kannst sie trotzdem mit diesem Konto annehmen.
            </p>
          )}
          <ConfirmForm action={acceptInviteAction} label="Einladung annehmen" pendingLabel="Wird angenommen" hidden={{ token }} />
        </div>
      ) : (
        <InviteRegisterForm token={token} email={invite.email} demo={demo} />
      )}
    </AuthShell>
  );
}
