import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
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
  const [clips, candidates, events, brand, approvals, quota, transcript] = await Promise.all([
    repo.listClips(id),
    repo.listCandidates(id),
    repo.listPipelineEvents(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
    repo.listGuestApprovals(id),
    getQuota(repo),
    repo.getCurrentTranscript(id),
  ]);
  const previewFont = await previewFontFor(repo, brand);
  const pub = getPublishingRepo();
  const clipIds = clips.map((c) => c.id);
  const [seriesList, extrasList] = await Promise.all([pub.listSeries(), pub.getClipExtras(clipIds)]);

  if (clips.length === 0) {
    return (
      <PageShell width="narrow" backgroundWord="Clips">
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch keine Clips</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Clips entstehen von selbst, sobald der Computer dein Video durchgesehen hat.
          </p>
          <div className="mt-6 flex justify-center">
            <ButtonLink href={`/projekte/${source.id}`}>Zum Video</ButtonLink>
          </div>
        </GlassCard>
      </PageShell>
    );
  }

  const candidateIds = new Set(clips.map((c) => c.candidate_id));

  return (
    <PageShell width="wide" backgroundWord="Clips">
      {/* Der Weg hierher, als Pfad. Wer aus einem Clip zurückkommt, muss ohne Zurück-Taste des
          Browsers wissen, wo er ist und wie er eine Ebene höher kommt. */}
      <nav aria-label="Pfad" className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-text-2">
        <Link href="/" className="hover:text-text hover:underline">
          Meine Videos
        </Link>
        <span aria-hidden="true" className="text-text-3">
          ›
        </span>
        <Link href={`/projekte/${source.id}`} className="max-w-[260px] truncate hover:text-text hover:underline">
          {source.title}
        </Link>
        <span aria-hidden="true" className="text-text-3">
          ›
        </span>
        <span className="text-text">Clips prüfen</span>
      </nav>

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
        transkriptVersion={transcript?.version ?? null}
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
