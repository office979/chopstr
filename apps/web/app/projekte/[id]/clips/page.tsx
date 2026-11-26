import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { isTerminalStatus } from "@/lib/pipeline";
import { isDemoMode, temporalConfigured } from "@/lib/env";
import { PipelineLive } from "../PipelineLive";
import { requireSession } from "@/lib/session";
import { mediaUrl } from "@/lib/clips/labels";
import { ClipGallery } from "./ClipGallery";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source ? `Clips · ${source.title}` : "Clips" };
}

export default async function ClipsPage({ params }: Props) {
  const { id } = await params;
  await requireSession();
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();
  const [clips, candidates, brand] = await Promise.all([
    repo.listClips(id),
    repo.listCandidates(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
  ]);

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
  const base = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;

  return (
    <PageShell width="wide" backgroundWord="Clips">
      <Brotkrume titel={source.title} />
      <ClipGallery
        sourceId={source.id}
        clips={clips}
        candidates={candidates.filter((c) => candidateIds.has(c.id))}
        mediaBase={base}
        demoSrc={repo.kind === "demo" ? mediaUrl(base, source.proxy_key) ?? "/demo/video.mp4" : null}
        quelleSrc={mediaUrl(base, source.proxy_key) ?? (repo.kind === "demo" ? "/demo/video.mp4" : null)}
        stilName={brand?.name ?? null}
        stilHref={brand ? `/marke?p=${brand.id}` : null}
        aktuellerLook={(brand?.caption_style as { look?: string } | undefined)?.look ?? null}
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
