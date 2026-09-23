"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { cn } from "@/components/ui/cn";
import { SilentPreview, type PreviewFont } from "@/components/clips/SilentPreview";
import { Modal } from "@/components/ui/Modal";
import { ClipApproval } from "./ClipApproval";
import type { Aspect, Candidate, CaptionVersion, Clip, GuestApproval, HookVersion, PipelineEvent } from "@/lib/repo/types";
import { EXPORT_BLOCKED_MESSAGE, exportBlocked, latestByClip } from "@/lib/guest/approval";
import { structureLabel } from "@/lib/candidates/labels";
import {
  CLIP_STATUS_LABELS,
  ASPECT_LABELS,
  PLATFORM_LABELS,
  formatClipDuration,
  mediaUrl,
} from "@/lib/clips/labels";
import { RENDER_STEP } from "@/lib/pipeline";
import { compositionDuration } from "@/lib/clips/render-demo";
import { PLATFORM_DEFAULT_PRESET } from "@/lib/clips/presets";
import type { ClipExtras, Series } from "@/lib/repo/types-publishing";
import { ClipSeries } from "./ClipSeries";

/* Serien-Zuordnung je Clip. Posten, Bildausschnitt und Experimente stehen nicht mehr auf der Karte. */
export interface ClipBoardPublishing {
  series: Series[];
  extras: Record<string, ClipExtras>;
  canSeries: boolean;
}

interface Props {
  sourceId: string;
  initialClips: Clip[];
  candidates: Candidate[];
  initialEvents: PipelineEvent[];
  mediaBase: string | null;
  demo: boolean;
  highlightColor?: string;
  lowerThird: { name: string; role: string } | null;
  /* Gast-Freigabe (Block B) */
  guestApprovals: GuestApproval[];
  canRequestGuest: boolean;
  planAllowsGuest: boolean;
  planName: string;
  canDelete: boolean;
  previewFont: PreviewFont | null;
  publishing?: ClipBoardPublishing;
}

interface ApiError {
  error?: string;
}

interface ClipDetail {
  hook: HookVersion | null;
  captions: CaptionVersion | null;
  guest_approval?: GuestApproval | null;
}

function isSettled(c: Clip): boolean {
  return c.status === "rendered" || c.status === "failed" || c.status === "exported";
}

function isDone(c: Clip): boolean {
  return c.status === "rendered" || c.status === "exported";
}

/* Seitenverhältnis als CSS-Wert. Vorher wurde alles außer 4:5 als 9:16 dargestellt, ein 16:9-Clip
 * (Hochformat-Schalter aus) bekam also einen hochkanten Rahmen und wurde im Bild gestaucht. */
const ASPECT_RATIO_CSS: Record<Aspect, string> = {
  "9:16": "9 / 16",
  "4:5": "4 / 5",
  "1:1": "1 / 1",
  "16:9": "16 / 9",
};

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
export function ClipBoard({
  sourceId,
  initialClips,
  candidates,
  initialEvents,
  mediaBase,
  demo,
  highlightColor,
  lowerThird,
  guestApprovals,
  canRequestGuest,
  planAllowsGuest,
  planName,
  canDelete,
  previewFont,
  publishing,
}: Props) {
  const [clips, setClips] = useState<Clip[]>(initialClips);
  const [extras, setExtras] = useState<Record<string, ClipExtras>>(publishing?.extras ?? {});
  const [approvals, setApprovals] = useState<Map<string, GuestApproval>>(() => latestByClip(guestApprovals));
  const [deleteTarget, setDeleteTarget] = useState<Clip | null>(null);
  /* Clip, der gerade groß in einem Fenster läuft. Nicht Vollbild: das Fenster bleibt Teil der Seite. */
  const [zoomClip, setZoomClip] = useState<Clip | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [events, setEvents] = useState<PipelineEvent[]>(initialEvents);
  const [connection, setConnection] = useState<"idle" | "live" | "closed" | "error">("idle");
  const [glitchGroups, setGlitchGroups] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
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

  /* SSE: nur solange ein Clip nicht abgeschlossen ist */
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
  }, [sourceId, applyClips, clips.every(isSettled)]);

  const latest = useMemo(() => latestEventByClip(events), [events]);
  const allSettled = clips.every(isSettled);
  const live = connection === "live" && !allSettled;

  /* Klick auf die kleine Vorschau: Fenster auf und, falls noch nicht geschehen, Hook und Untertitel
   * nachladen. Die werden für die Attrappe gebraucht, wenn der Clip noch nicht gebaut ist. */
  const openZoom = useCallback(
    async (clip: Clip) => {
      setZoomClip(clip);
      if (details[clip.id]) return;
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}`);
        const data = (await res.json()) as ApiError & ClipDetail;
        if (!res.ok) throw new Error(data.error ?? "Clip konnte nicht geladen werden");
        setDetails((prev) => ({ ...prev, [clip.id]: { hook: data.hook ?? null, captions: data.captions ?? null } }));
        if (data.guest_approval) {
          const fresh = data.guest_approval;
          setApprovals((prev) => new Map(prev).set(clip.id, fresh));
        }
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Clip konnte nicht geladen werden" });
      }
    },
    [sourceId, details],
  );

  const onRequested = useCallback((approval: GuestApproval) => {
    setApprovals((prev) => new Map(prev).set(approval.clip_id, approval));
    applyClips(clipsRef.current.map((c) => (c.id === approval.clip_id ? { ...c, guest_approval_required: true } : c)));
  }, [applyClips]);

  const refreshApproval = useCallback(
    async (clip: Clip) => {
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}`);
        const data = (await res.json()) as ApiError & ClipDetail;
        if (!res.ok) throw new Error(data.error ?? "Status konnte nicht geladen werden");
        if (data.guest_approval) {
          const fresh = data.guest_approval;
          setApprovals((prev) => new Map(prev).set(clip.id, fresh));
        }
        setMessage({ tone: "ok", text: "Freigabestatus aktualisiert." });
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Status konnte nicht geladen werden" });
      }
    },
    [sourceId],
  );

  const deleteClip = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${deleteTarget.id}`, { method: "DELETE" });
      const data = (await res.json()) as ApiError & { message?: string };
      if (!res.ok) throw new Error(data.error ?? "Löschen fehlgeschlagen");
      applyClips(clipsRef.current.filter((c) => c.id !== deleteTarget.id));
      setMessage({ tone: "ok", text: data.message ?? "Löschung eingeplant, Nachweis folgt." });
      setDeleteTarget(null);
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Löschen fehlgeschlagen" });
    } finally {
      setDeleting(false);
    }
  }, [deleteTarget, sourceId, applyClips]);

  return (
    <div className="flex flex-col gap-5">
      <Modal open={deleteTarget != null} onClose={() => !deleting && setDeleteTarget(null)} title="Clip löschen" description="Video, Untertitel, Poster und Textversionen dieses Clips werden gelöscht. Der Löschnachweis bleibt im Audit-Log.">
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleteTarget(null)} disabled={deleting}>
            Abbrechen
          </Button>
          <Button variant="danger" className="border border-danger/50" onClick={() => void deleteClip()} disabled={deleting}>
            {deleting ? "Wird gelöscht" : `${deleteTarget ? PLATFORM_LABELS[deleteTarget.platform] : "Clip"} löschen`}
          </Button>
        </div>
      </Modal>

      {/* Clip groß ansehen: eigenes Fenster mit den Steuerelementen des Browsers, also Ton,
          Lautstärke und Spulen. Geht jetzt mit einem Klick auf die kleine Vorschau auf. */}
      <Modal
        open={zoomClip != null}
        onClose={() => setZoomClip(null)}
        title={zoomClip ? `${PLATFORM_LABELS[zoomClip.platform]}, ${ASPECT_LABELS[zoomClip.aspect]}` : "Clip"}
        description="Ton, Lautstärke und Spulen über die Steuerung im Player."
        className="max-w-[min(92vw,720px)]"
      >
        {zoomClip &&
          (mediaUrl(mediaBase, zoomClip.file_key) ? (
            <video
              src={mediaUrl(mediaBase, zoomClip.file_key) ?? undefined}
              poster={mediaUrl(mediaBase, zoomClip.poster_key) ?? undefined}
              controls
              autoPlay
              playsInline
              preload="metadata"
              aria-label={`${PLATFORM_LABELS[zoomClip.platform]} abspielen`}
              className="mx-auto max-h-[70dvh] w-auto rounded-inner border border-line-strong bg-black"
              style={{ aspectRatio: ASPECT_RATIO_CSS[zoomClip.aspect] }}
            />
          ) : details[zoomClip.id] ? (
            /* Noch nicht gebaut: Attrappe aus Hook, Untertiteln und Markenfarben */
            <div className="mx-auto max-w-[360px]">
              <SilentPreview
                aspect={zoomClip.aspect}
                preset={details[zoomClip.id].captions?.preset ?? zoomClip.render_plan?.captions.preset ?? PLATFORM_DEFAULT_PRESET[zoomClip.platform]}
                durationS={zoomClip.duration_s ?? compositionDuration(zoomClip)}
                cards={details[zoomClip.id].captions?.cards ?? []}
                hookText={details[zoomClip.id].hook?.onscreen_hook ?? null}
                titleCard={zoomClip.title_card}
                highlightColor={highlightColor}
                lowerThird={lowerThird}
                font={previewFont}
              />
              {!details[zoomClip.id].captions && (
                <p className="mt-2 text-center text-xs text-text-2">Noch keine Untertitel. Sie entstehen beim Bauen.</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-text-2" role="status">
              Vorschau wird geladen
            </p>
          ))}
      </Modal>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-text-2">
          {groups.length} {groups.length === 1 ? "Clip" : "Clips"}, {clips.filter(isDone).length} von {clips.length} Clips fertig.
        </p>
        <div className="flex items-center gap-2 text-xs">
          {live && (
            <span className="flex items-center gap-2 text-ai-soft">
              <span className="h-1.5 w-1.5 rounded-full bg-ai-soft" aria-hidden="true" />
              {RENDER_STEP.label} live
            </span>
          )}
          {connection === "error" && !allSettled && <span className="text-attention">Verbindung unterbrochen, versuche erneut</span>}
          {demo && <Badge tone="ai">Testmodus</Badge>}
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
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wide text-text-2">Clip {gi + 1}</p>
            <h2 className="mt-1 text-lg font-medium">{g.candidate ? structureLabel(g.candidate.structure) : "Clip gelöscht"}</h2>
            {g.candidate && <p className="mt-1 line-clamp-2 text-sm text-text-2">{snippet(g.candidate.rubric.text)}</p>}
          </div>

          {/* Eine Reihe je Clip statt vier Spalten: die Karten sind nicht mehr aneinander
              hochgezogen (Grid-Zeilen gleicher Höhe), und der vorhandene Platz nach rechts wird
              genutzt, statt alles vertikal zu stapeln. */}
          <ul className="flex flex-col gap-4" aria-label={`Clips zu Vorschlag ${gi + 1}`}>
            {g.clips.map((clip) => {
              const ev = latest.get(clip.id);
              const state = checkState(clip);
              const progress = clip.status === "rendering" ? (ev?.progress ?? 0) : isDone(clip) ? 1 : 0;
              const approval = approvals.get(clip.id);
              const blocked = exportBlocked(clip, approval);
              const mp4 = clip.file_key && mediaBase ? `/api/projects/${sourceId}/clips/${clip.id}/download?kind=mp4` : null;
              /* Warum ein Download gerade nicht geht. Gleiche Reihenfolge wie bisher: fehlende
                 Gastfreigabe zuerst, dann Testmodus, dann die Datei selbst. */
              const lockedTitle = blocked
                ? EXPORT_BLOCKED_MESSAGE
                : demo
                  ? "Im Testmodus gibt es keine Dateien"
                  : isDone(clip)
                    ? "Datei noch nicht verfügbar"
                    : "Erst wenn der Clip fertig ist";
              const poster = mediaUrl(mediaBase, clip.poster_key);
              /* Gerendertes MP4 direkt aus der Medien-URL (lokal /api/media, sonst CDN oder MinIO) */
              const video = isDone(clip) ? mediaUrl(mediaBase, clip.file_key) : null;
              const duration = clip.duration_s ?? compositionDuration(clip);
              const clipExtras = extras[clip.id] ?? { id: clip.id, experiment_id: null, variant: null, series_id: null, series_index: null, reframe_override: null };
              return (
                <li key={clip.id} className="flex min-w-0 flex-col gap-4 rounded-inner border border-line p-4 sm:flex-row sm:items-stretch">
                  {/* Vorschau links, klein und mit fester Breite. Die Höhe folgt dem Seitenverhältnis.
                      Ein Klick öffnet die große Vorschau; als Knopf ist sie mit Tab erreichbar und
                      reagiert auf Enter und Leertaste. */}
                  <button
                    type="button"
                    onClick={() => void openZoom(clip)}
                    title="Groß ansehen"
                    aria-label={`${PLATFORM_LABELS[clip.platform]} groß ansehen`}
                    className="transition-soft group relative w-[132px] shrink-0 self-start overflow-hidden rounded-[12px] border border-line bg-black hover:border-white/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
                    style={{ aspectRatio: ASPECT_RATIO_CSS[clip.aspect] }}
                  >
                    {video ? (
                      <video src={video} poster={poster ?? undefined} muted playsInline preload="metadata" className="pointer-events-none h-full w-full object-cover" />
                    ) : poster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={poster} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <div
                        aria-hidden="true"
                        className="flex h-full w-full items-end justify-between p-3"
                        style={{
                          background: "radial-gradient(ellipse at 50% 30%, rgba(91,140,255,0.22) 0%, rgba(27,26,98,0.3) 40%, rgba(0,0,0,0) 75%), #0a0a13",
                        }}
                      />
                    )}
                    <span aria-hidden="true" className="transition-soft absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/35">
                      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-text text-black">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M4.5 2.8v10.4c0 .8.9 1.3 1.6.9l8-5.2c.6-.4.6-1.4 0-1.8l-8-5.2c-.7-.4-1.6.1-1.6.9z" />
                        </svg>
                      </span>
                    </span>
                  </button>

                  {/* Mitte: Zustand, kurze Zeichen, Handlungen. */}
                  <div className="flex min-w-0 flex-1 flex-col gap-3">
                  <div className="flex items-start gap-3">
                    <StatusCheck state={state} size={28} label={`${CLIP_STATUS_LABELS[clip.status]}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <p className={cn("text-sm font-medium", state === "error" ? "text-attention" : "text-text")}>{CLIP_STATUS_LABELS[clip.status]}</p>
                        <Badge tone="ok" className="h-6 px-2.5 text-[11px]">{PLATFORM_LABELS[clip.platform]}</Badge>
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
                        </>
                      )}
                      {clip.status === "failed" && <p className="mt-0.5 text-sm text-attention">{clip.render_error ?? "Das Erstellen hat nicht geklappt. Bitte nochmal versuchen."}</p>}
                      {clip.status === "draft" && <p className="mt-0.5 text-sm text-text-2">Wird gleich erstellt.</p>}
                    </div>
                  </div>

                  {/* Sichtbar bleibt nur, was rechtlich am Clip hängt. */}
                  {isDone(clip) && (clip.ad_label || clip.provenance.source_credit) && (
                    <div className="flex flex-wrap gap-1.5">
                      {clip.ad_label && <Badge>Werbelabel: {clip.ad_label}</Badge>}
                      {clip.provenance.source_credit && <Badge>{clip.provenance.source_credit}</Badge>}
                    </div>
                  )}

                  {/* Kurzes Zeichen statt Erklärsatz: das ist ein echtes Problem am Clip, der volle
                      Wortlaut steht im Titel. */}
                  {clip.cps_warnings.length > 0 && (
                    <p className="flex items-center gap-1.5 text-xs text-text-2" title={clip.cps_warnings.join("\n")}>
                      <IconWarn />
                      Untertitel laufen schnell durch
                    </p>
                  )}

                  {blocked && (
                    <p className="flex items-center gap-1.5 rounded-[12px] border border-attention/50 bg-attention/10 px-3 py-2 text-xs text-text">
                      <IconWarn className="text-attention" />
                      {EXPORT_BLOCKED_MESSAGE}
                    </p>
                  )}

                  {/* Drei Handlungen je Clip: Herunterladen bleibt hervorgehoben, Bearbeiten und
                      Löschen sind reine Zeichen mit Titel und Beschriftung für Screenreader. */}
                  <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
                    {mp4 && !blocked ? (
                      <a
                        href={mp4}
                        download
                        className="transition-soft inline-flex h-9 items-center gap-2 rounded-pill bg-text px-4 text-sm font-medium text-black hover:bg-white"
                      >
                        <IconDownload />
                        Herunterladen
                      </a>
                    ) : (
                      <span
                        aria-disabled="true"
                        title={lockedTitle}
                        className={cn(
                          "inline-flex h-9 cursor-not-allowed items-center gap-2 rounded-pill border px-4 text-sm font-medium",
                          blocked ? "border-attention/40 text-attention/70" : "border-line text-text-3",
                        )}
                      >
                        <IconDownload />
                        Herunterladen
                      </span>
                    )}
                    <IconLink href={`/projekte/${sourceId}/clips/${clip.id}`} label="Bearbeiten">
                      <IconPencil />
                    </IconLink>
                    {canDelete && (
                      <IconButton label="Löschen" tone="danger" onClick={() => setDeleteTarget(clip)} disabled={clip.status === "rendering"}>
                        <IconTrash />
                      </IconButton>
                    )}
                  </div>
                  </div>

                  {/* Rechte Spalte: oben die Freigabe (hat mit dem Rest nichts zu tun),
                      unten die Serie. Dazwischen Luft, damit beides an seinem Platz bleibt. */}
                  <div className="flex w-full shrink-0 flex-col justify-between gap-4 border-t border-line pt-3 sm:w-[300px] sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
                    <div className="flex flex-col gap-1">
                      <ClipApproval
                        sourceId={sourceId}
                        clipId={clip.id}
                        clipLabel={`${PLATFORM_LABELS[clip.platform]} ${ASPECT_LABELS[clip.aspect]}`}
                        guestApprovalRequired={clip.guest_approval_required}
                        current={approval ?? null}
                        canRequest={canRequestGuest}
                        planAllows={planAllowsGuest}
                        planName={planName}
                        onRequested={onRequested}
                      />
                      {clip.guest_approval_required && !approval?.decision && (
                        <button type="button" onClick={() => refreshApproval(clip)} className="self-start text-xs text-text-2 underline-offset-4 hover:text-text hover:underline">
                          Status aktualisieren
                        </button>
                      )}
                    </div>

                    {publishing?.canSeries && (
                      <ClipSeries
                        clipId={clip.id}
                        extras={clipExtras}
                        series={publishing.series}
                        onExtras={(next) => setExtras((prev) => ({ ...prev, [next.id]: next }))}
                      />
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </GlassCard>
      ))}
    </div>
  );
}

/* Zeichen im Stil der Seitenleiste: 20 px, 1,75 px Strich, currentColor, keine Füllung */
function Svg({ size = 20, className, children }: { size?: number; className?: string; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  );
}

const IconDownload = () => (
  <Svg size={18}>
    <path d="M12 3v12" />
    <path d="m7 11 5 5 5-5" />
    <path d="M4 20h16" />
  </Svg>
);
const IconPencil = () => (
  <Svg size={18}>
    <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" />
    <path d="m14 6 4 4" />
  </Svg>
);
const IconTrash = () => (
  <Svg size={18}>
    <path d="M4 7h16" />
    <path d="M9 7V4h6v3" />
    <path d="M6 7l1 13h10l1-13" />
    <path d="M10 11v5" />
    <path d="M14 11v5" />
  </Svg>
);
const IconWarn = ({ className }: { className?: string }) => (
  <Svg size={14} className={cn("shrink-0", className)}>
    <path d="M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </Svg>
);

const ICON_ACTION =
  "transition-soft inline-flex h-9 w-9 items-center justify-center rounded-pill border border-line-strong text-text-2 hover:border-white/40 hover:bg-white/5 hover:text-text";

/* Reines Zeichen als Knopf. Titel für die Maus, aria-label für Screenreader. */
function IconButton({
  label,
  onClick,
  disabled,
  tone,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "danger";
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(ICON_ACTION, tone === "danger" && "hover:border-danger/60 hover:bg-danger/10 hover:text-danger", disabled && "cursor-not-allowed opacity-40 hover:border-line-strong hover:bg-transparent")}
    >
      {children}
    </button>
  );
}

/* Reines Zeichen als Verweis, sonst gleich wie IconButton. */
function IconLink({ href, label, children }: { href: string; label: string; children: ReactNode }) {
  return (
    <Link href={href} title={label} aria-label={label} className={ICON_ACTION}>
      {children}
    </Link>
  );
}
