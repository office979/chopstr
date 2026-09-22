import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { Timecode } from "@/components/ui/Timecode";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { STATUS_LABELS } from "@/lib/pipeline";
import { DeleteSourceButton } from "@/components/projects/DeleteSourceButton";
import { formatDate } from "@/lib/format";
import type { Source } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

export const metadata = { title: "Projekte" };

function checkState(status: Source["status"]): StatusCheckState {
  if (status === "ready") return "done";
  if (status === "failed") return "error";
  if (status === "uploaded" || status === "uploading") return "idle";
  return "active";
}

/* Grober Fortschritt aus dem Status (Details liefert die Projektseite live) */
function progressOf(status: Source["status"]): number {
  switch (status) {
    case "uploading":
      return 0.05;
    case "uploaded":
      return 0.1;
    case "ingesting":
      return 0.25;
    case "transcribing":
      return 0.5;
    case "analyzing":
      return 0.75;
    case "scoring":
      return 0.9;
    case "ready":
      return 1;
    default:
      return 0;
  }
}

export default async function ProjectsPage() {
  const session = await requireSession();
  const canDelete = can(session.role, "source.delete");
  const repo = getRepo();
  const sources = await repo.listSources();
  const counts = new Map(
    await Promise.all(
      sources.filter((s) => s.status === "ready").map(async (s) => [s.id, await repo.countCandidates(s.id)] as const),
    ),
  );
  const clipCounts = new Map(
    await Promise.all(sources.filter((s) => s.status === "ready").map(async (s) => [s.id, await repo.countClips(s.id)] as const)),
  );

  const readyCount = sources.filter((s) => s.status === "ready").length;
  const failedCount = sources.filter((s) => s.status === "failed").length;
  const activeCount = sources.filter((s) => checkState(s.status) === "active").length;
  const openCandidates = [...counts.values()].reduce((n, c) => n + Math.max(0, c.total - c.accepted - c.rejected), 0);
  const renderedClips = [...clipCounts.values()].reduce((n, c) => n + c.rendered, 0);

  return (
    <PageShell width="wide">
      <section className="relative mb-8 overflow-hidden rounded-card bg-[linear-gradient(135deg,#020cf5_0%,#1422ff_45%,#1b1a62_100%)] p-6 sm:p-8">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-3xl" />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-[var(--tracking-display)] text-white sm:text-4xl">Projekte</h1>
            <p className="mt-2 text-[15px] text-white/75">
              Hallo {session.displayName.split(/\s+/)[0]}. Long-Form-Video rein, sinntreue Clips raus.
            </p>
          </div>
        </div>
        <dl className="relative mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Projekte gesamt" value={sources.length} hint={`${readyCount} bereit`} />
          <Stat label="In Verarbeitung" value={activeCount} hint={activeCount > 0 ? "KI arbeitet gerade" : "nichts in der Warteschlange"} />
          <Stat label="Offene Kandidaten" value={openCandidates} hint="warten auf deine Freigabe" />
          <Stat label="Clips gerendert" value={renderedClips} hint={failedCount > 0 ? `${failedCount} Projekt(e) fehlgeschlagen` : "bereit zum Veröffentlichen"} />
        </dl>
      </section>

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-medium">Alle Projekte</h2>
        <span className="text-sm text-text-3">{sources.length} {sources.length === 1 ? "Projekt" : "Projekte"}</span>
      </div>

      {sources.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch keine Projekte</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">
            Lade eine Podcast-Folge, eine Keynote oder ein Interview hoch. Die Transkription läuft in der EU.
          </p>
          <div className="mt-6 flex justify-center">
            <ButtonLink href="/upload">Erstes Projekt anlegen</ButtonLink>
          </div>
        </GlassCard>
      ) : (
        <ul className="grid gap-4 sm:gap-5">
          {sources.map((s) => {
            const state = checkState(s.status);
            const progress = progressOf(s.status);
            const count = counts.get(s.id);
            const hasCandidates = (count?.total ?? 0) > 0;
            const clipCount = clipCounts.get(s.id);
            return (
              <li key={s.id} className="min-w-0">
                <GlassCard padding="none" className="group min-w-0 overflow-hidden hover:border-brand/60 hover:bg-white/[0.07]">
                  <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-6 sm:p-6">
                    <StatusCheck state={state} size={40} label={STATUS_LABELS[s.status]} />
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/projekte/${s.id}`}
                        className="block truncate text-lg font-medium text-text after:absolute after:inset-0 after:content-[''] group-hover:text-white"
                      >
                        {s.title}
                      </Link>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-2">
                        <span>
                          Dauer <Timecode seconds={s.duration_s} className="text-text-2" />
                        </span>
                        <span>Hochgeladen {formatDate(s.created_at)}</span>
                        {s.expected_speakers != null && (
                          <span>{s.expected_speakers} Sprecher</span>
                        )}
                      </div>
                    </div>
                    <div className="relative z-10 flex flex-wrap items-center gap-2 sm:justify-end">
                      <Badge tone={state === "error" ? "attention" : state === "active" ? "ai" : "neutral"}>
                        {STATUS_LABELS[s.status]}
                      </Badge>
                      {hasCandidates && count && (
                        <Badge tone="ok">
                          {count.total} {count.total === 1 ? "Kandidat" : "Kandidaten"}
                        </Badge>
                      )}
                      {clipCount && clipCount.total > 0 && (
                        <Badge tone={clipCount.rendering > 0 ? "ai" : "ok"}>
                          {clipCount.rendered > 0
                            ? `${clipCount.rendered} ${clipCount.rendered === 1 ? "Clip" : "Clips"} gerendert`
                            : `${clipCount.total} ${clipCount.total === 1 ? "Clip" : "Clips"} in Arbeit`}
                        </Badge>
                      )}
                      {clipCount && clipCount.total > 0 && (
                        <ButtonLink href={`/projekte/${s.id}/clips`} size="sm" variant="ghost">
                          Clips
                        </ButtonLink>
                      )}
                      {s.status === "ready" && hasCandidates ? (
                        <>
                          <ButtonLink href={`/projekte/${s.id}/transkript`} size="sm" variant="ghost">
                            Transkript
                          </ButtonLink>
                          <ButtonLink href={`/projekte/${s.id}/review`} size="sm">
                            Review öffnen
                          </ButtonLink>
                        </>
                      ) : s.status === "ready" ? (
                        <ButtonLink href={`/projekte/${s.id}/transkript`} size="sm">
                          Transkript öffnen
                        </ButtonLink>
                      ) : (
                        <ButtonLink href={`/projekte/${s.id}`} size="sm" variant="ghost">
                          Details
                        </ButtonLink>
                      )}
                      {canDelete && <DeleteSourceButton sourceId={s.id} title={s.title} />}
                    </div>
                  </div>
                  <div className="h-[3px] w-full bg-white/5" aria-hidden="true">
                    <div
                      className={state === "active" ? "h-full bg-ai-soft" : state === "error" ? "h-full bg-attention" : "h-full bg-text/70"}
                      style={{ width: `${Math.round(progress * 100)}%` }}
                    />
                  </div>
                </GlassCard>
              </li>
            );
          })}
        </ul>
      )}
    </PageShell>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="rounded-inner bg-[#07071a]/80 p-4 backdrop-blur-sm sm:p-5">
      <dt className="text-sm text-text-2">{label}</dt>
      <dd className="mt-2 font-mono text-3xl font-medium tabular-nums text-text">{String(value).padStart(2, "0")}</dd>
      <dd className="mt-1 text-xs text-text-3">{hint}</dd>
    </div>
  );
}
