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

/* Öffentliche Freigabeseite (PHASE4.md, Abschnitt 4): kein Login, das Token ist das Geheimnis. */
export default async function GuestApprovalPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const repo = getRepo();
  const view = isTokenShape(token) ? await repo.getGuestApprovalByToken(token) : null;
  if (view && !view.approval.viewed_at) await repo.markGuestApprovalViewed(token);
  const base = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;
  const mediaToken = isLocalMedia() ? token : null;

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <BlueBubbles />
      <main className="relative z-10 mx-auto flex w-full max-w-[960px] flex-col px-4 pb-16 pt-10 sm:px-6 sm:pt-16">
        <div className="mb-8 flex items-center justify-between gap-4">
          <Link href="/" aria-label="chopstr" className="inline-flex">
            <Wordmark width={128} className="opacity-95" />
          </Link>
          {view && <span className="text-xs text-text-3">Freigabe für {view.workspace_name}</span>}
        </div>

        {!view ? (
          <GlassCard padding="lg" className="text-center">
            <p className="text-lg font-medium">Link ungültig</p>
            <p className="mx-auto mt-2 max-w-md text-text-2">Dieser Freigabe-Link existiert nicht mehr oder wurde zurückgezogen. Bitte um einen neuen Link.</p>
          </GlassCard>
        ) : (
          <GuestDecision
            token={token}
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
              video_url: guestMediaUrl(base, view.clip.file_key, mediaToken),
              poster_url: guestMediaUrl(base, view.clip.poster_key, mediaToken),
              onscreen_hook: view.onscreen_hook,
              spoken_hook: view.spoken_hook,
              post_caption: view.post_caption,
            }}
          />
        )}
        <p className="mt-8 text-center text-xs text-text-3">chopstr · EU-verarbeitet · Mensch gibt frei. Deine Entscheidung wird mit Zeitpunkt im Audit-Log des Workspace gespeichert.</p>
      </main>
    </div>
  );
}
