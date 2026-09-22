import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Timecode } from "@/components/ui/Timecode";
import { getRepo } from "@/lib/repo";
import { STATUS_LABELS, isTerminalStatus } from "@/lib/pipeline";
import { formatBytes, formatDate, shortHash } from "@/lib/format";
import { PipelineLive } from "./PipelineLive";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source?.title ?? "Projekt" };
}

const RIGHTS_LABEL = { own: "Eigenes Material", licensed: "Lizenziert", third_party: "Fremdmaterial (Quellenangabe)" };

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs uppercase tracking-wide text-text-2">{label}</dt>
      <dd className="text-[15px] text-text">{children}</dd>
    </div>
  );
}

export default async function ProjectPage({ params }: Props) {
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();

  const [events, transcript, brand] = await Promise.all([
    repo.listPipelineEvents(id),
    repo.getCurrentTranscript(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
  ]);

  const live = !isTerminalStatus(source.status);

  return (
    <PageShell backgroundWord="Projekt" lightTone={live ? "ai" : "brand"}>
      <PageHeader
        eyebrow="Projekt"
        title={source.title}
        description={source.original_filename ?? undefined}
        actions={
          <>
            <ButtonLink href="/" variant="ghost">
              Alle Projekte
            </ButtonLink>
            {transcript && <ButtonLink href={`/projekte/${source.id}/transkript`}>Transkript öffnen</ButtonLink>}
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <PipelineLive
          sourceId={source.id}
          initialStatus={source.status}
          initialStatusMessage={source.status_message}
          initialEvents={events}
          hasTranscript={Boolean(transcript)}
        />

        <div className="flex flex-col gap-5">
          <GlassCard padding="lg">
            <h2 className="mb-5 text-lg font-medium">Metadaten</h2>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-5">
              <Meta label="Dauer">
                <Timecode seconds={source.duration_s} className="text-text" />
              </Meta>
              <Meta label="Auflösung">
                {source.width && source.height ? (
                  <span className="font-mono">
                    {source.width}×{source.height}
                    {source.fps ? `, ${source.fps} fps` : ""}
                  </span>
                ) : (
                  <span className="text-text-2">wird ermittelt</span>
                )}
              </Meta>
              <Meta label="Größe">{formatBytes(source.size_bytes)}</Meta>
              <Meta label="Löschfrist">{formatDate(source.delete_after)}</Meta>
              <div className="col-span-2">
                <Meta label="SHA-256">
                  <span className="font-mono text-sm" title={source.sha256 ?? undefined}>
                    {shortHash(source.sha256)}
                  </span>
                </Meta>
              </div>
              <Meta label="Rechte">{RIGHTS_LABEL[source.rights_status]}</Meta>
              <Meta label="Sprecher erwartet">{source.expected_speakers ?? "unbekannt"}</Meta>
              {source.rights_status === "third_party" && (
                <div className="col-span-2">
                  <Meta label="Quelle">
                    {[source.source_owner, source.source_title].filter(Boolean).join(", ") || "keine Angabe"}
                    {source.source_url && (
                      <span className="block truncate font-mono text-sm text-text-2">{source.source_url}</span>
                    )}
                  </Meta>
                </div>
              )}
              <div className="col-span-2">
                <Meta label="Markenprofil">{brand?.name ?? <span className="text-text-2">keines</span>}</Meta>
              </div>
              <div className="col-span-2">
                <Meta label="Status">
                  <Badge tone={source.status === "failed" ? "attention" : live ? "ai" : "neutral"}>
                    {STATUS_LABELS[source.status]}
                  </Badge>
                </Meta>
              </div>
            </dl>
          </GlassCard>

          {(source.brief.audience || source.brief.wanted || source.brief.exclude) && (
            <GlassCard padding="lg">
              <h2 className="mb-4 text-lg font-medium">Redaktions-Briefing</h2>
              <dl className="flex flex-col gap-4">
                {source.brief.audience && <Meta label="Zielgruppe">{source.brief.audience}</Meta>}
                {source.brief.wanted && <Meta label="Gewünschte Momente">{source.brief.wanted}</Meta>}
                {source.brief.exclude && <Meta label="Ausschlüsse">{source.brief.exclude}</Meta>}
                {source.brief.platform && <Meta label="Plattform">{source.brief.platform}</Meta>}
              </dl>
            </GlassCard>
          )}
        </div>
      </div>
    </PageShell>
  );
}
