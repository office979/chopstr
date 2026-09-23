import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { decisionCheck, posteriorAOverB, successMetricLabel, variantStats } from "@/lib/experiments/stats";
import { CLIP_STATUS_LABELS, PLATFORM_LABELS, patternLabel } from "@/lib/clips/labels";
import { PUBLICATION_STATUS_LABELS } from "@/lib/publishing/platforms";
import { formatDateTime } from "@/lib/format";
import { ExperimentDecision } from "./ExperimentDecision";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const experiment = await getPublishingRepo().getExperiment(id);
  return { title: experiment?.hypothesis ? `Experiment · ${experiment.hypothesis.slice(0, 60)}` : "Experiment" };
}

function n(v: number | null | undefined, digits = 0): string {
  return v == null ? "nicht verfügbar" : v.toLocaleString("de-AT", { maximumFractionDigits: digits });
}

/* Detail eines Experiments: beide Clips, Metriken je Variante, Bedingungen, Konfidenz, Gewinner setzen */
export default async function ExperimentPage({ params }: Props) {
  const { id } = await params;
  await requirePublishingPage("experiments.manage");
  const pub = getPublishingRepo();
  const experiment = await pub.getExperiment(id);
  if (!experiment) notFound();
  const clips = await pub.listClipsForExperiment(id);
  const ids = clips.map((c) => c.id);
  const repo = getRepo();
  const [publications, feedback, hooks] = await Promise.all([
    pub.listPublicationsForClips(ids),
    pub.listFeedbackForClips(ids),
    Promise.all(clips.map((c) => repo.getCurrentHook(c.id))),
  ]);
  const a = clips.find((c) => c.variant === "A") ?? null;
  const b = clips.find((c) => c.variant === "B") ?? null;
  const sa = a ? variantStats(a.id, publications, feedback) : null;
  const sb = b ? variantStats(b.id, publications, feedback) : null;
  const check = decisionCheck(experiment, sa, sb);
  const confidence = experiment.confidence ?? (sa && sb ? posteriorAOverB(sa, sb, id) : null);
  const source = a ? await repo.getSource(a.source_id) : null;

  return (
    <PageShell width="default" backgroundWord="A/B">
      <PageHeader
        eyebrow={`Experiment${source ? ` · ${source.title}` : ""}`}
        title={experiment.hypothesis ?? "Experiment"}
        description={`Angelegt ${formatDateTime(experiment.created_at)} · Mindestexposure ${experiment.min_exposure.toLocaleString("de-AT")} Views je Variante`}
        actions={
          <>
            <ButtonLink href="/experimente" variant="ghost">
              Alle Experimente
            </ButtonLink>
            {source && (
              <ButtonLink href={`/projekte/${source.id}/clips`} variant="ghost">
                Clips des Projekts
              </ButtonLink>
            )}
          </>
        }
      />

      <div className="grid gap-5 md:grid-cols-2">
        {(
          [
            ["A", a, sa],
            ["B", b, sb],
          ] as const
        ).map(([label, clip, stats]) => {
          const hook = clip ? hooks[clips.indexOf(clip)] : null;
          const winner = experiment.winner_clip_id && clip && experiment.winner_clip_id === clip.id;
          const pubs = clip ? publications.filter((p) => p.clip_id === clip.id) : [];
          return (
            <GlassCard key={label} padding="lg" selected={Boolean(winner)} className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-medium">Variante {label}</h2>
                <div className="flex gap-1.5">
                  {winner && <Badge tone="ok">Gewinner</Badge>}
                  {clip && <Badge>{PLATFORM_LABELS[clip.platform]}</Badge>}
                </div>
              </div>
              {!clip ? (
                <p className="text-sm text-text-2">Kein Clip für diese Variante.</p>
              ) : (
                <>
                  <div className="text-sm">
                    <p className="text-text-2">Hook ({patternLabel(hook?.pattern)})</p>
                    <p className="mt-1 text-text">{hook?.spoken_hook ?? "Noch keine Hook-Version"}</p>
                    {hook?.onscreen_hook && <p className="mt-1 text-xs text-text-2">On-Screen: {hook.onscreen_hook}</p>}
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    <dt className="text-text-2">Clip-Status</dt>
                    <dd>{CLIP_STATUS_LABELS[clip.status]}</dd>
                    <dt className="text-text-2">Veröffentlicht</dt>
                    <dd>{stats?.published_at ? formatDateTime(stats.published_at) : "noch nicht"}</dd>
                    <dt className="text-text-2">Views</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.views)}</dd>
                    <dt className="text-text-2">Folgen</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.follows)}</dd>
                    <dt className="text-text-2">Folgequote / 1.000</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.follows_per_1k, 2)}</dd>
                    <dt className="text-text-2">Saves</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.saves)}</dd>
                    <dt className="text-text-2">Fenster</dt>
                    <dd>{stats?.window ?? "keine Metriken"}</dd>
                  </dl>
                  {pubs.length > 0 && (
                    <ul className="flex flex-col gap-1 text-xs text-text-2">
                      {pubs.map((p) => (
                        <li key={p.id}>
                          {PUBLICATION_STATUS_LABELS[p.status]}
                          {p.external_url ? (
                            <>
                              {" · "}
                              <a href={p.external_url} target="_blank" rel="noreferrer" className="underline-offset-4 hover:text-text hover:underline">
                                Post
                              </a>
                            </>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="mt-auto flex flex-wrap gap-2">
                    <ButtonLink href={`/projekte/${clip.source_id}/clips/${clip.id}/hooks`} size="sm" variant="ghost">
                      Hook-Studio
                    </ButtonLink>
                    <ButtonLink href={`/projekte/${clip.source_id}/clips`} size="sm" variant="ghost">
                      Clip-Karte
                    </ButtonLink>
                  </div>
                </>
              )}
            </GlassCard>
          );
        })}
      </div>

      <GlassCard padding="lg" className="mt-5">
        <ExperimentDecision
          experimentId={id}
          status={experiment.status}
          winner={experiment.winner_clip_id ? (experiment.winner_clip_id === a?.id ? "A" : "B") : null}
          decidedAt={experiment.decided_at}
          confidence={confidence}
          ready={check.ready}
          reasons={check.reasons}
          metricLabel={successMetricLabel(sa ?? sb)}
        />
      </GlassCard>
    </PageShell>
  );
}
