"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { PIPELINE_STEPS, STATUS_LABELS, isTerminalStatus } from "@/lib/pipeline";
import type { CandidateCount, PipelineEvent, PipelineStep, SourceStatus } from "@/lib/repo/types";

interface Props {
  sourceId: string;
  initialStatus: SourceStatus;
  initialStatusMessage: string | null;
  initialEvents: PipelineEvent[];
  hasTranscript: boolean;
  candidateCount: CandidateCount;
}

interface StepView {
  state: StatusCheckState | "skipped";
  progress: number | null;
  message: string | null;
  at: string | null;
}

function deriveSteps(events: PipelineEvent[]): Record<PipelineStep, StepView> {
  const views = {} as Record<PipelineStep, StepView>;
  for (const def of PIPELINE_STEPS) {
    views[def.key] = { state: "idle", progress: null, message: null, at: null };
  }
  for (const e of events) {
    const v = views[e.step];
    if (!v) continue;
    v.at = e.at;
    if (e.message) v.message = e.message;
    if (e.progress != null) v.progress = e.progress;
    if (e.status === "started") v.state = "active";
    else if (e.status === "progress") v.state = "active";
    else if (e.status === "finished") {
      v.state = "done";
      v.progress = 1;
    } else if (e.status === "failed") v.state = "error";
    else if (e.status === "skipped") v.state = "skipped";
  }
  return views;
}

function timeOf(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* Pipeline-Schritte als Live-Ansicht über Server-Sent Events */
export function PipelineLive({ sourceId, initialStatus, initialStatusMessage, initialEvents, hasTranscript, candidateCount }: Props) {
  const [events, setEvents] = useState<PipelineEvent[]>(initialEvents);
  const [status, setStatus] = useState<SourceStatus>(initialStatus);
  const [statusMessage, setStatusMessage] = useState<string | null>(initialStatusMessage);
  const [connection, setConnection] = useState<"idle" | "live" | "closed" | "error">(() =>
    isTerminalStatus(initialStatus) ? "closed" : "idle",
  );

  useEffect(() => {
    if (isTerminalStatus(initialStatus)) return;
    const lastId = initialEvents.reduce((max, e) => Math.max(max, e.id), 0);
    const es = new EventSource(`/api/projects/${sourceId}/events?after=${lastId}`);
    es.addEventListener("hello", () => setConnection("live"));
    es.addEventListener("pipeline", (msg) => {
      const e = JSON.parse((msg as MessageEvent<string>).data) as PipelineEvent;
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e]));
    });
    es.addEventListener("status", (msg) => {
      const s = JSON.parse((msg as MessageEvent<string>).data) as { status: SourceStatus; status_message: string | null };
      setStatus(s.status);
      setStatusMessage(s.status_message);
    });
    es.addEventListener("done", () => {
      setConnection("closed");
      es.close();
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) setConnection("closed");
      else setConnection("error");
    };
    return () => es.close();
  }, [sourceId, initialStatus, initialEvents]);

  const steps = useMemo(() => deriveSteps(events), [events]);
  const failed = status === "failed";
  const hasCandidates = status === "ready" && candidateCount.total > 0;

  return (
    <GlassCard padding="lg" selected={connection === "live"}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium">Pipeline</h2>
        <div className="flex items-center gap-2">
          {connection === "live" && (
            <span className="flex items-center gap-2 text-xs text-ai-soft">
              <span className="h-1.5 w-1.5 rounded-full bg-ai-soft" aria-hidden="true" />
              live
            </span>
          )}
          {connection === "error" && <span className="text-xs text-attention">Verbindung unterbrochen, versuche erneut</span>}
          <Badge tone={failed ? "attention" : isTerminalStatus(status) ? "neutral" : "ai"}>{STATUS_LABELS[status]}</Badge>
        </div>
      </div>

      <ol className="flex flex-col">
        {PIPELINE_STEPS.map((def, i) => {
          const v = steps[def.key];
          const skipped = v.state === "skipped";
          const state: StatusCheckState = v.state === "skipped" ? "idle" : v.state;
          const isLast = i === PIPELINE_STEPS.length - 1;
          return (
            <li key={def.key} className={cn("relative flex gap-4", skipped && "opacity-50")}>
              <div className="flex flex-col items-center">
                <StatusCheck state={state} size={32} label={`${def.label}: ${v.state === "skipped" ? "übersprungen" : state}`} />
                {!isLast && <span className="my-1 w-px flex-1 bg-line" aria-hidden="true" />}
              </div>
              <div className={cn("flex-1 pb-6", isLast && "pb-0")}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <p className={cn("font-medium", v.state === "error" ? "text-attention" : "text-text")}>
                    {def.label}
                  </p>
                  {v.at && !skipped && <span className="font-mono text-xs text-text-3">{timeOf(v.at)}</span>}
                </div>
                <p className={cn("mt-0.5 text-sm", v.state === "error" ? "text-attention" : "text-text-2")}>
                  {v.message ?? def.description}
                </p>
                {v.state === "active" && (
                  <div
                    className="mt-3 h-1 w-full overflow-hidden rounded-pill bg-white/10"
                    role="progressbar"
                    aria-label={`${def.label} Fortschritt`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round((v.progress ?? 0) * 100)}
                  >
                    <div
                      className="transition-soft h-full rounded-pill bg-ai-soft"
                      style={{ width: `${Math.max(4, Math.round((v.progress ?? 0) * 100))}%` }}
                    />
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {failed && (
        <p className="mt-6 rounded-inner border border-attention/50 bg-attention/10 p-4 text-sm text-text">
          {statusMessage ?? "Die Verarbeitung ist fehlgeschlagen. Bitte prüfe die Datei und lade sie erneut hoch."}
        </p>
      )}

      {status === "ready" && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
          <p className="text-sm text-text-2">
            {hasCandidates
              ? `${candidateCount.gate_passed} von ${candidateCount.total} erfüllen alle Pflichtkriterien.${
                  candidateCount.accepted > 0 ? ` ${candidateCount.accepted} angenommen.` : ""
                }`
              : hasTranscript
                ? "Transkript liegt vor. Prüfe unsichere Wörter und Sprechernamen."
                : (statusMessage ?? "Verarbeitung abgeschlossen.")}
          </p>
          <div className="flex flex-wrap gap-2">
            {hasTranscript && (
              <Link
                href={`/projekte/${sourceId}/transkript`}
                className={cn(
                  "transition-soft inline-flex h-10 items-center rounded-pill px-5 text-sm font-medium",
                  hasCandidates
                    ? "border border-line-strong text-text hover:border-white/40 hover:bg-white/5"
                    : "bg-text text-black hover:bg-white",
                )}
              >
                Transkript öffnen
              </Link>
            )}
            {hasCandidates && (
              <Link
                href={`/projekte/${sourceId}/review`}
                className="transition-soft inline-flex h-10 items-center rounded-pill bg-text px-5 text-sm font-medium text-black hover:bg-white"
              >
                Kandidaten prüfen
              </Link>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
