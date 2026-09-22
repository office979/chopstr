"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { cn } from "@/components/ui/cn";
import { SilentPreview } from "@/components/clips/SilentPreview";
import type { Candidate, CaptionVersion, Clip, HookVersion, PipelineEvent } from "@/lib/repo/types";
import { structureLabel } from "@/lib/candidates/labels";
import {
  CLIP_STATUS_LABELS,
  PLATFORM_LABELS,
  RENDER_STAGES,
  RENDER_STAGE_LABELS,
  formatClipDuration,
  formatLoudness,
  mediaUrl,
} from "@/lib/clips/labels";
import { RENDER_STEP } from "@/lib/pipeline";
import { compositionDuration } from "@/lib/clips/render-demo";
import { PLATFORM_DEFAULT_PRESET } from "@/lib/clips/presets";

interface Props {
  sourceId: string;
  initialClips: Clip[];
  candidates: Candidate[];
  initialEvents: PipelineEvent[];
  mediaBase: string | null;
  demo: boolean;
  highlightColor?: string;
  lowerThird: { name: string; role: string } | null;
}

interface ApiError {
  error?: string;
}

interface ClipDetail {
  hook: HookVersion | null;
  captions: CaptionVersion | null;
}

function isSettled(c: Clip): boolean {
  return c.status === "rendered" || c.status === "failed" || c.status === "exported";
}

function isDone(c: Clip): boolean {
  return c.status === "rendered" || c.status === "exported";
}

function checkState(c: Clip): StatusCheckState {
  if (c.status === "failed") return "error";
  if (c.status === "rendering") return "active";
  if (isDone(c)) return "done";
  return "idle";
}

/* Letztes Render-Ereignis je Clip (payload.clip_id) */
function latestEventByClip(events: PipelineEvent[]): Map<string, PipelineEvent> {
  const out = new Map<string, PipelineEvent>();
  for (const e of events) {
    const clipId = e.payload && typeof e.payload.clip_id === "string" ? e.payload.clip_id : null;
    if (clipId) out.set(clipId, e);
  }
  return out;
}

/* Je Kandidat: sind alle Clips fertig? */
function doneByCandidate(clips: Clip[]): Map<string, boolean> {
  const out = new Map<string, boolean>();
  for (const c of clips) {
    const key = c.candidate_id ?? "ohne";
    out.set(key, (out.get(key) ?? true) && isDone(c));
  }
  return out;
}

function snippet(text: string, max = 120): string {
  const plain = text.replace(/^SPEAKER_\d+:\s*/gm, "").replace(/\s+/g, " ").trim();
  return plain.length > max ? `${plain.slice(0, max).replace(/\s+\S*$/, "")} …` : plain;
}

/* Clip-Übersicht: Pakete je Kandidat, Karten je Clip, Fortschritt live über SSE (step = 'render').
 * Spektrum-Glitch auf der Gruppenkarte, wenn alle Clips eines Pakets fertig werden (nur beim Übergang). */
export function ClipBoard({ sourceId, initialClips, candidates, initialEvents, mediaBase, demo, highlightColor, lowerThird }: Props) {
  const [clips, setClips] = useState<Clip[]>(initialClips);
  const [events, setEvents] = useState<PipelineEvent[]>(initialEvents);
  const [connection, setConnection] = useState<"idle" | "live" | "closed" | "error">("idle");
  const [streamKey, setStreamKey] = useState(0);
  const [glitchGroups, setGlitchGroups] = useState<Set<string>>(new Set());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, ClipDetail>>({});
  const clipsRef = useRef<Clip[]>(initialClips);

  const groups = useMemo(() => {
    const byCandidate = new Map<string, Clip[]>();
    for (const c of clips) {
      const key = c.candidate_id ?? "ohne";
      byCandidate.set(key, [...(byCandidate.get(key) ?? []), c]);
    }
    return [...byCandidate.entries()].map(([candidateId, list]) => ({
      candidateId,
      candidate: candidates.find((k) => k.id === candidateId) ?? null,
      clips: list,
      rendered: list.filter(isDone).length,
    }));
  }, [clips, candidates]);

  /* Übergang „alle gerendert“ je Paket erkennen: Vergleich alter und neuer Clip-Stand aus dem Stream,
   * nicht beim Laden der Seite. Der Glitch dauert 900 ms (globals.css). */
  const applyClips = useCallback((next: Clip[]) => {
    const before = doneByCandidate(clipsRef.current);
    const after = doneByCandidate(next);
    const fresh = [...after.entries()].filter(([id, all]) => all && before.get(id) === false).map(([id]) => id);
    clipsRef.current = next;
    setClips(next);
    if (fresh.length === 0) return;
    setGlitchGroups((cur) => new Set([...cur, ...fresh]));
    window.setTimeout(() => {
      setGlitchGroups((cur) => {
        const copy = new Set(cur);
        for (const id of fresh) copy.delete(id);
        return copy;
      });
    }, 1000);
  }, []);

  /* SSE: nur solange ein Clip nicht abgeschlossen ist; streamKey erzwingt einen Neustart nach „Neu rendern“ */
  useEffect(() => {
    if (clips.every(isSettled)) return undefined;
    const lastId = events.reduce((max, e) => Math.max(max, e.id), 0);
    const es = new EventSource(`/api/projects/${sourceId}/clips/events?after=${lastId}`);
    es.addEventListener("hello", () => setConnection("live"));
    es.addEventListener("render", (msg) => {
      const e = JSON.parse((msg as MessageEvent<string>).data) as PipelineEvent;
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e]));
    });
    es.addEventListener("clips", (msg) => {
      const data = JSON.parse((msg as MessageEvent<string>).data) as { clips: Clip[] };
      applyClips(data.clips);
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
    /* events bewusst nicht als Abhängigkeit: der Stream läuft weiter, bis alle Clips abgeschlossen sind */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId, streamKey, applyClips, clips.every(isSettled)]);

  const latest = useMemo(() => latestEventByClip(events), [events]);
  const allSettled = clips.every(isSettled);
  const live = connection === "live" && !allSettled;

  const rerender = useCallback(
    async (clip: Clip) => {
      setBusyId(clip.id);
      setMessage(null);
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}/render`, { method: "POST" });
        const data = (await res.json()) as ApiError & { clip?: Clip; signaled?: boolean; demo?: boolean };
        if (!res.ok || !data.clip) throw new Error(data.error ?? "Render konnte nicht angestoßen werden");
        applyClips(clipsRef.current.map((c) => (c.id === clip.id ? { ...data.clip!, status: "rendering" } : c)));
        setDetails((prev) => {
          const copy = { ...prev };
          delete copy[clip.id];
          return copy;
        });
        setStreamKey((k) => k + 1);
        setMessage({
          tone: "ok",
          text: data.signaled
            ? `Render für ${PLATFORM_LABELS[clip.platform]} angestoßen.`
            : data.demo
              ? `Demo-Render für ${PLATFORM_LABELS[clip.platform]} läuft.`
              : `Render für ${PLATFORM_LABELS[clip.platform]} vorgemerkt. Er startet, sobald der Worker erreichbar ist.`,
        });
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Render konnte nicht angestoßen werden" });
      } finally {
        setBusyId(null);
      }
    },
    [sourceId, applyClips],
  );

  const togglePreview = useCallback(
    async (clip: Clip) => {
      if (previewId === clip.id) {
        setPreviewId(null);
        return;
      }
      setPreviewId(clip.id);
      if (details[clip.id]) return;
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}`);
        const data = (await res.json()) as ApiError & ClipDetail;
        if (!res.ok) throw new Error(data.error ?? "Clip konnte nicht geladen werden");
        setDetails((prev) => ({ ...prev, [clip.id]: { hook: data.hook ?? null, captions: data.captions ?? null } }));
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Clip konnte nicht geladen werden" });
      }
    },
    [sourceId, previewId, details],
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-text-2">
          Paket: {groups.length} {groups.length === 1 ? "Kandidat" : "Kandidaten"}, {clips.filter(isDone).length} von {clips.length} Clips gerendert.
        </p>
        <div className="flex items-center gap-2 text-xs">
          {live && (
            <span className="flex items-center gap-2 text-ai-soft">
              <span className="h-1.5 w-1.5 rounded-full bg-ai-soft" aria-hidden="true" />
              {RENDER_STEP.label} live
            </span>
          )}
          {connection === "error" && !allSettled && <span className="text-attention">Verbindung unterbrochen, versuche erneut</span>}
          {demo && <Badge tone="ai">Demo-Render</Badge>}
        </div>
      </div>

      {message && (
        <p
          role="status"
          aria-live="polite"
          className={cn("rounded-inner border px-4 py-3 text-sm", message.tone === "ok" ? "border-line text-text" : "border-attention/50 bg-attention/10 text-text")}
        >
          {message.text}
        </p>
      )}

      {groups.map((g, gi) => (
        <GlassCard key={g.candidateId} padding="lg" className={cn("flex flex-col gap-5", glitchGroups.has(g.candidateId) && "spectrum-glitch")}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-wide text-text-2">Paket {gi + 1}</p>
              <h2 className="mt-1 text-lg font-medium">{g.candidate ? structureLabel(g.candidate.structure) : "Kandidat entfernt"}</h2>
              {g.candidate && <p className="mt-1 line-clamp-2 text-sm text-text-2">{snippet(g.candidate.rubric.text)}</p>}
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm tabular-nums text-text">
                {g.rendered} von {g.clips.length} gerendert
              </span>
              {g.candidate && (
                <Link href={`/projekte/${sourceId}/review`} className="text-sm text-text-2 hover:text-text hover:underline">
                  Review
                </Link>
              )}
            </div>
          </div>

          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" aria-label={`Clips Paket ${gi + 1}`}>
            {g.clips.map((clip) => {
              const ev = latest.get(clip.id);
              const state = checkState(clip);
              const progress = clip.status === "rendering" ? (ev?.progress ?? 0) : isDone(clip) ? 1 : 0;
              const stage = ev?.payload && typeof ev.payload.stage === "string" ? ev.payload.stage : null;
              const mp4 = mediaUrl(mediaBase, clip.file_key);
              const srt = mediaUrl(mediaBase, clip.srt_key);
              const vtt = mediaUrl(mediaBase, clip.vtt_key);
              const poster = mediaUrl(mediaBase, clip.poster_key);
              const neutral = clip.render_plan?.reframe.strategy === "neutral";
              const duration = clip.duration_s ?? compositionDuration(clip);
              const detail = details[clip.id];
              const open = previewId === clip.id;
              const c2pa = clip.provenance?.c2pa;
              return (
                <li key={clip.id} className="flex min-w-0 flex-col gap-3 rounded-inner border border-line p-4">
                  <div
                    className="relative w-full overflow-hidden rounded-[12px] border border-line bg-black"
                    style={{ aspectRatio: clip.aspect === "4:5" ? "4 / 5" : "9 / 16", maxHeight: 220 }}
                  >
                    {poster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={poster} alt={`Poster ${PLATFORM_LABELS[clip.platform]}`} className="h-full w-full object-cover" />
                    ) : (
                      <div
                        aria-hidden="true"
                        className="flex h-full w-full items-end justify-between p-3"
                        style={{
                          background: "radial-gradient(ellipse at 50% 30%, rgba(91,140,255,0.22) 0%, rgba(27,26,98,0.3) 40%, rgba(0,0,0,0) 75%), #0a0a13",
                        }}
                      >
                        <span className="font-mono text-[11px] text-text-3">{clip.width && clip.height ? `${clip.width}×${clip.height}` : "Poster folgt"}</span>
                        <span className="font-mono text-[11px] text-text-3">{clip.fps ? `${clip.fps} fps` : ""}</span>
                      </div>
                    )}
                    <div className="absolute left-3 top-3 flex gap-1.5">
                      <Badge tone="ok" className="h-6 bg-black/60 px-2.5 text-[11px]">
                        {PLATFORM_LABELS[clip.platform]}
                      </Badge>
                      <Badge className="h-6 bg-black/60 px-2 font-mono text-[11px]">{clip.aspect}</Badge>
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <StatusCheck state={state} size={28} label={`${CLIP_STATUS_LABELS[clip.status]}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                        <p className={cn("text-sm font-medium", state === "error" ? "text-attention" : "text-text")}>{CLIP_STATUS_LABELS[clip.status]}</p>
                        <span className="font-mono text-xs tabular-nums text-text-2">{formatClipDuration(duration)}</span>
                      </div>
                      {clip.status === "rendering" && (
                        <>
                          <p className="mt-0.5 text-sm text-text-2">{ev?.message ?? RENDER_STEP.description}</p>
                          <div
                            className="mt-2 h-1 w-full overflow-hidden rounded-pill bg-white/10"
                            role="progressbar"
                            aria-label={`Render ${PLATFORM_LABELS[clip.platform]}`}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={Math.round(progress * 100)}
                          >
                            <div className="transition-soft h-full rounded-pill bg-ai-soft" style={{ width: `${Math.max(4, Math.round(progress * 100))}%` }} />
                          </div>
                          <ol className="mt-2 flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[11px]">
                            {RENDER_STAGES.map((s) => {
                              const idx = RENDER_STAGES.indexOf(s);
                              const cur = stage ? RENDER_STAGES.indexOf(stage as (typeof RENDER_STAGES)[number]) : -1;
                              return (
                                <li key={s} className={cn(idx < cur ? "text-text" : idx === cur ? "text-ai-soft" : "text-text-3")}>
                                  {RENDER_STAGE_LABELS[s]}
                                </li>
                              );
                            })}
                          </ol>
                        </>
                      )}
                      {clip.status === "failed" && <p className="mt-0.5 text-sm text-attention">{clip.render_error ?? "Render fehlgeschlagen, bitte erneut starten."}</p>}
                      {clip.status === "draft" && <p className="mt-0.5 text-sm text-text-2">Wartet auf den Render.</p>}
                      {isDone(clip) && clip.loudness && (
                        <p className="mt-0.5 font-mono text-xs text-text-2">
                          {formatLoudness(clip.loudness.integrated_lufs, clip.loudness.true_peak_dbtp)}
                        </p>
                      )}
                    </div>
                  </div>

                  {isDone(clip) && (
                    <div className="flex flex-wrap gap-1.5">
                      {c2pa === "signed" && <Badge tone="ok">C2PA signiert</Badge>}
                      {c2pa === "skipped" && (
                        <Badge tone="attention" title={clip.provenance.reason ?? undefined}>
                          C2PA übersprungen{clip.provenance.reason ? `: ${clip.provenance.reason}` : ""}
                        </Badge>
                      )}
                      {c2pa === "failed" && <Badge tone="attention">C2PA fehlgeschlagen{clip.provenance.reason ? `: ${clip.provenance.reason}` : ""}</Badge>}
                      {clip.ad_label && <Badge>Werbelabel: {clip.ad_label}</Badge>}
                      {clip.provenance.source_credit && <Badge>{clip.provenance.source_credit}</Badge>}
                    </div>
                  )}

                  {isDone(clip) && neutral && (
                    <p className="rounded-[12px] border border-attention/50 bg-attention/10 px-3 py-2 text-xs text-text">
                      <span className="font-medium text-attention">Reframe: neutraler Crop, kein Detektor.</span> Bildausschnitt bitte in der Vorschau prüfen.
                    </p>
                  )}
                  {isDone(clip) && clip.render_plan && !neutral && (
                    <p className="text-xs text-text-2">
                      Reframe: {clip.render_plan.reframe.strategy === "talking_head" ? "ein Sprecher" : "zwei Sprecher"}, Detektor {clip.render_plan.reframe.detector}
                    </p>
                  )}

                  {clip.cps_warnings.length > 0 && (
                    <ul className="flex flex-col gap-1 text-xs text-attention" aria-label="Lesetempo-Warnungen">
                      {clip.cps_warnings.slice(0, 3).map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                      {clip.cps_warnings.length > 3 && <li className="text-text-2">und {clip.cps_warnings.length - 3} weitere</li>}
                    </ul>
                  )}

                  <div className="mt-auto flex flex-wrap gap-1.5 border-t border-line pt-3">
                    {(
                      [
                        ["MP4", mp4],
                        ["SRT", srt],
                        ["VTT", vtt],
                      ] as const
                    ).map(([label, href]) =>
                      href ? (
                        <a
                          key={label}
                          href={href}
                          download
                          className="transition-soft inline-flex h-8 items-center rounded-pill border border-line-strong px-3 font-mono text-xs text-text hover:border-white/40 hover:bg-white/5"
                        >
                          {label}
                        </a>
                      ) : (
                        <span
                          key={label}
                          aria-disabled="true"
                          title={demo ? "Im Demo-Modus gibt es keine Dateien" : isDone(clip) ? "Datei noch nicht verfügbar" : "Erst nach dem Render"}
                          className="inline-flex h-8 cursor-not-allowed items-center rounded-pill border border-line px-3 font-mono text-xs text-text-3"
                        >
                          {label}
                        </span>
                      ),
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Link
                      href={`/projekte/${sourceId}/clips/${clip.id}/hooks`}
                      className="transition-soft inline-flex h-9 items-center rounded-pill bg-text px-4 text-sm font-medium text-black hover:bg-white"
                    >
                      Hook-Studio
                    </Link>
                    <Button size="sm" variant="ghost" onClick={() => rerender(clip)} disabled={busyId === clip.id || clip.status === "rendering"}>
                      Neu rendern
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => togglePreview(clip)} aria-expanded={open}>
                      {open ? "Vorschau schließen" : "Ton-aus-Vorschau"}
                    </Button>
                  </div>

                  {open && (
                    <div className="border-t border-line pt-4">
                      {detail ? (
                        <SilentPreview
                          aspect={clip.aspect}
                          preset={detail.captions?.preset ?? clip.render_plan?.captions.preset ?? PLATFORM_DEFAULT_PRESET[clip.platform]}
                          durationS={duration}
                          cards={detail.captions?.cards ?? []}
                          hookText={detail.hook?.onscreen_hook ?? null}
                          titleCard={clip.title_card}
                          highlightColor={highlightColor}
                          lowerThird={lowerThird}
                        />
                      ) : (
                        <p className="text-sm text-text-2" role="status">
                          Vorschau wird geladen
                        </p>
                      )}
                      {detail && !detail.captions && (
                        <p className="mt-2 text-center text-xs text-text-2">Noch keine Caption-Karten. Sie entstehen beim Render.</p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </GlassCard>
      ))}
    </div>
  );
}
