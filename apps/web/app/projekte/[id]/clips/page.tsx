import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { isTerminalStatus } from "@/lib/pipeline";
import { isDemoMode, temporalConfigured } from "@/lib/env";
import { PipelineLive } from "../PipelineLive";
import { aspectForSource } from "@/lib/clips/presets";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { getQuota } from "@/lib/billing/quota";
import { previewFontFor } from "@/lib/brand/preview-font";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { canExt } from "@/lib/auth/permissions-publishing";
import { mediaUrl } from "@/lib/clips/labels";
import { ClipBoard } from "./ClipBoard";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source ? `Clips · ${source.title}` : "Clips" };
}

export default async function ClipsPage({ params }: Props) {
  const { id } = await params;
  const session = await requireSession();
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();
  const [clips, candidates, events, brand, approvals, quota] = await Promise.all([
    repo.listClips(id),
    repo.listCandidates(id),
    repo.listPipelineEvents(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
    repo.listGuestApprovals(id),
    getQuota(repo),
  ]);
  const previewFont = await previewFontFor(repo, brand);
  const pub = getPublishingRepo();
  const clipIds = clips.map((c) => c.id);
  const [seriesList, extrasList] = await Promise.all([pub.listSeries(), pub.getClipExtras(clipIds)]);

  /* Noch keine Clips? Dann zeigt diese Seite, wie weit der Computer ist.
   *
   * Das stand vorher auf einer eigenen Seite je Video, und von dort musste man weiterklicken.
   * Solange gerechnet wird, ist der Fortschritt die Antwort auf die einzige Frage, die jemand
   * hat; danach verschwindet er von selbst, weil dann Clips da sind. Eine Seite, die nach getaner
   * Arbeit ein Datenblatt über einen abgeschlossenen Vorgang zeigt, braucht niemand. */
  if (clips.length === 0) {
    const [events, candidateCount] = await Promise.all([repo.listPipelineEvents(id), repo.countCandidates(id)]);
    const live = !isTerminalStatus(source.status);
    return (
      <PageShell width="narrow" backgroundWord="Video" lightTone={live ? "ai" : "brand"}>
        <Brotkrume titel={source.title} />
        <PageHeader eyebrow="Video" title={source.title} />
        <PipelineLive
          sourceId={source.id}
          initialStatus={source.status}
          initialStatusMessage={source.status_message}
          initialEvents={events}
          candidateCount={candidateCount}
          localWorker={!isDemoMode() && !temporalConfigured()}
        />
      </PageShell>
    );
  }

  const candidateIds = new Set(clips.map((c) => c.candidate_id));

  return (
    <PageShell width="wide" backgroundWord="Clips">
      <Brotkrume titel={source.title} />

      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Clips prüfen</h1>
        {/* Marke und Video stehen einmal hier und nicht auf jeder Karte: auf dieser Seite sind sie
            für alle Clips gleich, und vierzehnmal dasselbe ist keine Information. */}
        <p className="mt-1 text-sm text-text-2">
          {brand ? (
            <>
              Marke{" "}
              <Link href={`/marke?p=${brand.id}`} className="text-text hover:underline">
                {brand.name}
              </Link>
              {" · "}
            </>
          ) : null}
          Video {source.title}
        </p>
      </div>
      <ClipBoard
        sourceId={source.id}
        initialClips={clips}
        quellAspekt={aspectForSource(source.width, source.height)}
        candidates={candidates.filter((c) => candidateIds.has(c.id))}
        initialEvents={events.filter((e) => e.step === "render")}
        mediaBase={process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null}
        quelleSrc={mediaUrl(process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null, source.proxy_key)}
        demo={repo.kind === "demo"}
        highlightColor={brand?.caption_style?.highlight_color}
        lowerThird={brand?.ci?.lower_third?.enabled ? { name: brand.ci.lower_third.name ?? "", role: brand.ci.lower_third.role ?? "" } : null}
        guestApprovals={approvals}
        canRequestGuest={can(session.role, "guest_approval.request")}
        planAllowsGuest={Boolean(quota.plan?.features?.guest_approval)}
        planName={quota.plan?.name ?? "Starter"}
        canDelete={can(session.role, "source.delete")}
        canPublish={canExt(session.role, "publishing.publish")}
        previewFont={previewFont}
        publishing={{
          series: seriesList.filter((s) => s.active),
          extras: Object.fromEntries(extrasList.map((e) => [e.id, e])),
          canSeries: canExt(session.role, "series.manage"),
        }}
      />
    </PageShell>
  );
}

/* Der Weg hierher, als Pfad. Er endet beim VIDEO und nicht bei „Clips prüfen": diese Seite ist
 * das Video - es gibt keine Ebene mehr darüber, seit die eigene Projektseite weggefallen ist. */
function Brotkrume({ titel }: { titel: string }) {
  return (
    <nav aria-label="Pfad" className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-text-2">
      <Link href="/" className="hover:text-text hover:underline">
        Meine Videos
      </Link>
      <span aria-hidden="true" className="text-text-3">
        ›
      </span>
      <span className="max-w-[320px] truncate text-text">{titel}</span>
    </nav>
  );
}
