import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { Wordmark } from "@/components/brand/Wordmark";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { Timecode } from "@/components/ui/Timecode";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { STATUS_LABELS } from "@/lib/pipeline";
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

  return (
    <PageShell backgroundWord="Clips">
      <div className="mb-10 flex flex-col gap-6 sm:mb-14">
        <Wordmark width={168} className="opacity-95" />
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-[var(--tracking-display)] sm:text-5xl">Projekte</h1>
          <p className="mt-3 text-base text-text-2 sm:text-lg">
            Long-Form-Video rein, sinntreue Clips raus. Jede Auswahl wird erklärt, du gibst frei.
          </p>
        </div>
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
                <GlassCard padding="none" className="min-w-0 overflow-hidden">
                  <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-6 sm:p-6">
                    <StatusCheck state={state} size={40} label={STATUS_LABELS[s.status]} />
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/projekte/${s.id}`}
                        className="block truncate text-lg font-medium text-text hover:underline"
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
                    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
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
