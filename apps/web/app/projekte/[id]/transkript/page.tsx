import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { TranscriptEditor } from "./TranscriptEditor";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source ? `Transkript · ${source.title}` : "Transkript" };
}

export default async function TranscriptPage({ params }: Props) {
  const { id } = await params;
  await requireSession();
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();
  const transcript = await repo.getCurrentTranscript(id);

  if (!transcript) {
    return (
      <PageShell width="narrow" backgroundWord="Text">
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch kein Transkript</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Für „{source.title}“ liegt noch keine Transkript-Version vor. Sobald die Pipeline fertig ist, erscheint es hier.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <ButtonLink href={`/projekte/${source.id}`} variant="ghost">
              Zum Projekt
            </ButtonLink>
          </div>
        </GlassCard>
      </PageShell>
    );
  }

  /* Proxy-Video nur, wenn ein Key und eine öffentliche Medien-Basis-URL vorliegen.
   * TODO (Phase 2): signierte URLs aus dem derived-Bucket statt statischer Basis-URL. */
  const mediaBase = process.env.NEXT_PUBLIC_MEDIA_BASE_URL;
  const videoSrc = source.proxy_key && mediaBase ? `${mediaBase.replace(/\/$/, "")}/${source.proxy_key}` : null;

  return (
    <PageShell width="wide" backgroundWord="Text">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-text-2">
            <Link href={`/projekte/${source.id}`} className="hover:text-text hover:underline">
              {source.title}
            </Link>
          </p>
          <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Transkript</h1>
        </div>
      </div>
      <TranscriptEditor
        sourceId={source.id}
        title={source.title}
        durationS={source.duration_s ?? transcript.words.at(-1)?.end ?? 0}
        videoSrc={videoSrc}
        transcript={transcript}
      />
    </PageShell>
  );
}
