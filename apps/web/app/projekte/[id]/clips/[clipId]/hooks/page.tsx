import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { getQuota } from "@/lib/billing/quota";
import { previewFontFor } from "@/lib/brand/preview-font";
import { latestByClip } from "@/lib/guest/approval";
import { lintProfileFrom } from "@/lib/clips/render-demo";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import { HookStudio } from "./HookStudio";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string; clipId: string }> };

export async function generateMetadata({ params }: Props) {
  const { clipId } = await params;
  const clip = await getRepo().getClip(clipId);
  return { title: clip ? `Hook-Studio · ${PLATFORM_LABELS[clip.platform]}` : "Hook-Studio" };
}

export default async function HookStudioPage({ params }: Props) {
  const { id, clipId } = await params;
  const session = await requireSession();
  const repo = getRepo();
  const [source, clip] = await Promise.all([repo.getSource(id), repo.getClip(clipId)]);
  if (!source || !clip || clip.source_id !== id) notFound();
  const [candidate, versions, captions, brand, siblings, approvals, quota] = await Promise.all([
    clip.candidate_id ? repo.getCandidate(clip.candidate_id) : Promise.resolve(null),
    repo.listHookVersions(clipId),
    repo.getCurrentCaptions(clipId),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
    repo.listClips(id),
    repo.listGuestApprovals(id),
    getQuota(repo),
  ]);
  const previewFont = await previewFontFor(repo, brand);

  return (
    <PageShell width="wide" backgroundWord="Hook" className="pt-24 sm:pt-28">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-text-2">
            <Link href={`/projekte/${source.id}`} className="hover:text-text hover:underline">
              {source.title}
            </Link>
            {" · "}
            <Link href={`/projekte/${source.id}/clips`} className="hover:text-text hover:underline">
              Clips
            </Link>
          </p>
          <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Hook-Studio</h1>
          <p className="mt-1 text-sm text-text-2">
            {PLATFORM_LABELS[clip.platform]}, {clip.aspect}. Jede Änderung wird eine neue Version, der Render folgt erst auf deinen Klick.
          </p>
        </div>
        <ButtonLink href={`/projekte/${source.id}/clips`} variant="ghost" size="sm">
          Zur Clip-Übersicht
        </ButtonLink>
      </div>
      <HookStudio
        sourceId={source.id}
        clip={clip}
        clipText={candidate?.rubric.text ?? ""}
        initialVersions={versions}
        captions={captions}
        lintProfile={lintProfileFrom(brand)}
        siblingClips={siblings.filter((c) => c.candidate_id === clip.candidate_id && c.id !== clip.id)}
        highlightColor={brand?.caption_style?.highlight_color}
        hookOverlayDefault={brand?.caption_style?.hook_overlay?.[clip.platform] ?? clip.platform !== "linkedin"}
        lowerThird={brand?.ci?.lower_third?.enabled ? { name: brand.ci.lower_third.name ?? "", role: brand.ci.lower_third.role ?? "" } : null}
        guestApproval={latestByClip(approvals).get(clip.id) ?? null}
        canRequestGuest={can(session.role, "guest_approval.request")}
        planAllowsGuest={Boolean(quota.plan?.features?.guest_approval)}
        planName={quota.plan?.name ?? "Starter"}
        previewFont={previewFont}
      />
    </PageShell>
  );
}
