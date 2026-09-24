"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { SilentPreview, type PreviewFont } from "@/components/clips/SilentPreview";
import { Modal } from "@/components/ui/Modal";
import { ClipApproval } from "./ClipApproval";
import type { Aspect, Candidate, CaptionVersion, Clip, GuestApproval, HookVersion, PipelineEvent } from "@/lib/repo/types";
import { EXPORT_BLOCKED_MESSAGE, exportBlocked, latestByClip } from "@/lib/guest/approval";
import { vorschauStand } from "@/lib/clips/vorschau-stand";
import { stilAusPlan, stilPruefen } from "@/lib/clips/caption-style";
import { RUBRIC_LABELS, RUBRIC_ORDER, structureLabel } from "@/lib/candidates/labels";
import { clipZustand, korrekturGrund, ZUSTAND_LABEL, ZUSTAND_RANG, ZUSTAND_SATZ, type ClipZustand } from "@/lib/clips/clip-zustand";
import { fortsetzung, thema } from "@/lib/clips/karten-text";
import {
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
  /* Die neueste Transkriptversion des Projekts. Daran hängt, ob eine Textkorrektur schon im
   * gebauten Video steckt. */
  transkriptVersion: number | null;
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
  transkriptVersion,
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
  /* Ausgewählte Clips für Sammelaktionen. Bleibt beim Zurückkommen aus dem Editor erhalten: wer
   * zehn Clips ausgewählt hat, einen bearbeitet und zurückkommt, will nicht von vorn anfangen. */
  const [auswahl, setAuswahl] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<ClipZustand | "alle">("alle");
  const [sammelLaeuft, setSammelLaeuft] = useState(false);
  /* Was zuletzt verworfen wurde, zum Zurückholen. Eine Entscheidung ohne Weg zurück lädt nicht
   * zum Aufräumen ein. */
  const [zuletztVerworfen, setZuletztVerworfen] = useState<string[]>([]);

  const merkschluessel = `chopstr.clips.${sourceId}`;
  /* Auswahl, Filter und Scrollstand über einen Ausflug in den Editor retten.
   *
   * Die Reihenfolge ist der Punkt. Ein erster Versuch schrieb den Stand in der Aufräumfunktion
   * des Speicher-Effekts. Beim Zurückkommen lief dann: wiederherstellen, dadurch ändern sich die
   * Abhängigkeiten, Aufräumen speichert den Stand von VOR dem Wiederherstellen - also leer. Der
   * gemerkte Stand löschte sich selbst.
   *
   * Jetzt wird bei jeder Änderung geschrieben und genau einmal gelesen. */
  const standRef = useRef<{ auswahl: string[]; filter: ClipZustand | "alle" }>({ auswahl: [], filter: "alle" });
  const gelesen = useRef(false);

  const merken = useCallback(() => {
    /* Vor dem ersten Lesen nichts schreiben, sonst überschreibt der leere Anfangszustand das
     * Gemerkte, bevor es jemand geholt hat. */
    if (!gelesen.current) return;
    try {
      sessionStorage.setItem(
        merkschluessel,
        JSON.stringify({ ...standRef.current, scrollY: Math.round(window.scrollY) }),
      );
    } catch {
      /* Kein Speicher, kein Problem: dann fängt die Auswahl eben neu an. */
    }
  }, [merkschluessel]);

  useEffect(() => {
    standRef.current = { auswahl: [...auswahl], filter };
    merken();
  }, [auswahl, filter, merken]);

  useEffect(() => {
    const holen = () => {
      try {
        const roh = sessionStorage.getItem(merkschluessel);
        if (roh) {
          const d = JSON.parse(roh) as { auswahl?: string[]; filter?: string; scrollY?: number };
          if (Array.isArray(d.auswahl) && d.auswahl.length) setAuswahl(new Set(d.auswahl));
          if (typeof d.filter === "string") setFilter(d.filter as ClipZustand | "alle");
          if (typeof d.scrollY === "number" && d.scrollY > 0) window.scrollTo({ top: d.scrollY });
        }
      } catch {
        /* Ein unlesbarer Eintrag ist kein Grund, die Seite zu stören. */
      }
      gelesen.current = true;
    };
    /* Ein Tick später, damit das Lesen nicht mitten in den ersten Aufbau fällt. */
    const t = window.setTimeout(holen, 0);
    window.addEventListener("pagehide", merken);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("pagehide", merken);
      merken();
    };
  }, [merkschluessel, merken]);

  useEffect(() => {
    let angefordert = 0;
    const beiScroll = () => {
      if (angefordert) return;
      angefordert = window.requestAnimationFrame(() => {
        angefordert = 0;
        merken();
      });
    };
    window.addEventListener("scroll", beiScroll, { passive: true });
    return () => {
      if (angefordert) window.cancelAnimationFrame(angefordert);
      window.removeEventListener("scroll", beiScroll);
    };
  }, [merken]);


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

  /* Der Zustand je Clip, einmal gerechnet. Karte, Filter und Zähler lesen dasselbe Ergebnis;
   * drei Stellen mit je eigener Rechnung waren der Grund dafür, dass an einem Clip „Fertig" stand
   * und daneben eine Warnung. */
  const zustaende = useMemo(() => {
    const aus = new Map<string, { zustand: ClipZustand; veraltet: boolean }>();
    for (const clip of clips) {
      const gespeicherterStil = stilPruefen(extras[clip.id]?.caption_style);
      const stand = {
        status: clip.status,
        hatDatei: Boolean(clip.file_key),
        plan: clip.render_plan,
        renderFehler: clip.render_error,
        transkriptVersion,
        stil: Object.keys(gespeicherterStil).length
          ? gespeicherterStil
          : stilAusPlan((clip.render_plan?.captions as unknown as Record<string, unknown>) ?? null, clip.render_plan?.output.height),
        schnitt: clip.composition,
        zeitmarken: clip.zeitmarken,
      };
      aus.set(clip.id, {
        zustand: clipZustand({ clip, freigabe: approvals.get(clip.id) ?? null, stand }),
        veraltet: vorschauStand(stand) === "veraltet",
      });
    }
    return aus;
  }, [clips, extras, approvals, transkriptVersion]);

  const zaehler = useMemo(() => {
    const aus = new Map<ClipZustand, number>();
    for (const z of zustaende.values()) aus.set(z.zustand, (aus.get(z.zustand) ?? 0) + 1);
    return aus;
  }, [zustaende]);

  /* Die sichtbaren Clips: gefiltert und so sortiert, dass oben steht, was Arbeit braucht.
   * Verworfene sind nur unter ihrem eigenen Filter zu sehen - sonst wäre Verwerfen folgenlos. */
  const sichtbar = useMemo(() => {
    const liste = clips.filter((c) => {
      const z = zustaende.get(c.id)?.zustand;
      if (filter === "alle") return z !== "verworfen";
      return z === filter;
    });
    return [...liste].sort((a, b) => {
      const ra = ZUSTAND_RANG[zustaende.get(a.id)?.zustand ?? "pruefen"];
      const rb = ZUSTAND_RANG[zustaende.get(b.id)?.zustand ?? "pruefen"];
      if (ra !== rb) return ra - rb;
      return (a.composition[0]?.start ?? 0) - (b.composition[0]?.start ?? 0);
    });
  }, [clips, zustaende, filter]);

  /* Den Prüfstand setzen, einzeln oder für die ganze Auswahl. */
  const reviewSetzen = useCallback(
    async (ids: string[], review: Clip["review"]) => {
      if (ids.length === 0) return;
      setSammelLaeuft(true);
      setMessage(null);
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/review`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clip_ids: ids, review }),
        });
        const data = (await res.json()) as ApiError & { clips?: Clip[] };
        if (!res.ok) throw new Error(data.error ?? "Das hat nicht geklappt");
        const neu = new Map((data.clips ?? []).map((c) => [c.id, c]));
        applyClips(clipsRef.current.map((c) => neu.get(c.id) ?? c));
        setZuletztVerworfen(review === "verworfen" ? ids : []);
        const wieViele = ids.length === 1 ? "Ein Clip" : `${ids.length} Clips`;
        setMessage({
          tone: "ok",
          text:
            review === "verworfen"
              ? `${wieViele} verworfen.`
              : review === "bereit"
                ? `${wieViele} als bereit markiert.`
                : `${wieViele} zurückgeholt.`,
        });
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Das hat nicht geklappt" });
      } finally {
        setSammelLaeuft(false);
      }
    },
    [sourceId, applyClips],
  );

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
          {clips.length} {clips.length === 1 ? "Clip" : "Clips"}
          {zaehler.get("korrektur") ? `, ${zaehler.get("korrektur")} brauchen eine Korrektur` : ""}
          {zaehler.get("pruefen") ? `, ${zaehler.get("pruefen")} warten auf dich` : ""}.
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

      {/* Filter nach Zustand. Bei dreißig Clips ist „alle zeigen" keine Übersicht mehr, und die
          Frage lautet ohnehin fast immer „was muss ich noch ansehen". */}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Clips filtern">
        {([["alle", `Alle (${clips.length - (zaehler.get("verworfen") ?? 0)})`]] as [ClipZustand | "alle", string][])
          .concat(
            (["korrektur", "pruefen", "bereit", "freigegeben", "wird_erstellt", "fehler", "verworfen"] as ClipZustand[])
              .filter((z) => (zaehler.get(z) ?? 0) > 0)
              .map((z) => [z, `${ZUSTAND_LABEL[z]} (${zaehler.get(z)})`] as [ClipZustand | "alle", string]),
          )
          .map(([wert, label]) => (
            <button
              key={wert}
              type="button"
              onClick={() => setFilter(wert)}
              aria-pressed={filter === wert}
              className={cn(
                "transition-soft rounded-pill border px-3.5 py-1.5 text-sm",
                filter === wert ? "border-white/60 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong",
              )}
            >
              {label}
            </button>
          ))}
      </div>

      {/* Sammelaktionen. Erscheinen erst mit einer Auswahl: eine Leiste, die immer dasteht und
          meistens nichts tun kann, nimmt nur Platz weg. */}
      {auswahl.size > 0 && (
        <GlassCard padding="md" selected>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-text">
              {auswahl.size === 1 ? "Ein Clip ausgewählt" : `${auswahl.size} Clips ausgewählt`}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([...auswahl], "bereit")}>
                Als bereit markieren
              </Button>
              <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([...auswahl], "verworfen")}>
                Verwerfen
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setAuswahl(new Set())}>
                Auswahl aufheben
              </Button>
            </div>
          </div>
        </GlassCard>
      )}

      {/* Zurückholen nach einem Verwerfen. Solange der Hinweis steht, ist die Entscheidung
          umkehrbar, ohne dass man den Filter kennen muss. */}
      {zuletztVerworfen.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-inner border border-line px-4 py-3">
          <p className="text-sm text-text-2">
            {zuletztVerworfen.length === 1 ? "Ein Clip wurde verworfen." : `${zuletztVerworfen.length} Clips wurden verworfen.`}{" "}
            Gelöscht ist nichts.
          </p>
          <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen(zuletztVerworfen, "offen")}>
            Zurückholen
          </Button>
        </div>
      )}

      {sichtbar.length === 0 && (
        <GlassCard padding="lg" className="text-center">
          <p className="text-text-2">
            {filter === "alle" ? "Hier ist nichts." : `Kein Clip im Zustand „${ZUSTAND_LABEL[filter as ClipZustand]}".`}
          </p>
          {filter !== "alle" && (
            <div className="mt-4 flex justify-center">
              <Button variant="ghost" onClick={() => setFilter("alle")}>
                Alle zeigen
              </Button>
            </div>
          )}
        </GlassCard>
      )}

      <ul className="flex flex-col gap-3" aria-label="Clips">
        {sichtbar.map((clip) => {
          const ev = latest.get(clip.id);
          const z = zustaende.get(clip.id) ?? { zustand: "pruefen" as ClipZustand, veraltet: false };
          const kandidat = candidates.find((k) => k.id === clip.candidate_id) ?? null;
          const progress = clip.status === "rendering" ? (ev?.progress ?? 0) : isDone(clip) ? 1 : 0;
          const approval = approvals.get(clip.id);
          const blocked = exportBlocked(clip, approval);
          const mp4 = clip.file_key && mediaBase ? `/api/projects/${sourceId}/clips/${clip.id}/download?kind=mp4` : null;
          const lockedTitle = blocked
            ? EXPORT_BLOCKED_MESSAGE
            : z.veraltet
              ? "Die Datei zeigt nicht mehr, was eingestellt ist. Bitte neu erstellen."
              : demo
                ? "Im Testmodus gibt es keine Dateien"
                : isDone(clip)
                  ? "Datei noch nicht verfügbar"
                  : "Erst wenn der Clip fertig ist";
          const poster = mediaUrl(mediaBase, clip.poster_key);
          const video = isDone(clip) ? mediaUrl(mediaBase, clip.file_key) : null;
          const duration = clip.duration_s ?? compositionDuration(clip);
          const clipExtras = extras[clip.id] ?? {
            id: clip.id,
            experiment_id: null,
            variant: null,
            series_id: null,
            series_index: null,
            reframe_override: null,
          };
          const gewaehlt = auswahl.has(clip.id);
          const ueberschrift = thema(kandidat?.rubric.text ?? "");

          return (
            <li key={clip.id}>
              <GlassCard
                padding="md"
                selected={gewaehlt}
                className={cn("flex min-w-0 gap-4", glitchGroups.has(clip.candidate_id ?? "ohne") && "spectrum-glitch")}
              >
                {/* Auswahlkästchen ganz links: Sammelaktionen brauchen einen Griff, der nicht mit
                    „ansehen" verwechselt wird. */}
                <label className="flex shrink-0 cursor-pointer items-start pt-1">
                  <input
                    type="checkbox"
                    checked={gewaehlt}
                    onChange={(e) =>
                      setAuswahl((prev) => {
                        const kopie = new Set(prev);
                        if (e.target.checked) kopie.add(clip.id);
                        else kopie.delete(clip.id);
                        return kopie;
                      })
                    }
                    aria-label={`${ueberschrift} auswählen`}
                    /* Sichtbar auf dunklem Grund: ein Kästchen in Systemfarben verschwindet hier
                     * fast. Rand und Hintergrund sind gesetzt, das Häkchen kommt von accent. */
                    className="h-5 w-5 cursor-pointer rounded border border-line-strong bg-black/40 accent-white"
                  />
                </label>

                {/* Vorschau: ein Klick spielt sie groß ab. */}
                <button
                  type="button"
                  onClick={() => void openZoom(clip)}
                  title="Ansehen"
                  aria-label={`${ueberschrift} ansehen`}
                  className="transition-soft group relative w-[92px] shrink-0 self-start overflow-hidden rounded-[10px] border border-line bg-black hover:border-white/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
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
                      className="h-full w-full"
                      style={{ background: "radial-gradient(ellipse at 50% 30%, rgba(91,140,255,0.22) 0%, rgba(27,26,98,0.3) 40%, rgba(0,0,0,0) 75%), #0a0a13" }}
                    />
                  )}
                  <span aria-hidden="true" className="transition-soft absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/35">
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-text text-black">
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M4.5 2.8v10.4c0 .8.9 1.3 1.6.9l8-5.2c.6-.4.6-1.4 0-1.8l-8-5.2c-.7-.4-1.6.1-1.6.9z" />
                      </svg>
                    </span>
                  </span>
                </button>

                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  {/* Worum es geht. Vorher stand hier die Form des Clips („Pointe am Anfang"), und
                      die sagt nichts darüber, ob man diesen Clip veröffentlichen will. */}
                  <div className="min-w-0">
                    <p className="text-[15px] font-medium leading-snug text-text">{ueberschrift}</p>
                    {kandidat && fortsetzung(kandidat.rubric.text) && (
                      <p className="mt-0.5 line-clamp-2 text-sm text-text-2">{fortsetzung(kandidat.rubric.text)}</p>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <ZustandPille zustand={z.zustand} />
                    {/* Die Plattform als Plakette: bei mehreren Formaten desselben Ausschnitts ist
                        sie der Unterschied, und der muss ins Auge fallen. */}
                    <Badge className="h-6 px-2.5 text-[11px]">{PLATFORM_LABELS[clip.platform]}</Badge>
                    <span className="font-mono text-xs tabular-nums text-text-2">{formatClipDuration(duration)}</span>
                    <span className="text-xs text-text-3">{ASPECT_LABELS[clip.aspect]}</span>
                    {kandidat && <span className="text-xs text-text-3">{structureLabel(kandidat.structure)}</span>}
                  </div>

                  {clip.status === "rendering" && (
                    <div
                      className="h-1 w-full max-w-[280px] overflow-hidden rounded-pill bg-white/10"
                      role="progressbar"
                      aria-label="Fortschritt"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(progress * 100)}
                    >
                      <div className="transition-soft h-full rounded-pill bg-ai-soft" style={{ width: `${Math.max(4, Math.round(progress * 100))}%` }} />
                    </div>
                  )}

                  {/* Eine Warnung führt zur Korrektur und nicht in die Leere. */}
                  {z.zustand === "korrektur" && (
                    <Link
                      href={`/projekte/${sourceId}/clips/${clip.id}`}
                      className="transition-soft flex items-start gap-1.5 self-start rounded-[10px] border border-attention/50 bg-attention/10 px-3 py-2 text-xs text-text hover:border-attention"
                    >
                      <IconWarn className="mt-0.5 shrink-0 text-attention" />
                      <span>
                        {korrekturGrund(clip, z.veraltet)} <span className="underline underline-offset-4">Beheben</span>
                      </span>
                    </Link>
                  )}
                  {clip.status === "failed" && (
                    <p className="text-sm text-attention">{clip.render_error ?? "Das Erstellen hat nicht geklappt."}</p>
                  )}

                  {/* Was rechtlich am Clip hängt, bleibt sichtbar. */}
                  {isDone(clip) && (clip.ad_label || clip.provenance.source_credit) && (
                    <div className="flex flex-wrap gap-1.5">
                      {clip.ad_label && <Badge>Werbelabel: {clip.ad_label}</Badge>}
                      {clip.provenance.source_credit && <Badge>{clip.provenance.source_credit}</Badge>}
                    </div>
                  )}

                  {/* Handlungen: alle sichtbar und benannt, keine hinter einem Zeichen versteckt. */}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Button size="sm" variant="ghost" onClick={() => void openZoom(clip)}>
                      Ansehen
                    </Button>
                    <Link
                      href={`/projekte/${sourceId}/clips/${clip.id}`}
                      className="transition-soft inline-flex h-9 items-center rounded-pill border border-line px-3.5 text-sm text-text-2 hover:border-line-strong hover:text-text"
                    >
                      Bearbeiten
                    </Link>
                    {clip.review === "verworfen" ? (
                      <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([clip.id], "offen")}>
                        Zurückholen
                      </Button>
                    ) : (
                      <>
                        <Button
                          size="sm"
                          variant={z.zustand === "pruefen" ? "primary" : "ghost"}
                          disabled={sammelLaeuft || clip.review === "bereit" || !isDone(clip)}
                          onClick={() => void reviewSetzen([clip.id], "bereit")}
                        >
                          {clip.review === "bereit" ? "Ist bereit" : "Freigeben"}
                        </Button>
                        <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([clip.id], "verworfen")}>
                          Verwerfen
                        </Button>
                      </>
                    )}
                    {mp4 && !blocked && !z.veraltet ? (
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
                          blocked || z.veraltet ? "border-attention/40 text-attention/70" : "border-line text-text-3",
                        )}
                      >
                        <IconDownload />
                        Herunterladen
                      </span>
                    )}
                    {canDelete && (
                      <IconButton label="Endgültig löschen" tone="danger" onClick={() => setDeleteTarget(clip)} disabled={clip.status === "rendering"}>
                        <IconTrash />
                      </IconButton>
                    )}
                  </div>

                  {/* Warum dieser Clip vorgeschlagen wurde, aus der Analyse und nicht erfunden.
                      Zugeklappt, weil es beim Suchen nicht stört und beim Zweifeln hilft. */}
                  {kandidat?.rubric.proposal_why && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-sm text-text-2 underline-offset-4 hover:text-text hover:underline">
                        Warum vorgeschlagen?
                      </summary>
                      <div className="mt-2 flex flex-col gap-2 rounded-inner border border-line p-3">
                        <p className="text-sm text-text">{kandidat.rubric.proposal_why}</p>
                        <ul className="flex flex-wrap gap-x-4 gap-y-1">
                          {RUBRIC_ORDER.filter((k) => kandidat.rubric.scores[k]).map((k) => (
                            <li key={k} className="text-xs text-text-2">
                              {RUBRIC_LABELS[k]}{" "}
                              <span className="tabular-nums text-text">{kandidat.rubric.scores[k].value.toFixed(0)}</span>
                              <span className="text-text-3"> von 10</span>
                            </li>
                          ))}
                        </ul>
                        {kandidat.rubric.scores_stale && (
                          <p className="text-xs text-text-3">
                            Die Bewertung stammt vom ursprünglichen Ausschnitt, der Clip wurde seitdem geändert.
                          </p>
                        )}
                      </div>
                    </details>
                  )}

                  {/* Gastfreigabe und Serie stehen unter dem Clip und nicht in einer eigenen
                      Spalte: als Spalte waren sie genauso hoch wie die Karte und machten aus
                      jedem Eintrag einen Block. */}
                  <div className="mt-1 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-3">
                    <ClipApproval
                      sourceId={sourceId}
                      clipId={clip.id}
                      clipLabel={`${PLATFORM_LABELS[clip.platform]} ${ASPECT_LABELS[clip.aspect]}`}
                      guestApprovalRequired={clip.guest_approval_required}
                      current={approval ?? null}
                      canRequest={canRequestGuest && !z.veraltet}
                      planAllows={planAllowsGuest}
                      planName={planName}
                      onRequested={onRequested}
                    />
                    {clip.guest_approval_required && !approval?.decision && (
                      <button type="button" onClick={() => refreshApproval(clip)} className="text-xs text-text-2 underline-offset-4 hover:text-text hover:underline">
                        Status aktualisieren
                      </button>
                    )}
                    {/* Nur wenn es Serien gibt. Ein leeres „Serie zuordnen" auf jeder Karte war
                        dreißigmal derselbe Hinweis auf etwas, das es nicht gibt. */}
                    {publishing?.canSeries && publishing.series.length > 0 && (
                      <ClipSeries
                        clipId={clip.id}
                        extras={clipExtras}
                        series={publishing.series}
                        onExtras={(next) => setExtras((prev) => ({ ...prev, [next.id]: next }))}
                      />
                    )}
                  </div>
                </div>
              </GlassCard>
            </li>
          );
        })}
      </ul>
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

/* Der Zustand als Pille. Farbe nur da, wo sie etwas bedeutet: Korrektur ist dringend, bereit und
 * freigegeben sind erledigt, der Rest bleibt neutral. Eine Oberfläche, in der alles bunt ist,
 * sagt nichts mehr. */
function ZustandPille({ zustand }: { zustand: ClipZustand }) {
  return (
    <span
      title={ZUSTAND_SATZ[zustand]}
      className={cn(
        "inline-flex h-6 items-center rounded-pill border px-2.5 text-[12px] font-medium",
        zustand === "korrektur" && "border-attention/60 bg-attention/15 text-text",
        zustand === "fehler" && "border-danger/60 bg-danger/15 text-text",
        (zustand === "bereit" || zustand === "freigegeben") && "border-brand/60 bg-brand/15 text-text",
        (zustand === "pruefen" || zustand === "wird_erstellt" || zustand === "verworfen") && "border-line text-text-2",
      )}
    >
      {ZUSTAND_LABEL[zustand]}
    </span>
  );
}
