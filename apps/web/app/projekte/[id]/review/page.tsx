import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { sentencesFromWords } from "@/lib/transcript/sentences";
import { ReviewBoard } from "./ReviewBoard";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source ? `Review · ${source.title}` : "Review" };
}

export default async function ReviewPage({ params }: Props) {
  const { id } = await params;
  await requireSession();
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();
  const [transcript, candidates, clips, brand] = await Promise.all([
    repo.getCurrentTranscript(id),
    repo.listCandidates(id),
    repo.listClips(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
  ]);

  if (candidates.length === 0 || !transcript) {
    const running = source.status !== "ready" && source.status !== "failed";
    return (
      <PageShell width="narrow" backgroundWord="Review">
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">{running ? "Noch keine Kandidaten" : "Keine Kandidaten"}</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            {running
              ? "Die Story-Engine läuft noch. Sobald die Pipeline fertig ist, erscheinen die Kandidaten hier."
              : "Verwerfen ist ein Ergebnis: das Material hat keinen eigenständigen Moment ergeben."}
          </p>
          {!running && (
            <p className="mx-auto mt-3 max-w-md text-sm text-text-2">
              Prüfe das Redaktions-Briefing im Projekt: Zielgruppe, gewünschte Momente und Ausschlüsse steuern, was die
              Story-Engine vorschlägt.
            </p>
          )}
          <div className="mt-6 flex justify-center gap-2">
            <ButtonLink href={`/projekte/${source.id}`} variant="ghost">
              Zum Projekt
            </ButtonLink>
            {transcript && <ButtonLink href={`/projekte/${source.id}/transkript`}>Transkript öffnen</ButtonLink>}
          </div>
        </GlassCard>
      </PageShell>
    );
  }

  const mediaBase = process.env.NEXT_PUBLIC_MEDIA_BASE_URL;
  const videoSrc = source.proxy_key && mediaBase ? `${mediaBase.replace(/\/$/, "")}/${source.proxy_key}` : null;
  const sentences = sentencesFromWords(transcript.words);
  const passed = candidates.filter((c) => c.gate_passed).length;

  return (
    <PageShell width="wide" backgroundWord="Review">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-text-2">
            <Link href={`/projekte/${source.id}`} className="hover:text-text hover:underline">
              {source.title}
            </Link>
          </p>
          <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Kandidaten prüfen</h1>
          <p className="mt-1 text-sm text-text-2">
            {candidates.length} Kandidaten, {passed} erfüllen alle Pflichtkriterien. Du entscheidest, was ein Clip wird.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {clips.length > 0 && (
            <ButtonLink href={`/projekte/${source.id}/clips`} variant="ghost" size="sm">
              Clips ({clips.length})
            </ButtonLink>
          )}
          <ButtonLink href={`/projekte/${source.id}/transkript`} variant="ghost" size="sm">
            Transkript
          </ButtonLink>
        </div>
      </div>
      <ReviewBoard
        sourceId={source.id}
        title={source.title}
        durationS={source.duration_s ?? transcript.words.at(-1)?.end ?? 0}
        videoSrc={videoSrc}
        initialCandidates={candidates}
        initialClips={clips}
        defaultPlatform={brand?.default_platform ?? source.brief.platform ?? "linkedin"}
        sentences={sentences}
        speakerNames={transcript.stats.speaker_names ?? {}}
      />
    </PageShell>
  );
}
