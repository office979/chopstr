import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Timecode } from "@/components/ui/Timecode";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { STATUS_LABELS, isTerminalStatus } from "@/lib/pipeline";
import { isDemoMode, temporalConfigured } from "@/lib/env";
import { DeleteSourceButton } from "@/components/projects/DeleteSourceButton";
import { formatBytes, formatDate } from "@/lib/format";
import { ProDetails, ProRow } from "@/components/ui/ProDetails";
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
  const session = await requireSession();
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) notFound();
  const canDelete = can(session.role, "source.delete");

  const [events, transcript, brand, candidateCount, clipCount] = await Promise.all([
    repo.listPipelineEvents(id),
    repo.getCurrentTranscript(id),
    source.brand_profile_id ? repo.getBrandProfile(source.brand_profile_id) : Promise.resolve(null),
    repo.countCandidates(id),
    repo.countClips(id),
  ]);

  const live = !isTerminalStatus(source.status);
  const hasCandidates = source.status === "ready" && candidateCount.total > 0;

  return (
    <PageShell backgroundWord="Video" lightTone={live ? "ai" : "brand"}>
      <PageHeader
        eyebrow="Video"
        title={source.title}
        description={source.original_filename ?? undefined}
        actions={
          <>
            <ButtonLink href="/" variant="ghost">
              Alle Videos
            </ButtonLink>
            {transcript && (
              <ButtonLink href={`/projekte/${source.id}/transkript`} variant={hasCandidates ? "ghost" : "primary"}>
                Text öffnen
              </ButtonLink>
            )}
            {hasCandidates && <ButtonLink href={`/projekte/${source.id}/review`}>Clips auswählen</ButtonLink>}
            {clipCount.total > 0 && (
              <ButtonLink href={`/projekte/${source.id}/clips`} variant="ghost">
                Clips
              </ButtonLink>
            )}
            {canDelete && <DeleteSourceButton sourceId={source.id} title={source.title} size="md" redirectTo="/" />}
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
          candidateCount={candidateCount}
          localWorker={!isDemoMode() && !temporalConfigured()}
        />

        <div className="flex flex-col gap-5">
          {clipCount.total > 0 && (
            <GlassCard padding="lg" selected={clipCount.rendering > 0}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-medium">Clips</h2>
                  <p className="mt-1 text-sm text-text-2">
                    {clipCount.rendered} von {clipCount.total} fertig
                    {clipCount.rendering > 0 ? `, ${clipCount.rendering} in Arbeit` : ""}
                    {clipCount.failed > 0 ? `, ${clipCount.failed} fehlgeschlagen` : ""}.
                  </p>
                </div>
                <p className="text-4xl font-light leading-none tabular-nums tracking-[var(--tracking-display)]">{clipCount.total}</p>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <ButtonLink href={`/projekte/${source.id}/clips`} size="sm">
                  Clips öffnen
                </ButtonLink>
                {clipCount.failed > 0 && <Badge tone="attention">{clipCount.failed} fehlgeschlagen</Badge>}
              </div>
            </GlassCard>
          )}
          <GlassCard padding="lg">
            <h2 className="mb-5 text-lg font-medium">Angaben zum Video</h2>
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
                <Meta label="Aussehen">{brand?.name ?? <span className="text-text-2">keines</span>}</Meta>
              </div>
              <div className="col-span-2">
                <Meta label="Status">
                  <Badge tone={source.status === "failed" ? "attention" : live ? "ai" : "neutral"}>
                    {STATUS_LABELS[source.status]}
                  </Badge>
                </Meta>
              </div>
            </dl>

            {/* Prüfsumme, Löschfrist und Rechtestatus lösen keine Entscheidung aus; sie stehen
                hier, statt die Hauptansicht zu füllen (Bedienkonzept, Abschnitt 9). */}
            <ProDetails className="mt-5">
              <ProRow label="SHA-256">{source.sha256 ?? "wird ermittelt"}</ProRow>
              <ProRow label="Löschfrist">{formatDate(source.delete_after)}</ProRow>
              <ProRow label="Rechtestatus">{RIGHTS_LABEL[source.rights_status]}</ProRow>
              {source.mime_type && <ProRow label="Dateityp">{source.mime_type}</ProRow>}
              {source.original_filename && <ProRow label="Dateiname">{source.original_filename}</ProRow>}
              {transcript?.asr_model_id && <ProRow label="Spracherkennung">{transcript.asr_model_id}</ProRow>}
              {transcript?.diarizer_id && <ProRow label="Sprechertrennung">{transcript.diarizer_id}</ProRow>}
            </ProDetails>
          </GlassCard>

          {(source.brief.audience || source.brief.wanted || source.brief.exclude) && (
            <GlassCard padding="lg">
              <h2 className="mb-4 text-lg font-medium">Deine Wünsche</h2>
              <dl className="flex flex-col gap-4">
                {source.brief.audience && <Meta label="Zielgruppe">{source.brief.audience}</Meta>}
                {source.brief.wanted && <Meta label="Gewünschte Clips">{source.brief.wanted}</Meta>}
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
