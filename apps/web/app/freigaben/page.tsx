import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { getRepo } from "@/lib/repo";
import { redirect } from "next/navigation";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { appBaseUrl } from "@/lib/auth/url";
import { FreigabenListe } from "./FreigabenListe";

export const dynamic = "force-dynamic";

export const metadata = { title: "Freigaben" };

/* Meine Freigaben: die verschickten Links, an einer Stelle.
 *
 * Der Link zu einer Freigabe steht beim Verschicken im Fenster. Wer ihn dort nicht kopiert oder
 * später verliert, hatte bisher keinen Weg zurück - es gab keine Stelle, an der ein verschickter
 * Link noch einmal auftaucht. Und den Link neu zu erzeugen hiesse, der gefragten Person eine
 * zweite Adresse zu schicken und die erste ins Leere laufen zu lassen.
 */
export default async function FreigabenPage() {
  const session = await requireSession();
  if (!can(session.role, "guest_approval.request")) redirect("/verboten?aktion=guest_approval.request");
  const freigaben = await getRepo().listFreigaben();
  const basis = await appBaseUrl();

  return (
    <PageShell width="wide">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Meine Freigaben</h1>
        <p className="mt-2 text-[15px] text-text-2">
          Jede Freigabe ist ein Paket von Clips mit einem Link. Wer ihn öffnet, sieht nur diese Clips
          und sagt zu jedem Ja, Nein oder „da stimmt etwas nicht“ — ohne Konto bei chopstr.
        </p>
      </div>

      {freigaben.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-text-2">
            Noch nichts verschickt. In der Clip-Liste eines Videos steht oben rechts
            „Zur Freigabe senden“.
          </p>
        </GlassCard>
      ) : (
        <FreigabenListe freigaben={freigaben} basis={basis} />
      )}
    </PageShell>
  );
}
