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
  const [connections, seriesList, publications, feedback, extrasList, workspace] = await Promise.all([
    pub.listConnections(),
    pub.listSeries(),
    pub.listPublicationsForClips(clipIds),
    pub.listFeedbackForClips(clipIds),
    pub.getClipExtras(clipIds),
    repo.getWorkspace(),
  ]);

  if (clips.length === 0) {
    return (
      <PageShell width="narrow" backgroundWord="Clips">
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch keine Clips</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Clips entstehen, sobald du einen Moment nimmst. Für jede Plattform, die du wählst, wird einer erstellt.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <ButtonLink href={`/projekte/${source.id}`} variant="ghost">
              Zum Video
            </ButtonLink>
            <ButtonLink href={`/projekte/${source.id}/review`}>Momente auswählen</ButtonLink>
          </div>
        </GlassCard>
      </PageShell>
    );
  }

  const candidateIds = new Set(clips.map((c) => c.candidate_id));

  return (
    <PageShell width="wide" backgroundWord="Clips">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-text-2">
            <Link href={`/projekte/${source.id}`} className="hover:text-text hover:underline">
              {source.title}
            </Link>
          </p>
          <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Clips</h1>
          <p className="mt-1 text-sm text-text-2">Ansehen, herunterladen oder direkt posten.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/serien" variant="ghost" size="sm">
            Serien
          </ButtonLink>
          <ButtonLink href="/experimente" variant="ghost" size="sm">
            Experimente
          </ButtonLink>
          <ButtonLink href={`/projekte/${source.id}/review`} variant="ghost" size="sm">
            Momente
          </ButtonLink>
          <ButtonLink href={`/projekte/${source.id}`} variant="ghost" size="sm">
            Video
          </ButtonLink>
        </div>
      </div>
      <ClipBoard
        sourceId={source.id}
        initialClips={clips}
        candidates={candidates.filter((c) => candidateIds.has(c.id))}
        initialEvents={events.filter((e) => e.step === "render")}
        mediaBase={process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null}
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
          connections: connections.filter((c) => c.status === "connected"),
          series: seriesList.filter((s) => s.active),
          publications,
          feedback,
          extras: Object.fromEntries(extrasList.map((e) => [e.id, e])),
          dpaSigned: Boolean(workspace.dpa_signed_at),
          plan: quota.plan ? { name: quota.plan.name, features: quota.plan.features } : null,
          canPublish: canExt(session.role, "publishing.publish"),
          canSeries: canExt(session.role, "series.manage"),
          canRender: can(session.role, "clip.render"),
        }}
      />
    </PageShell>
  );
}
