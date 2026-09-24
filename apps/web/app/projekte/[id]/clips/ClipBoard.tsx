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
import { stilAusPlan, stilPruefen } from "@/lib/clips/caption-style";
import { RUBRIC_LABELS, RUBRIC_ORDER, structureLabel } from "@/lib/candidates/labels";
import {
  aktionStand,
  DATEI_LABEL,
  DATEI_SATZ,
  FILTER_LABEL,
  FILTER_ORDNUNG,
  hauptaktion,
  passtZuFilter,
  pruefstand,
  rang,
  REDAKTION_LABEL,
  REDAKTION_SATZ,
  type Befund,
  type FilterId,
  type Pruefstand,
} from "@/lib/clips/pruefstand";
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
import { Gepostet } from "./Gepostet";

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
  /* Das ganze Video als Proxy. Daraus kommt der Vorschaumoment für Clips, die noch kein eigenes
   * Poster haben. */
  quelleSrc: string | null;
  demo: boolean;
  highlightColor?: string;
  lowerThird: { name: string; role: string } | null;
  /* Gast-Freigabe (Block B) */
  guestApprovals: GuestApproval[];
  canRequestGuest: boolean;
  planAllowsGuest: boolean;
  planName: string;
  canDelete: boolean;
  /* Darf dieser Nutzer eintragen, dass ein Clip gepostet wurde, und Kennzahlen nachtragen? */
  canPublish: boolean;
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
  quelleSrc,
  demo,
  highlightColor,
  lowerThird,
  guestApprovals,
  canRequestGuest,
  planAllowsGuest,
  planName,
  canDelete,
  canPublish,
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
  const [filter, setFilter] = useState<FilterId>("alle");
  /* Zwei weitere Achsen, die vor allem eine Agentur braucht: welche Plattform, und wer von aussen
   * entscheidet. Marke und Video stehen im Kopf der Seite - auf dieser Seite sind sie für alle
   * Clips gleich, und vierzehnmal dasselbe ist keine Information. */
  const [plattform, setPlattform] = useState<string>("alle");
  const [person, setPerson] = useState<string>("alle");
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
  const standRef = useRef<{ auswahl: string[]; filter: FilterId; plattform: string; person: string }>({
    auswahl: [],
    filter: "alle",
    plattform: "alle",
    person: "alle",
  });
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
    standRef.current = { auswahl: [...auswahl], filter, plattform, person };
    merken();
  }, [auswahl, filter, plattform, person, merken]);

  useEffect(() => {
    const holen = () => {
      try {
        const roh = sessionStorage.getItem(merkschluessel);
        if (roh) {
          const d = JSON.parse(roh) as {
            auswahl?: string[];
            filter?: string;
            plattform?: string;
            person?: string;
            scrollY?: number;
          };
          if (Array.isArray(d.auswahl) && d.auswahl.length) setAuswahl(new Set(d.auswahl));
          if (typeof d.filter === "string") setFilter(d.filter as FilterId);
          if (typeof d.plattform === "string") setPlattform(d.plattform);
          if (typeof d.person === "string") setPerson(d.person);
          if (typeof d.scrollY === "number" && d.scrollY > 0) zielScroll.current = d.scrollY;
        }
      } catch {
        /* Ein unlesbarer Eintrag ist kein Grund, die Seite zu stören. */
      }
      gelesen.current = true;
    };
    /* Kommt jemand über eine Zahl von der Übersicht, gilt deren Filter und nicht der gemerkte.
     * „3 Clips prüfen" anzuklicken und dann die Liste von letzter Woche zu sehen, wäre eine
     * Antwort auf eine andere Frage. */
    const ausAdresse = window.location.hash.replace("#", "");
    const t = window.setTimeout(
      ausAdresse && (FILTER_ORDNUNG as string[]).includes(ausAdresse)
        ? () => {
            setFilter(ausAdresse as FilterId);
            gelesen.current = true;
          }
        : holen,
      0,
    );
    window.addEventListener("pagehide", merken);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("pagehide", merken);
      merken();
    };
  }, [merkschluessel, merken]);

  /* Den Scrollstand wiederherstellen, sobald die Seite hoch genug dafür ist.
   *
   * Ein einzelner scrollTo direkt nach dem Lesen ging ins Leere: zu dem Zeitpunkt stehen die
   * Karten noch nicht, die Seite ist einen Bildschirm hoch, und der Browser klemmt das Ziel
   * stillschweigend auf 0. Man landete oben und suchte die Stelle von Hand wieder.
   *
   * Deshalb wird über ein paar Bilder hinweg versucht, bis die Höhe reicht. Danach wird
   * aufgegeben: ein Filter, der die Liste kürzer macht, kann den alten Stand unerreichbar
   * machen, und dann ist oben die richtige Antwort. */
  const zielScroll = useRef<number | null>(null);
  useEffect(() => {
    let frame = 0;
    let versuche = 0;
    const versuchen = () => {
      const ziel = zielScroll.current;
      if (ziel == null) {
        if (versuche++ < 60) frame = requestAnimationFrame(versuchen);
        return;
      }
      const moeglich = document.documentElement.scrollHeight - window.innerHeight;
      if (moeglich >= ziel || versuche++ > 60) {
        window.scrollTo({ top: Math.min(ziel, Math.max(moeglich, 0)) });
        zielScroll.current = null;
        return;
      }
      frame = requestAnimationFrame(versuchen);
    };
    frame = requestAnimationFrame(versuchen);
    return () => cancelAnimationFrame(frame);
  }, []);

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
  const staende = useMemo(() => {
    const aus = new Map<string, Pruefstand>();
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
      /* „In Arbeit" heisst: jemand hat hier schon etwas eingestellt. Das ist etwas anderes als ein
       * roher Vorschlag, den noch niemand angesehen hat, und für die Frage „was muss ich noch
       * anfassen" der wichtigere Unterschied. */
      const bearbeitet =
        Object.keys(gespeicherterStil).length > 0 ||
        (clip.zeitmarken?.length ?? 0) > 0 ||
        clip.composition.length > 1;
      aus.set(clip.id, pruefstand({ clip, freigabe: approvals.get(clip.id) ?? null, stand, bearbeitet }));
    }
    return aus;
  }, [clips, extras, approvals, transkriptVersion]);

  /* Wie viele Clips passen zu welchem Filter? Ein Clip kann in mehreren stehen: ein freigegebener
   * mit veraltetem Video ist beides. Das ist kein Fehler der Zählung, sondern der Punkt der drei
   * Achsen. */
  const zaehler = useMemo(() => {
    const aus = new Map<FilterId, number>();
    for (const f of [...FILTER_ORDNUNG, "alle" as FilterId]) {
      aus.set(f, [...staende.values()].filter((p) => passtZuFilter(p, f)).length);
    }
    return aus;
  }, [staende]);

  /* Die sichtbaren Clips: gefiltert und so sortiert, dass oben steht, was Arbeit braucht.
   * Verworfene sind nur unter ihrem eigenen Filter zu sehen - sonst wäre Verwerfen folgenlos. */
  const sichtbar = useMemo(() => {
    const liste = clips.filter((c) => {
      const p = staende.get(c.id);
      if (p && !passtZuFilter(p, filter)) return false;
      if (plattform !== "alle" && c.platform !== plattform) return false;
      if (person !== "alle" && (approvals.get(c.id)?.guest_name ?? "") !== person) return false;
      return true;
    });
    return [...liste].sort((a, b) => {
      const pa = staende.get(a.id);
      const pb = staende.get(b.id);
      const ra = pa ? rang(pa) : 9;
      const rb = pb ? rang(pb) : 9;
      if (ra !== rb) return ra - rb;
      return (a.composition[0]?.start ?? 0) - (b.composition[0]?.start ?? 0);
    });
  }, [clips, staende, filter, plattform, person, approvals]);

  /* Was aus der Auswahl wirklich freigegeben werden darf.
   *
   * Gerechnet wird über denselben aktionStand, den auch die einzelne Karte benutzt. Zwei
   * Rechnungen für dieselbe Frage wären genau der Fehler, der vorher zu „Korrektur nötig" neben
   * einem anklickbaren „Freigeben" geführt hat. */
  const sammel = useMemo(() => {
    const freigebbar: string[] = [];
    const gesperrt: string[] = [];
    let schonFrei = 0;
    let grund = "";
    for (const id of auswahl) {
      const p = staende.get(id);
      if (!p) continue;
      const a = aktionStand("freigeben", p);
      if (a.erlaubt) freigebbar.push(id);
      else if (p.redaktion === "freigegeben") schonFrei += 1;
      else {
        gesperrt.push(id);
        if (!grund) grund = a.grund ?? "";
      }
    }
    return { freigebbar, gesperrt, grund, schonFrei };
  }, [auswahl, staende]);

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
                /* Dasselbe Wort wie auf dem Knopf. „Als bereit markiert" nach einem Klick auf
                 * „Freigeben" lässt zweifeln, ob dasselbe passiert ist. */
                ? `${wieViele} freigegeben.`
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

  /* Nur anbieten, was es gibt. Ein Auswahlfeld mit einem einzigen Eintrag ist eine Frage ohne
   * Alternative und kostet trotzdem einen Blick. */
  const plattformen = useMemo(() => [...new Set(clips.map((c) => c.platform))].sort(), [clips]);
  const personen = useMemo(
    () => [...new Set([...approvals.values()].map((a) => a.guest_name).filter((n): n is string => Boolean(n)))].sort(),
    [approvals],
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
                <p className="mt-2 text-center text-xs text-text-2">Noch keine Untertitel. Sie entstehen beim Clippen.</p>
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
          {zaehler.get("fehler") ? `, ${zaehler.get("fehler")} mit einem Fehler` : ""}
          {zaehler.get("zu_pruefen") ? `, ${zaehler.get("zu_pruefen")} warten auf deine Entscheidung` : ""}
          {zaehler.get("postbereit") ? `, ${zaehler.get("postbereit")} bereit zum Posten` : ""}.
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

      {/* Der Meldebereich steht immer da, auch leer.
       *
       * Vorher entstand er erst mit der Meldung. Ein Screenreader kündigt eine Live-Region aber
       * nur an, wenn sie schon im Baum war, bevor sich ihr Inhalt ändert (W3C, WCAG 2.2, 4.1.3
       * Statusmeldungen). Wer nicht sieht, blieb also nach „12 Clips freigegeben" ohne Rückmeldung.
       * Leer nimmt der Bereich keinen Platz ein. */}
      <p
        role="status"
        aria-live="polite"
        className={cn(
          message && "rounded-inner border px-4 py-3 text-sm",
          message?.tone === "ok" && "border-line text-text",
          message && message.tone !== "ok" && "border-attention/50 bg-attention/10 text-text",
        )}
      >
        {message?.text ?? ""}
      </p>

      {/* Filter nach Zustand. Bei dreißig Clips ist „alle zeigen" keine Übersicht mehr, und die
          Frage lautet ohnehin fast immer „was muss ich noch ansehen". */}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Clips filtern">
        {([["alle", `Alle (${zaehler.get("alle") ?? 0})`]] as [FilterId, string][])
          .concat(
            FILTER_ORDNUNG.filter((f) => (zaehler.get(f) ?? 0) > 0).map(
              (f) => [f, `${FILTER_LABEL[f]} (${zaehler.get(f)})`] as [FilterId, string],
            ),
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

      {/* Plattform und Person. Nur da, wo es mehr als eine gibt: sonst wäre es eine Frage ohne
          Alternative. Marke und Video stehen im Kopf der Seite, für alle Clips hier gleich. */}
      {(plattformen.length > 1 || personen.length > 0) && (
        <div className="flex flex-wrap items-center gap-4">
          {plattformen.length > 1 && (
            <label className="flex items-center gap-2 text-sm text-text-2">
              Plattform
              <select
                value={plattform}
                onChange={(e) => setPlattform(e.target.value)}
                className="transition-soft rounded-inner border border-line bg-black/40 px-3 py-1.5 text-sm text-text hover:border-line-strong focus:border-white/50 focus:outline-none"
              >
                <option value="alle">Alle</option>
                {plattformen.map((pf) => (
                  <option key={pf} value={pf}>
                    {PLATFORM_LABELS[pf as keyof typeof PLATFORM_LABELS] ?? pf}
                  </option>
                ))}
              </select>
            </label>
          )}
          {personen.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-text-2">
              Freigabe bei
              <select
                value={person}
                onChange={(e) => setPerson(e.target.value)}
                className="transition-soft rounded-inner border border-line bg-black/40 px-3 py-1.5 text-sm text-text hover:border-line-strong focus:border-white/50 focus:outline-none"
              >
                <option value="alle">Allen</option>
                {personen.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          )}
          {(plattform !== "alle" || person !== "alle" || filter !== "alle") && (
            <button
              type="button"
              onClick={() => {
                setFilter("alle");
                setPlattform("alle");
                setPerson("alle");
              }}
              className="text-sm text-text-3 underline underline-offset-4 hover:text-text"
            >
              Filter zurücksetzen
            </button>
          )}
        </div>
      )}

      {/* Sammelaktionen. Erscheinen erst mit einer Auswahl: eine Leiste, die immer dasteht und
          meistens nichts tun kann, nimmt nur Platz weg. */}
      {auswahl.size > 0 && (
        <GlassCard padding="md" selected className="sticky top-4 z-20">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-text">
                {auswahl.size === 1 ? "Ein Clip ausgewählt" : `${auswahl.size} Clips ausgewählt`}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={sammelLaeuft || sammel.freigebbar.length === 0}
                  onClick={() => void reviewSetzen(sammel.freigebbar, "bereit")}
                >
                  {sammel.freigebbar.length === auswahl.size
                    ? "Freigeben"
                    : `${sammel.freigebbar.length} freigeben`}
                </Button>
                <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([...auswahl], "verworfen")}>
                  Verwerfen
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setAuswahl(new Set())}>
                  Auswahl aufheben
                </Button>
              </div>
            </div>
            {/* Eine Sammelfreigabe darf die Qualitätsprüfung nicht umgehen. Wer zwanzig Clips
                auswählt und freigibt, will nicht stillschweigend auch den freigeben, in dem eine
                Verneinung weggeschnitten wurde. Die betroffenen bleiben stehen und werden genannt. */}
            {/* Warum der Knopf eine kleinere Zahl nennt als die Auswahl. Ohne diese Zeile sieht
                „3 ausgewählt" neben „1 freigeben" nach einem Fehler aus. */}
            {sammel.schonFrei > 0 && (
              <p className="text-sm text-text-2">
                {sammel.schonFrei === 1
                  ? "Einer davon ist schon freigegeben."
                  : `${sammel.schonFrei} davon sind schon freigegeben.`}
              </p>
            )}
            {sammel.gesperrt.length > 0 && (
              <p className="text-sm text-attention">
                {sammel.gesperrt.length === 1
                  ? "Ein ausgewählter Clip bleibt stehen: "
                  : `${sammel.gesperrt.length} ausgewählte Clips bleiben stehen: `}
                {sammel.grund}{" "}
                <button
                  type="button"
                  onClick={() => {
                    setAuswahl(new Set(sammel.gesperrt));
                    setFilter("fehler");
                  }}
                  className="underline underline-offset-4 hover:text-text"
                >
                  Diese ansehen
                </button>
              </p>
            )}
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
            {filter === "alle" ? "Hier ist nichts." : `Kein Clip unter „${FILTER_LABEL[filter]}“.`}
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
          const p = staende.get(clip.id)!;
          const kandidat = candidates.find((k) => k.id === clip.candidate_id) ?? null;
          const progress = clip.status === "rendering" ? (ev?.progress ?? 0) : isDone(clip) ? 1 : 0;
          const approval = approvals.get(clip.id);
          const blocked = exportBlocked(clip, approval);
          const mp4 = clip.file_key && mediaBase ? `/api/projects/${sourceId}/clips/${clip.id}/download?kind=mp4` : null;
          /* Jede Handlung fragt denselben Rechner. Vorher entschied jeder Knopf für sich, ob er
           * anklickbar ist, und daher stand „Korrektur nötig" neben einem offenen „Freigeben". */
          const darfFreigeben = aktionStand("freigeben", p);
          const darfLaden = aktionStand("herunterladen", p, {
            exportGesperrt: blocked ? EXPORT_BLOCKED_MESSAGE : demo ? "Im Testmodus gibt es keine Dateien" : null,
            hatDatei: Boolean(mp4),
          });
          const darfGast = aktionStand("gast_fragen", p);
          const naechste = hauptaktion(p);
          const bearbeiten = `/projekte/${sourceId}/clips/${clip.id}`;
          const poster = mediaUrl(mediaBase, clip.poster_key);
          const video = isDone(clip) ? mediaUrl(mediaBase, clip.file_key) : null;
          /* Ein Bild aus dem Clip, auch bevor er gebaut ist. Genommen wird ein Moment kurz nach
           * dem Anfang: am Schnittpunkt selbst steht oft ein Übergang oder ein schwarzes Bild,
           * und ein schwarzes Kästchen hilft beim Wiedererkennen nicht. */
          const momentS = (clip.composition[0]?.start ?? 0) + 1.5;
          const moment = !video && !poster && quelleSrc ? `${quelleSrc}#t=${momentS.toFixed(1)}` : null;
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
          const ueberschrift = thema(kandidat?.rubric.text ?? "") || `${PLATFORM_LABELS[clip.platform]}-Clip`;

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
                  ) : moment ? (
                    <video src={moment} muted playsInline preload="metadata" className="pointer-events-none h-full w-full object-cover" />
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

                  {/* Warum hat der Computer diesen Ausschnitt vorgeschlagen? Der Satz kommt aus
                      der Analyse dieses Clips und stand vorher zugeklappt ganz unten. Wer prüfen
                      soll, ob ein Vorschlag taugt, braucht die Begründung zuerst und nicht zuletzt. */}
                  {kandidat?.rubric.proposal_why && (
                    <p className="line-clamp-2 text-sm text-text-2">
                      {/* Kein „weil" davor: der Satz aus der Analyse ist ein Hauptsatz, und
                          „Vorgeschlagen, weil die Zahl steht am Anfang" ist kein Deutsch. */}
                      <span className="text-text-3">Warum vorgeschlagen: </span>
                      {kandidat.rubric.proposal_why}
                    </p>
                  )}

                  {/* Die drei Achsen. Gezeigt wird, was etwas aussagt: die redaktionelle
                      Entscheidung immer, Qualität und Datei nur, wenn sie nicht in Ordnung sind.
                      Eine Karte mit drei grünen Plaketten sagt dasselbe wie eine mit keiner und
                      kostet dreimal so viel Aufmerksamkeit. */}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    {p.postbereit ? (
                      <span
                        title="Freigegeben, ohne offenen Fehler, und die geclippte Datei ist aktuell."
                        className="inline-flex h-6 items-center rounded-pill border border-brand/60 bg-brand/15 px-2.5 text-[12px] font-medium text-text"
                      >
                        Bereit zum Posten
                      </span>
                    ) : (
                      <Pille ton={p.redaktion === "freigegeben" ? "gut" : "ruhig"} titel={REDAKTION_SATZ[p.redaktion]}>
                        {REDAKTION_LABEL[p.redaktion]}
                      </Pille>
                    )}
                    {p.qualitaet === "fehler" && (
                      <Pille ton="fehler" titel="Am Inhalt stimmt etwas nicht.">
                        Fehler
                      </Pille>
                    )}
                    {p.qualitaet === "hinweis" && (
                      <Pille ton="ruhig" titel="Brauchbar, aber einer Ansicht wert.">
                        Hinweis
                      </Pille>
                    )}
                    {p.datei !== "aktuell" && (
                      <Pille ton={p.datei === "veraltet" || p.datei === "fehlgeschlagen" ? "achtung" : "ruhig"} titel={DATEI_SATZ[p.datei]}>
                        {DATEI_LABEL[p.datei]}
                      </Pille>
                    )}
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

                  {/* Der wichtigste Befund, und nur der. Die übrigen stehen im Editor, wo man
                      auch etwas gegen sie tun kann; hier würde eine Liste die Entscheidung
                      erschweren statt sie zu stützen. */}
                  {p.befunde[0] && <BefundZeile befund={p.befunde[0]} ziel={bearbeiten} rest={p.befunde.length - 1} />}

                  {/* Was rechtlich am Clip hängt, bleibt sichtbar. */}
                  {isDone(clip) && (clip.ad_label || clip.provenance.source_credit) && (
                    <div className="flex flex-wrap gap-1.5">
                      {clip.ad_label && <Badge>Werbelabel: {clip.ad_label}</Badge>}
                      {clip.provenance.source_credit && <Badge>{clip.provenance.source_credit}</Badge>}
                    </div>
                  )}

                  {/* Eine hervorgehobene Handlung, der Rest eine Ebene tiefer.
                      Vorher standen hier sechs gleichrangige Knöpfe. Sechs Möglichkeiten sind
                      keine Führung, sondern eine Auswahlaufgabe vor der eigentlichen Aufgabe. */}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {naechste.id === "pruefen" && (
                      <Button size="sm" onClick={() => void openZoom(clip)}>
                        Clip prüfen
                      </Button>
                    )}
                    {(naechste.id === "beheben" || naechste.id === "neu_bauen") && (
                      <Link
                        href={bearbeiten}
                        className="transition-soft inline-flex h-9 items-center rounded-pill bg-text px-4 text-sm font-medium text-black hover:bg-white"
                      >
                        {naechste.label}
                      </Link>
                    )}
                    {naechste.id === "herunterladen" &&
                      (darfLaden.erlaubt && mp4 ? (
                        <a
                          href={mp4}
                          download
                          className="transition-soft inline-flex h-9 items-center gap-2 rounded-pill bg-text px-4 text-sm font-medium text-black hover:bg-white"
                        >
                          <IconDownload />
                          Herunterladen
                        </a>
                      ) : (
                        <GesperrtKnopf grund={darfLaden.grund}>
                          <IconDownload />
                          Herunterladen
                        </GesperrtKnopf>
                      ))}
                    {naechste.id === "zurueckholen" && (
                      <Button size="sm" disabled={sammelLaeuft} onClick={() => void reviewSetzen([clip.id], "offen")}>
                        Zurückholen
                      </Button>
                    )}
                    {naechste.id === "warten" && (
                      <span className="inline-flex h-9 items-center rounded-pill border border-line px-4 text-sm text-text-3">
                        Wird gebaut
                      </span>
                    )}

                    {/* Freigeben steht neben der Hauptaktion, solange es noch aussteht: das ist die
                        Entscheidung, um die es auf dieser Seite geht. Gesperrt sagt es, warum. */}
                    {p.redaktion !== "verworfen" && p.redaktion !== "freigegeben" && naechste.id !== "pruefen" && (
                      darfFreigeben.erlaubt ? (
                        <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([clip.id], "bereit")}>
                          Freigeben
                        </Button>
                      ) : (
                        <GesperrtKnopf grund={darfFreigeben.grund}>Freigeben</GesperrtKnopf>
                      )
                    )}
                    {p.redaktion !== "verworfen" && naechste.id === "pruefen" && (
                      darfFreigeben.erlaubt ? (
                        <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([clip.id], "bereit")}>
                          Freigeben
                        </Button>
                      ) : (
                        <GesperrtKnopf grund={darfFreigeben.grund}>Freigeben</GesperrtKnopf>
                      )
                    )}

                    <Weitere
                      clip={clip}
                      stand={p}
                      bearbeiten={bearbeiten}
                      mp4={mp4}
                      darfLaden={darfLaden}
                      canDelete={canDelete}
                      laeuft={sammelLaeuft}
                      onAnsehen={() => void openZoom(clip)}
                      onReview={(r) => void reviewSetzen([clip.id], r)}
                      onLoeschen={() => setDeleteTarget(clip)}
                    />
                  </div>

                  {/* Die Bewertung im Einzelnen. Der Grund steht schon oben; hier geht es um die
                      Frage „woran hat der Computer das festgemacht", und die stellt sich nur, wenn
                      man zweifelt. */}
                  {kandidat?.rubric.proposal_why && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-sm text-text-2 underline-offset-4 hover:text-text hover:underline">
                        Bewertung im Einzelnen
                      </summary>
                      <div className="mt-2 flex flex-col gap-2 rounded-inner border border-line p-3">
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
                      canRequest={canRequestGuest && darfGast.erlaubt}
                      gesperrtGrund={darfGast.grund}
                      planAllows={planAllowsGuest}
                      planName={planName}
                      onRequested={onRequested}
                    />
                    {/* Was aus dem Clip geworden ist. Ohne diese Zeile endete die Kette am
                        fertigen Clip: Posten und Kennzahlen gab es nur als Schnittstelle, und
                        „Tests" und „Berichte" konnten deshalb nie etwas zeigen. */}
                    {p.redaktion === "freigegeben" && (
                      <Gepostet sourceId={sourceId} clipId={clip.id} plattform={clip.platform} canPublish={canPublish} />
                    )}
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
const IconWarn = ({ className }: { className?: string }) => (
  <Svg size={14} className={cn("shrink-0", className)}>
    <path d="M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </Svg>
);


/* Eine Plakette. Farbe nur da, wo sie etwas bedeutet: ein Fehler ist dringend, eine Freigabe ist
 * erledigt, der Rest bleibt ruhig. Eine Oberfläche, in der alles bunt ist, sagt nichts mehr. */
function Pille({
  ton,
  titel,
  children,
}: {
  ton: "gut" | "achtung" | "fehler" | "ruhig";
  titel?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={titel}
      className={cn(
        "inline-flex h-6 items-center rounded-pill border px-2.5 text-[12px] font-medium",
        ton === "gut" && "border-brand/60 bg-brand/15 text-text",
        ton === "achtung" && "border-attention/60 bg-attention/15 text-text",
        ton === "fehler" && "border-danger/60 bg-danger/15 text-text",
        ton === "ruhig" && "border-line text-text-2",
      )}
    >
      {children}
    </span>
  );
}

/* Der wichtigste Befund als anklickbare Zeile.
 *
 * Drei Dinge stehen darin, und alle drei werden gebraucht: was los ist, wo es ist, und der Weg
 * dorthin. Vorher stand hier „82 Stellen laufen schnell durch" ohne Ort und ohne Weg - eine Zahl,
 * mit der niemand etwas anfangen kann. */
function BefundZeile({ befund, ziel, rest }: { befund: Befund; ziel: string; rest: number }) {
  const schwer = befund.schwere === "fehler";
  return (
    <Link
      href={ziel}
      className={cn(
        "transition-soft flex items-start gap-1.5 self-start rounded-[10px] border px-3 py-2 text-xs text-text",
        schwer ? "border-danger/50 bg-danger/10 hover:border-danger" : "border-attention/50 bg-attention/10 hover:border-attention",
      )}
    >
      <IconWarn className={cn("mt-0.5 shrink-0", schwer ? "text-danger" : "text-attention")} />
      <span>
        {befund.text}
        {befund.stelle && <span className="text-text-2">{` Am engsten bei „${befund.stelle}“.`}</span>}
        {rest > 0 && <span className="text-text-3">{` Und ${rest} weiterer Punkt${rest === 1 ? "" : "e"}.`}</span>}{" "}
        <span className="underline underline-offset-4">{schwer ? "Beheben" : "Ansehen"}</span>
      </span>
    </Link>
  );
}

/* Eine Handlung, die gerade nicht geht, mit dem Grund daneben.
 *
 * Der Grund steht sichtbar und nicht nur im Titelattribut. Ein Tooltip erreicht nur, wer eine Maus
 * hat und ahnt, dass dort etwas steht. */
function GesperrtKnopf({ grund, children }: { grund: string | null; children: ReactNode }) {
  return (
    <span className="inline-flex flex-col gap-0.5">
      <span
        aria-disabled="true"
        title={grund ?? undefined}
        className="inline-flex h-9 cursor-not-allowed items-center gap-2 rounded-pill border border-line px-4 text-sm font-medium text-text-3"
      >
        {children}
      </span>
      {grund && <span className="max-w-[260px] text-xs leading-snug text-text-3">{grund}</span>}
    </span>
  );
}

/* Die zweite Ebene: alles, was es auch noch gibt, hinter einer benannten Klappe.
 *
 * „Vorschlag verwerfen" und „Datei löschen" stehen hier ausdrücklich getrennt und mit Erklärung.
 * Vorher stand Verwerfen als Knopf und Löschen als Mülleimer-Zeichen daneben - zwei sehr
 * verschiedene Dinge, die gleich aussahen und nebeneinander lagen. */
function Weitere({
  clip,
  stand,
  bearbeiten,
  mp4,
  darfLaden,
  canDelete,
  laeuft,
  onAnsehen,
  onReview,
  onLoeschen,
}: {
  clip: Clip;
  stand: Pruefstand;
  bearbeiten: string;
  mp4: string | null;
  darfLaden: { erlaubt: boolean; grund: string | null };
  canDelete: boolean;
  laeuft: boolean;
  onAnsehen: () => void;
  onReview: (r: Clip["review"]) => void;
  onLoeschen: () => void;
}) {
  const [offen, setOffen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOffen((o) => !o)}
        aria-expanded={offen}
        className="transition-soft inline-flex h-9 items-center rounded-pill border border-line px-3.5 text-sm text-text-2 hover:border-line-strong hover:text-text"
      >
        Mehr
      </button>
      {offen && (
        <>
          {/* Klick daneben schliesst. Ohne das bleibt die Klappe offen, wenn man woanders hinsieht. */}
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setOffen(false)}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div className="absolute right-0 z-40 mt-1 flex w-[260px] flex-col gap-1 rounded-inner border border-line-strong bg-[#0b0b14] p-1.5 shadow-xl">
            <MenuKnopf onClick={() => { setOffen(false); onAnsehen(); }}>Groß ansehen</MenuKnopf>
            <MenuLink href={bearbeiten} onClick={() => setOffen(false)}>
              Bearbeiten
            </MenuLink>
            {mp4 && darfLaden.erlaubt && (
              <MenuLink href={mp4} download onClick={() => setOffen(false)}>
                Herunterladen
              </MenuLink>
            )}
            {stand.redaktion === "freigegeben" && (
              <MenuKnopf disabled={laeuft} onClick={() => { setOffen(false); onReview("offen"); }}>
                Freigabe zurücknehmen
              </MenuKnopf>
            )}
            {stand.redaktion === "verworfen" ? (
              <MenuKnopf disabled={laeuft} onClick={() => { setOffen(false); onReview("offen"); }}>
                Zurückholen
              </MenuKnopf>
            ) : (
              <MenuKnopf
                disabled={laeuft}
                onClick={() => { setOffen(false); onReview("verworfen"); }}
                hinweis="Der Clip bleibt erhalten und lässt sich zurückholen."
              >
                Vorschlag verwerfen
              </MenuKnopf>
            )}
            {canDelete && (
              <MenuKnopf
                ton="danger"
                disabled={clip.status === "rendering"}
                onClick={() => { setOffen(false); onLoeschen(); }}
                hinweis="Video, Untertitel und Poster werden endgültig gelöscht."
              >
                Datei endgültig löschen
              </MenuKnopf>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function MenuKnopf({
  children,
  onClick,
  disabled,
  ton,
  hinweis,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  ton?: "danger";
  hinweis?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "transition-soft rounded-[8px] px-3 py-2 text-left text-sm text-text hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-40",
        ton === "danger" && "text-danger hover:bg-danger/10",
      )}
    >
      {children}
      {hinweis && <span className="mt-0.5 block text-xs font-normal text-text-3">{hinweis}</span>}
    </button>
  );
}

function MenuLink({
  children,
  href,
  onClick,
  download,
}: {
  children: ReactNode;
  href: string;
  onClick: () => void;
  download?: boolean;
}) {
  return (
    <Link
      href={href}
      download={download}
      onClick={onClick}
      className="transition-soft rounded-[8px] px-3 py-2 text-left text-sm text-text hover:bg-white/8"
    >
      {children}
    </Link>
  );
}

