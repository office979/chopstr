"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { PIPELINE_STEPS, STATUS_LABELS, isTerminalStatus } from "@/lib/pipeline";
import { playDoneSound } from "@/lib/sound";
import type { CandidateCount, PipelineEvent, PipelineStep, SourceStatus } from "@/lib/repo/types";

/* So lange bleibt „Fertig“ stehen, bevor die Clips aufgehen: lang genug, dass man den Haken sieht,
 * kurz genug, dass es nicht nach Hängen aussieht. */
const DONE_HANDOFF_MS = 1400;

interface Props {
  sourceId: string;
  initialStatus: SourceStatus;
  initialStatusMessage: string | null;
  initialEvents: PipelineEvent[];
  candidateCount: CandidateCount;
  /* Lokaler Testmodus ohne Temporal: der Worker (python -m chopstr_worker.local_worker) holt die Quelle per Polling ab */
  localWorker?: boolean;
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
  return new Date(iso).toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" });
}

/* Wie weit ist die Verarbeitung? Erledigte und übersprungene Schritte zählen voll, der laufende
 * anteilig. Der Deckel von 0,95 verhindert, dass ein Schritt, der bei 100 Prozent steht und noch
 * nicht abgeschlossen ist, die Rechnung gegen null treibt. */
function doneFraction(steps: Record<PipelineStep, StepView>): number {
  let done = 0;
  for (const def of PIPELINE_STEPS) {
    const v = steps[def.key];
    if (v.state === "done" || v.state === "skipped") done += 1;
    else if (v.state === "active") done += Math.min(0.95, v.progress ?? 0);
  }
  return done / PIPELINE_STEPS.length;
}

/* Grobe Restzeit: so lange hat der bisherige Anteil gedauert, so lange dauert der Rest vermutlich
 * auch. Mehr Rechnung wäre Genauigkeit vortäuschen. Solange zu wenig Anhaltspunkte da sind, wird
 * keine Zahl genannt — lieber ungenau als falsch. */
function remainingLabel(events: PipelineEvent[], steps: Record<PipelineStep, StepView>, now: number): string {
  const vage = "Dauert noch ein paar Minuten";
  let first: number | null = null;
  for (const e of events) {
    const t = new Date(e.at).getTime();
    if (!Number.isNaN(t) && (first === null || t < first)) first = t;
  }
  if (first === null) return vage;
  const elapsed = now - first;
  /* Unter einer halben Minute ist jede Hochrechnung geraten */
  if (elapsed < 30_000) return vage;

  const fraction = doneFraction(steps);
  if (fraction < 0.1) return vage;

  const remaining = (elapsed / fraction) * (1 - fraction);
  if (remaining > 45 * 60_000) return "Dauert noch eine ganze Weile";
  const minutes = Math.round(remaining / 60_000);
  if (minutes <= 1) return "Nur noch einen Moment";
  return `Noch etwa ${minutes} Minuten`;
}

/* Pipeline-Schritte als Live-Ansicht über Server-Sent Events */
export function PipelineLive({ sourceId, initialStatus, initialStatusMessage, initialEvents, candidateCount, localWorker = false }: Props) {
  const [events, setEvents] = useState<PipelineEvent[]>(initialEvents);
  const [status, setStatus] = useState<SourceStatus>(initialStatus);
  const [statusMessage, setStatusMessage] = useState<string | null>(initialStatusMessage);
  const [connection, setConnection] = useState<"idle" | "live" | "closed" | "error">(() =>
    isTerminalStatus(initialStatus) ? "closed" : "idle",
  );
  /* Kommt mit dem „done“-Ereignis. Die Prop candidateCount stammt vom Seitenaufbau und ist null,
   * wenn die Analyse beim Öffnen noch lief — sie darf hier nicht als Wahrheit gelten. */
  const [liveCandidates, setLiveCandidates] = useState<CandidateCount | null>(null);
  const counts = liveCandidates ?? candidateCount;

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
    es.addEventListener("done", (msg) => {
      const d = JSON.parse((msg as MessageEvent<string>).data) as { status: SourceStatus; candidates?: CandidateCount };
      if (d.candidates) setLiveCandidates(d.candidates);
      setConnection("closed");
      es.close();
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) setConnection("closed");
      else setConnection("error");
    };
    return () => es.close();
  }, [sourceId, initialStatus, initialEvents]);

  /* Wenn die Analyse fertig wird, während diese Seite offen ist: kurzer Klang, dann weiter zu den
   * Clips. Nur beim Übergang, nicht beim Öffnen eines längst fertigen Videos, sonst käme man
   * auf der Projektseite nie zur Ruhe. Ohne gefundene Stellen bleibt man hier. */
  const router = useRouter();
  const startedUnfinished = useRef(!isTerminalStatus(initialStatus));
  const announced = useRef(false);
  const handedOff = useRef(false);

  /* Klang, sobald die Analyse durch ist — auch dann, wenn nichts gefunden wurde. Sonst sitzt jemand
   * vor einer fertigen Seite und wartet weiter. */
  useEffect(() => {
    if (!startedUnfinished.current || announced.current) return;
    if (!isTerminalStatus(status)) return;
    announced.current = true;
    if (status === "ready") playDoneSound();
  }, [status]);

  /* Weiter zu den Clips, sobald feststeht, dass es welche gibt. Der Auswahlschritt entfällt, die
   * Clips entstehen von selbst. Nur beim Übergang, nicht beim Öffnen eines längst fertigen Videos,
   * sonst käme man auf der Projektseite nie zur Ruhe. */
  useEffect(() => {
    if (!startedUnfinished.current || handedOff.current) return;
    if (status !== "ready" || counts.total === 0) return;
    handedOff.current = true;
    const t = window.setTimeout(() => router.push(`/projekte/${sourceId}/clips`), DONE_HANDOFF_MS);
    return () => window.clearTimeout(t);
  }, [status, counts.total, router, sourceId]);

  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  /* Neustart nach einem Fehlschlag. Die Datei liegt noch, es geht also nur der Status zurück auf
   * „hochgeladen“. Die Merker müssen mit zurück: Wer die Seite erst im Zustand „fehlgeschlagen“
   * geöffnet hat, gilt sonst weiter als jemand, der nichts Laufendes gesehen hat, und bekäme am
   * Ende keine Weiterleitung. */
  async function retry() {
    setRetrying(true);
    setRetryError(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/retry`, { method: "POST" });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        setRetryError(body?.error ?? "Der Neustart hat nicht geklappt.");
        setRetrying(false);
        return;
      }
      startedUnfinished.current = true;
      announced.current = false;
      handedOff.current = false;
      setLiveCandidates(null);
      router.refresh();
    } catch {
      setRetryError("Der Neustart hat nicht geklappt. Bitte prüfe deine Verbindung.");
      setRetrying(false);
    }
  }

  const steps = useMemo(() => deriveSteps(events), [events]);
  const failed = status === "failed";
  const running = !isTerminalStatus(status);
  const hasCandidates = status === "ready" && counts.total > 0;

  /* Die Restzeit braucht eine tickende Uhr. Sie startet erst nach dem Einhängen im Browser, damit
   * der Server nicht eine Zahl vorrendert, die beim Übernehmen sofort eine andere ist. */
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!running) return;
    const tick = () => setNow(Date.now());
    /* Auch der erste Tick läuft über einen Timer und nicht direkt im Effekt: so bleibt die Uhr eine
     * Quelle von außen und löst beim Einhängen keine Kaskade aus. */
    const first = window.setTimeout(tick, 0);
    const every = window.setInterval(tick, 15_000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(every);
    };
  }, [running]);
  const remaining = running && now !== null ? remainingLabel(events, steps, now) : null;

  return (
    <GlassCard padding="lg" selected={connection === "live"}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium">
          {failed ? "Der Computer kam nicht durch" : running ? "Der Computer arbeitet" : "Der Computer ist fertig"}
        </h2>
        <div className="flex items-center gap-2">
          {remaining && <span className="text-sm text-text-2">{remaining}</span>}
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
                  {/* Uhrzeit nur bei abgeschlossenen Schritten und ohne Sekunden. Am laufenden Schritt
                      sprang sie im Sekundentakt und stand damit in Konkurrenz zur Restzeit oben, die
                      die eigentliche Frage beantwortet. */}
                  {v.at && !skipped && (v.state === "done" || v.state === "error") && (
                    <span className="font-mono text-xs text-text-3">{timeOf(v.at)}</span>
                  )}
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
                    {/* Der Balken zeigt den Fortschritt, der durchlaufende Strahl zeigt, dass gerade
                        wirklich gerechnet wird. Ohne ihn sieht ein Schritt, der lange bei derselben
                        Prozentzahl steht (CPU-Transkription), aus wie ein Absturz. */}
                    <div
                      className="transition-soft relative h-full overflow-hidden rounded-pill bg-ai-soft"
                      style={{ width: `${Math.max(4, Math.round((v.progress ?? 0) * 100))}%` }}
                    >
                      <span className="pipeline-sheen" aria-hidden="true" />
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Hier stand der Befehl, mit dem man den lokalen Worker startet. Der gehört in die Anleitung
       * (README), nicht auf die Seite, auf der jemand auf sein Video wartet. Die Zeile bleibt aber
       * stehen: zwischen Hochladen und dem ersten Schritt passiert sonst sichtbar nichts. */}
      {localWorker && status === "uploaded" && (
        <p role="status" className="mt-6 flex flex-wrap items-center gap-2 rounded-inner border border-line px-4 py-3 text-sm text-text-2">
          <span className="h-1.5 w-1.5 rounded-full bg-ai-soft" aria-hidden="true" />
          <span>
            <span className="font-medium text-text">Die Verarbeitung startet gleich.</span> Dein Video liegt bereit, der Computer nimmt es sich als Nächstes vor.
          </span>
        </p>
      )}

      {failed && (
        <div className="mt-6 rounded-inner border border-attention/50 bg-attention/10 p-4">
          <p className="text-sm text-text">
            {statusMessage ?? "Beim Verarbeiten ist etwas schiefgegangen."}
          </p>
          <p className="mt-1 text-sm text-text-2">
            Das liegt oft an einer kurzen Störung. Versuch es noch einmal — deine Datei ist noch da und muss
            nicht neu hochgeladen werden.
          </p>
          {retryError && <p className="mt-3 text-sm text-attention">{retryError}</p>}
          <button
            type="button"
            onClick={retry}
            disabled={retrying}
            className="transition-soft mt-4 inline-flex h-10 items-center rounded-pill bg-text px-5 text-sm font-medium text-black hover:bg-white disabled:opacity-60"
          >
            {retrying ? "Wird neu gestartet" : "Noch einmal versuchen"}
          </button>
        </div>
      )}

      {/* Keine Knöpfe mehr: bei Funden geht es von selbst weiter zu den Clips, ohne Funde gibt es
       * nichts zu öffnen. Ein Knopf wäre hier nur eine zweite Möglichkeit, dasselbe zu tun. */}
      {status === "ready" && (
        <div className="mt-6 border-t border-line pt-5">
          <p className="text-sm text-text-2">
            {hasCandidates
              ? `${counts.total === 1 ? "Eine gute Stelle" : `${counts.total} gute Stellen`} gefunden. Deine Clips gehen gleich auf.`
              : "In diesem Video hat der Computer keine gute Stelle gefunden. Das passiert bei sehr kurzen Videos und wenn wenig gesprochen wird. Versuch es mit einem anderen Video."}
          </p>
        </div>
      )}
    </GlassCard>
  );
}
