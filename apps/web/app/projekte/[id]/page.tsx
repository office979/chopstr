import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { isTerminalStatus } from "@/lib/pipeline";
import { isDemoMode, temporalConfigured } from "@/lib/env";
import { PipelineLive } from "./PipelineLive";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source?.title ?? "Video" };
}

/* Diese Seite zeigt den Fortschritt der Analyse, sonst nichts. Dauer, Auflösung, Größe, Rechtestatus
 * und der Löschen-Knopf standen hier daneben und haben eine Wartezeit in ein Datenblatt verwandelt.
 * Wer wartet, will eine Frage beantwortet haben: wie lange noch. Danach geht es automatisch zu den
 * Clips weiter, die Seite muss also nicht noch einmal aufgerufen werden. */
export default async function ProjectPage({ params }: Props) {
  const { id } = await params;
  await requireSession();
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();

  const [events, candidateCount] = await Promise.all([repo.listPipelineEvents(id), repo.countCandidates(id)]);

  const live = !isTerminalStatus(source.status);

  return (
    <PageShell backgroundWord="Video" lightTone={live ? "ai" : "brand"} width="narrow">
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
