import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
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
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();
  const [clips, candidates, events, brand] = await Promise.all([
    repo.listClips(id),
    repo.listCandidates(id),
    repo.listPipelineEvents(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
  ]);

  if (clips.length === 0) {
    return (
      <PageShell width="narrow" backgroundWord="Clips">
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch keine Clips</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Clips entstehen, wenn du im Review einen Kandidaten annimmst und Ziele wählst. Je Ziel wird ein Clip gerendert.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <ButtonLink href={`/projekte/${source.id}`} variant="ghost">
              Zum Projekt
            </ButtonLink>
            <ButtonLink href={`/projekte/${source.id}/review`}>Kandidaten prüfen</ButtonLink>
          </div>
        </GlassCard>
      </PageShell>
    );
  }

  const candidateIds = new Set(clips.map((c) => c.candidate_id));

  return (
    <PageShell width="wide" backgroundWord="Clips" className="pt-24 sm:pt-28">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-text-2">
            <Link href={`/projekte/${source.id}`} className="hover:text-text hover:underline">
              {source.title}
            </Link>
          </p>
          <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Clips</h1>
          <p className="mt-1 text-sm text-text-2">Jeder Render ist ein deterministischer Plan, den du prüfen kannst.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href={`/projekte/${source.id}/review`} variant="ghost" size="sm">
            Review
          </ButtonLink>
          <ButtonLink href={`/projekte/${source.id}`} variant="ghost" size="sm">
            Projekt
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
      />
    </PageShell>
  );
}
