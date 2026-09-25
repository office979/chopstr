import Link from "next/link";
import { Wordmark } from "@/components/brand/Wordmark";
import { BlueBubbles } from "@/components/ui/BlueBubbles";
import { GlassCard } from "@/components/ui/GlassCard";
import { getRepo } from "@/lib/repo";
import { isTokenShape } from "@/lib/auth/tokens";
import { guestMediaUrl } from "@/lib/clips/labels";
import { isLocalMedia } from "@/lib/env";
import { isExpired } from "@/lib/guest/approval";
import { GuestDecision } from "./GuestDecision";

export const dynamic = "force-dynamic";
export const metadata = { title: "Freigabe", robots: { index: false, follow: false } };

/* Öffentliche Freigabeseite (PHASE4.md, Abschnitt 4): kein Login, das Token ist das Geheimnis.
 *
 * Zwei Arten von Token landen hier. Ein PAKET-Token (Migration 0016) zeigt mehrere Clips unter
 * einem Link - das ist der Regelfall, seit einmal gefragt wird statt je Clip. Ein CLIP-Token ist
 * eine Einzelfreigabe aus der Zeit davor; die gibt es noch, also bleibt sie gültig.
 *
 * Entschieden wird in beiden Fällen JE CLIP, und zwar über das Token dieses Clips. Die
 * Entscheidungs-Route bleibt deshalb unverändert. */
export default async function GuestApprovalPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const repo = getRepo();
  const paket = isTokenShape(token) ? await repo.getFreigabeByToken(token) : null;
  const einzeln = paket ? null : isTokenShape(token) ? await repo.getGuestApprovalByToken(token) : null;
  const eintraege = paket ? paket.eintraege : einzeln ? [einzeln] : [];
  for (const e of eintraege) {
    if (!e.approval.viewed_at) await repo.markGuestApprovalViewed(e.approval.token);
  }
  const workspaceName = paket?.workspace_name ?? einzeln?.workspace_name ?? "";
  const base = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <BlueBubbles />
      <main className="relative z-10 mx-auto flex w-full max-w-[960px] flex-col px-4 pb-16 pt-10 sm:px-6 sm:pt-16">
        <div className="mb-8 flex items-center justify-between gap-4">
          <Link href="/" aria-label="chopstr" className="inline-flex">
            <Wordmark width={128} className="opacity-95" />
          </Link>
          {eintraege.length > 0 && <span className="text-xs text-text-3">Freigabe für {workspaceName}</span>}
        </div>

        {eintraege.length === 0 ? (
          <GlassCard padding="lg" className="text-center">
            <p className="text-lg font-medium">Link ungültig</p>
            <p className="mx-auto mt-2 max-w-md text-text-2">Dieser Freigabe-Link existiert nicht mehr oder wurde zurückgezogen. Bitte um einen neuen Link.</p>
          </GlassCard>
        ) : (
          <div className="flex flex-col gap-6">
            {/* Bei einem Paket zuerst, worum es geht. Ohne diese Zeile steht jemand vor sieben
                Videos und weiss nicht, ob er alle ansehen soll oder eines davon aussuchen. */}
            {paket && eintraege.length > 1 && (
              <GlassCard padding="md">
                <p className="text-[15px] font-medium text-text">{paket.freigabe.name}</p>
                <p className="mt-1 text-sm text-text-2">
                  {eintraege.length} Clips. Bitte sag zu jedem, ob er so hinaus darf.
                </p>
                {paket.freigabe.message && <p className="mt-2 text-sm text-text-2">{paket.freigabe.message}</p>}
              </GlassCard>
            )}
            {eintraege.map((view) => (
              <GuestDecision
                key={view.approval.id}
                /* Das Token DIESES Clips, nicht das des Pakets: entschieden wird je Clip. */
                token={view.approval.token}
                view={{
                  guest_name: view.approval.guest_name,
                  message: view.approval.message,
                  decision: view.approval.decision,
                  comment: view.approval.comment,
                  decided_at: view.approval.decided_at,
                  expires_at: view.approval.expires_at,
                  expired: isExpired(view.approval),
                  workspace_name: view.workspace_name,
                  source_title: view.source_title,
                  platform: view.clip.platform,
                  aspect: view.clip.aspect,
                  title_card: view.clip.title_card,
                  duration_s: view.clip.duration_s,
                  video_url: guestMediaUrl(base, view.clip.file_key, isLocalMedia() ? view.approval.token : null),
                  poster_url: guestMediaUrl(base, view.clip.poster_key, isLocalMedia() ? view.approval.token : null),
                  onscreen_hook: view.onscreen_hook,
                  spoken_hook: view.spoken_hook,
                  post_caption: view.post_caption,
                }}
              />
            ))}
          </div>
        )}
        <p className="mt-8 text-center text-xs text-text-3">chopstr · EU-verarbeitet. Deine Entscheidung wird mit Zeitpunkt im Audit-Log des Teams gespeichert.</p>
      </main>
    </div>
  );
}
