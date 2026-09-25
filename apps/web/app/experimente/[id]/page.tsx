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
import { DEFAULT_CAPABILITIES, erfolgKennzahlFuer } from "@/lib/publishing/capabilities";
import { CONNECTION_PLATFORM_LABELS, connectionPlatformFor } from "@/lib/publishing/platforms";
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
  /* Was kann die Zielplattform überhaupt liefern?
   *
   * Der Test misst die Folgequote. Die Fähigkeitstabelle sagt, dass TikTok, Instagram und
   * LinkedIn neue Folgende keinem einzelnen Beitrag zuordnen - dort kommt diese Zahl nie. Ohne
   * diese Auskunft las der Test eine fehlende Zahl als „noch nicht da" und wartete auf etwas, das
   * nicht kommt. Die tatsächlich benutzte Verbindung sticht, denn ihre Fähigkeiten können
   * abweichen; ohne Publikation gilt der Standard der Plattform. */
  const genutzteVerbindung = publications.find((p) => p.connection_id)?.connection_id ?? null;
  const verbindung = genutzteVerbindung ? await pub.getConnection(genutzteVerbindung) : null;
  const zielPlattform = verbindung?.platform ?? (a ? connectionPlatformFor(a.platform) : "manual");
  const caps = verbindung?.capabilities ?? DEFAULT_CAPABILITIES[zielPlattform];
  const erfolg = erfolgKennzahlFuer(caps, CONNECTION_PLATFORM_LABELS[zielPlattform]);
  const check = decisionCheck(experiment, sa, sb, erfolg);
  const confidence = experiment.confidence ?? (sa && sb ? posteriorAOverB(sa, sb, id) : null);
  const source = a ? await repo.getSource(a.source_id) : null;

  return (
    <PageShell width="default" backgroundWord="A/B">
      {/* „Mindestexposure … Views je Variante" war Fachsprache. Was hier zählt, ist die
          Bedingung: wann darf überhaupt entschieden werden. */}
      <PageHeader
        eyebrow={`Test${source ? ` · ${source.title}` : ""}`}
        title={experiment.hypothesis ?? "Experiment"}
        description={`Angelegt ${formatDateTime(experiment.created_at)} · Entschieden wird frühestens 48 Stunden nach dem Posten und ab ${experiment.min_exposure.toLocaleString("de-AT")} Aufrufen je Fassung`}
        actions={
          <>
            <ButtonLink href="/experimente" variant="ghost">
              Alle Tests
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
                <h2 className="text-lg font-medium">Fassung {label}</h2>
                <div className="flex gap-1.5">
                  {winner && <Badge tone="ok">Gewinner</Badge>}
                  {clip && <Badge>{PLATFORM_LABELS[clip.platform]}</Badge>}
                </div>
              </div>
              {!clip ? (
                <p className="text-sm text-text-2">Für diese Fassung gibt es noch keinen Clip.</p>
              ) : (
                <>
                  {/* Was an dieser Fassung anders ist - der einzige Unterschied zwischen A und B.
                      „Hook" und „On-Screen" sind Fachwörter; gemeint sind der gesprochene Einstieg
                      und der Text, der dabei im Bild steht. */}
                  <div className="text-sm">
                    <p className="text-text-2">Gesprochener Einstieg ({patternLabel(hook?.pattern)})</p>
                    <p className="mt-1 text-text">{hook?.spoken_hook ?? "Noch kein Einstieg geschrieben"}</p>
                    {hook?.onscreen_hook && <p className="mt-1 text-xs text-text-2">Im Bild: {hook.onscreen_hook}</p>}
                  </div>
                  {/* Die Zahlen mit ihrer Herkunft. Ohne die letzte Zeile weiss niemand, ob hier
                      Zahlen von gestern oder von vor drei Wochen stehen - und ob sie von Hand
                      eingetragen oder von der Plattform geholt wurden. */}
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    <dt className="text-text-2">Stand des Clips</dt>
                    <dd>{CLIP_STATUS_LABELS[clip.status]}</dd>
                    <dt className="text-text-2">Gepostet</dt>
                    <dd>{stats?.published_at ? formatDateTime(stats.published_at) : "noch nicht"}</dd>
                    <dt className="text-text-2">Aufrufe</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.views)}</dd>
                    <dt className="text-text-2">Neue Folgende</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.follows)}</dd>
                    <dt className="text-text-2">Je 1.000 Aufrufe</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.follows_per_1k, 2)}</dd>
                    <dt className="text-text-2">Gespeichert</dt>
                    <dd className="font-mono tabular-nums">{n(stats?.saves)}</dd>
                    <dt className="text-text-2">Woher die Zahlen kommen</dt>
                    <dd>{stats?.window === "manual" ? "Von Hand eingetragen" : (stats?.window ?? "Noch keine Zahlen")}</dd>
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
                      Einstieg bearbeiten
                    </ButtonLink>
                    <ButtonLink href={`/projekte/${clip.source_id}/clips`} size="sm" variant="ghost">
                      Zum Clip
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
          metricLabel={successMetricLabel(sa ?? sb, erfolg)}
        />
        {/* Warum nach dieser Zahl verglichen wird. Steht hier, weil „Save-Quote" ohne Begründung
            nach einem Zufall aussieht - und weil eine fehlende Zahl nicht null bedeutet, sondern
            dass diese Plattform sie nicht herausgibt. */}
        <p className="mt-3 text-xs text-text-2">{erfolg.satz}</p>
      </GlassCard>
    </PageShell>
  );
}
