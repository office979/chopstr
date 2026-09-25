"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { SilentPreview, type PreviewFont } from "@/components/clips/SilentPreview";
import { Modal } from "@/components/ui/Modal";
import type { Aspect, Candidate, CaptionVersion, Clip, GuestApproval, HookVersion, PipelineEvent } from "@/lib/repo/types";
import {
  EXPORT_BLOCKED_MESSAGE,
  exportBlocked,
  FREIGABE_VERALTET_MESSAGE,
  freigabeVeraltet,
  latestByClip,
} from "@/lib/guest/approval";
import { stilPruefen } from "@/lib/clips/caption-style";
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
  FREIGABE_LABEL,
  FREIGABE_SATZ,
  freigabeStand,
  type FreigabeStand,
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
import { ASPECT_SIZE, PLATFORM_DEFAULT_PRESET } from "@/lib/clips/presets";
import { FASSUNG_FORMATE, FORMAT_HILFT_BEI, fassungMoeglich } from "@/lib/clips/fassungen";
import { kommtVomClip } from "@/lib/clips/rueckweg";
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
  /* Das Format der Quelle. Weicht das Zielformat davon ab, wurde das Bild beschnitten - und dann
   * ist die Frage, ob die richtige Person im Ausschnitt steht, eine echte Frage. */
  quellAspekt: Aspect | null;
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
  quellAspekt,
}: Props) {
  const [clips, setClips] = useState<Clip[]>(initialClips);
  const [extras, setExtras] = useState<Record<string, ClipExtras>>(publishing?.extras ?? {});
  const [approvals, setApprovals] = useState<Map<string, GuestApproval>>(() => latestByClip(guestApprovals));
  const [deleteTarget, setDeleteTarget] = useState<Clip | null>(null);
  /* Clip, der gerade groß in einem Fenster läuft. Nicht Vollbild: das Fenster bleibt Teil der Seite. */
  const [zoomClip, setZoomClip] = useState<Clip | null>(null);
  const [deleting, setDeleting] = useState(false);
  /* Welche Karte hat ihre Klappe offen?
   *
   * Die Klappe wurde von der naechsten Karte ueberdeckt und war halb abgeschnitten. Grund ist
   * `backdrop-filter` in der Glaskarte: das erzeugt einen eigenen Stapelkontext, und ein z-index
   * innerhalb der Karte kommt darueber nicht hinaus. Also hebt sich die ganze Karte, solange ihre
   * Klappe offen ist - dort konkurriert sie mit den Geschwistern und gewinnt. */
  const [klappeOffen, setKlappeOffen] = useState<string | null>(null);
  const [fassungFuer, setFassungFuer] = useState<Clip | null>(null);
  const [fassungLaeuft, setFassungLaeuft] = useState(false);
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
    /* Drei Wege auf diese Seite, drei Antworten:
     *
     *   über eine Zahl der Übersicht  -> deren Filter, sonst wäre der Klick folgenlos
     *   zurück aus einem Clip          -> der gemerkte Stand, dort wurde gerade gearbeitet
     *   frisch, etwa über die Brotkrume -> „Alle"
     *
     * Der dritte Fall lief vorher in den zweiten: man kam an und sah die Auswahl von vorhin,
     * also vielleicht zwei von drei Clips - ohne zu wissen warum. */
    const t = window.setTimeout(
      ausAdresse && (FILTER_ORDNUNG as string[]).includes(ausAdresse)
        ? () => {
            setFilter(ausAdresse as FilterId);
            gelesen.current = true;
          }
        : kommtVomClip(sourceId)
          ? holen
          : () => {
              gelesen.current = true;
            },
      0,
    );
    window.addEventListener("pagehide", merken);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("pagehide", merken);
      merken();
    };
  }, [merkschluessel, merken, sourceId]);

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
      /* „In Arbeit" heisst: jemand hat hier schon etwas eingestellt. Das ist etwas anderes als ein
       * roher Vorschlag, den noch niemand angesehen hat, und für die Frage „was muss ich noch
       * anfassen" der wichtigere Unterschied. */
      const bearbeitet =
        Object.keys(gespeicherterStil).length > 0 ||
        (clip.zeitmarken?.length ?? 0) > 0 ||
        clip.composition.length > 1;
      aus.set(
        clip.id,
        pruefstand({
          clip,
          freigabe: approvals.get(clip.id) ?? null,
          bearbeitet,
          kandidat: candidates.find((k) => k.id === clip.candidate_id) ?? null,
          quellformatAbweichend: quellAspekt != null && quellAspekt !== clip.aspect,
        }),
      );
    }
    return aus;
  }, [clips, extras, approvals, candidates, quellAspekt]);

  /* Wie viele Clips passen zu welchem Filter? Ein Clip kann in mehreren stehen: ein freigegebener
   * ohne Fehler ist freigegeben UND postbereit. Das ist kein Fehler der Zählung, sondern der Punkt
   * der drei Achsen. */
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

  /* Welche Clips gehen zur Bestätigung hinaus?
   *
   * Die ausgewählten, wenn welche ausgewählt sind - sonst alle sichtbaren, über die noch nicht
   * entschieden ist und von denen es eine fertige Datei gibt. Einen Clip ohne Datei zu schicken
   * hiesse, jemanden auf eine leere Seite zu schicken; einen abgelehnten noch einmal zu schicken
   * hiesse, dieselbe Frage zweimal zu stellen. */
  const zurFreigabe = useMemo(() => {
    const quelle = auswahl.size > 0 ? sichtbar.filter((c) => auswahl.has(c.id)) : sichtbar;
    return quelle
      .filter((c) => {
        const p = staende.get(c.id);
        if (!p) return false;
        if (auswahl.size > 0) return Boolean(c.file_key);
        /* Ohne Auswahl nur die, die noch nie hinausgingen. „Bestätigung ausstehend" heisst: die
         * Frage läuft schon - sie ein zweites Mal zu stellen wäre die gleiche Frage zweimal. */
        return Boolean(c.file_key) && freigabeStand(p, approvals.get(c.id) ?? null) === "nicht_gesendet";
      })
      .map((c) => ({ id: c.id, label: `${PLATFORM_LABELS[c.platform]} ${ASPECT_LABELS[c.aspect]}` }));
  }, [auswahl, sichtbar, staende, approvals]);

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

  /* Eine angeforderte Freigabe kommt aus der Antwort der Route zurück - es braucht also keine
   * zweite Abfrage, um den Zustand an der Karte richtig zu stellen. */
  const onRequested = useCallback(
    (neue: GuestApproval[]) => {
      setApprovals((prev) => {
        const next = new Map(prev);
        for (const a of neue) next.set(a.clip_id, a);
        return next;
      });
      const betroffen = new Set(neue.map((a) => a.clip_id));
      applyClips(clipsRef.current.map((c) => (betroffen.has(c.id) ? { ...c, guest_approval_required: true } : c)));
    },
    [applyClips],
  );

  /* Nach dem Verschicken sind die Kreuze erledigt. Einen Knopf „Auswahl aufheben" gibt es nicht
   * mehr, also hebt sie sich selbst auf - sonst bliebe sie stehen und die nächste Anfrage ginge
   * versehentlich an dieselben Clips. */
  const freigabeFertig = useCallback(() => setAuswahl(new Set()), []);

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

  /* Eine weitere Fassung desselben Moments in einem anderen Format.
   *
   * Gewählt wird das FORMAT und nicht die Plattform. TikTok, Reels und Shorts sind bei chopstr
   * alle hochkant: eine zweite Datei dafür wäre Bild für Bild dieselbe Datei mit einem anderen
   * Wort daneben. Was das Video wirklich verändert, ist das Format - anderer Bildausschnitt,
   * anderer sicherer Bereich für die Untertitel, andere Schriftgrösse. */
  const fassungAnlegen = useCallback(
    async (aspect: Aspect) => {
      if (!fassungFuer) return;
      setFassungLaeuft(true);
      setMessage(null);
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${fassungFuer.id}/fassungen`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ aspect }),
        });
        const data = (await res.json()) as ApiError & { message?: string; clip?: Clip };
        if (!res.ok || !data.clip) throw new Error(data.error ?? "Die Fassung konnte nicht angelegt werden");
        applyClips([...clips, data.clip]);
        setMessage({ tone: "ok", text: data.message ?? "Die Fassung wird geclippt." });
        setFassungFuer(null);
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Die Fassung konnte nicht angelegt werden" });
      } finally {
        setFassungLaeuft(false);
      }
    },
    [fassungFuer, sourceId, applyClips, clips],
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

      {/* Eine weitere Fassung desselben Moments.
          Gewählt wird das Format, nicht die Plattform: TikTok, Reels und Shorts sind bei chopstr
          alle hochkant, und eine zweite Datei dafür wäre dieselbe Datei. Das steht auch so da,
          statt vier Plattformen anzubieten und drei davon dasselbe liefern zu lassen. */}
      <Modal
        open={fassungFuer != null}
        onClose={() => !fassungLaeuft && setFassungFuer(null)}
        title="Weitere Fassung anlegen"
        description="Denselben Moment noch einmal clippen, in einem anderen Format. Bildausschnitt, Untertitelbereich und Schriftgröße passen sich an."
      >
        <div className="flex flex-col gap-3">
          {fassungFuer && (
            <FassungWahl
              vorhanden={clips
                .filter((c) => c.candidate_id === fassungFuer.candidate_id && c.status !== "deleted")
                .map((c) => c.aspect)}
              busy={fassungLaeuft}
              onWaehlen={fassungAnlegen}
            />
          )}
          <p className="text-xs text-text-3">
            TikTok, Reels und Shorts bekommen bei dir dasselbe Hochformat. Dafür brauchst du keine
            zweite Datei, nur einen anderen Text zum Posten.
          </p>
          {/* Der Untertitelstil hängt am Format, nicht am Geschmack: hochkant Wort für Wort,
              quadratisch und quer ruhig in zwei Zeilen. Das ist so gewollt, aber wer es nicht
              weiss, hält die zweite Fassung für falsch gebaut. */}
          <p className="text-xs text-text-3">
            Hochkant kommen die Untertitel Wort für Wort, quadratisch und quer ruhig in zwei Zeilen.
            Im Clip lässt sich das danach ändern.
          </p>
          <div className="flex justify-end">
            <Button variant="ghost" onClick={() => setFassungFuer(null)} disabled={fassungLaeuft}>
              Abbrechen
            </Button>
          </div>
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
          {zaehler.get("postbereit") ? `, ${zaehler.get("postbereit")} bereit zum Posten` : ""}.
        </p>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {live && (
            <span className="flex items-center gap-2 text-ai-soft">
              <span className="h-1.5 w-1.5 rounded-full bg-ai-soft" aria-hidden="true" />
              {RENDER_STEP.label} live
            </span>
          )}
          {connection === "error" && !allSettled && <span className="text-attention">Verbindung unterbrochen, versuche erneut</span>}
          {demo && <Badge tone="ai">Testmodus</Badge>}
          <FreigabeSenden
            clips={zurFreigabe}
            erlaubt={canRequestGuest}
            tarifErlaubt={planAllowsGuest}
            tarifName={planName}
            ausgewaehlt={auswahl.size}
            onFreigabe={onRequested}
            onFertig={freigabeFertig}
          />
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

      {/* Hier stand eine Sammelleiste: „2 Clips ausgewählt", „0 freigeben", „Verwerfen",
          „Auswahl aufheben". Sie ist weg. Freigegeben wird nicht mehr vom Team selbst, sondern von
          der Person, für die die Clips gemacht werden - und der Weg dorthin ist der Knopf oben:
          Clips ankreuzen, „Zur Freigabe senden", Mailadresse, fertig. Ein zweiter Knopf mit
          demselben Wort und einer anderen Bedeutung war genau die Verwirrung, die hier weg soll. */}

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
          /* Wurde der Clip nach der Freigabe noch angefasst? Dann hat die Person eine andere
           * Fassung gesehen als die, die jetzt herauskäme. */
          const freigabeAlt = freigabeVeraltet(approval, clip.updated_at);
          const mp4 = clip.file_key && mediaBase ? `/api/projects/${sourceId}/clips/${clip.id}/download?kind=mp4` : null;
          /* Jede Handlung fragt denselben Rechner. Vorher entschied jeder Knopf für sich, ob er
           * anklickbar ist, und daher stand „Korrektur nötig" neben einem offenen „Freigeben". */
          const darfLaden = aktionStand("herunterladen", p, {
            exportGesperrt: blocked ? EXPORT_BLOCKED_MESSAGE : demo ? "Im Testmodus gibt es keine Dateien" : null,
            hatDatei: Boolean(mp4),
          });
          const naechste = hauptaktion(p);
          /* Der eine Zustand, der an der Karte steht. Gerechnet aus denselben drei Achsen und
             der Antwort des Gastes - siehe lib/clips/pruefstand.freigabeStand. */
          const freigabe_stand = freigabeStand(p, approval ?? null);
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
                className={cn(
                  "flex min-w-0 gap-4",
                  klappeOffen === clip.id && "z-50",
                  glitchGroups.has(clip.candidate_id ?? "ohne") && "spectrum-glitch",
                )}
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

                  {/* „Warum vorgeschlagen: Heuristik ohne Sprachmodell, Diskursmarker …" stand
                      hier einmal. Das ist die Arbeitsweise der Maschine und keine Auskunft, mit
                      der ein Kunde etwas anfängt - sie stand an jeder Karte und schob das
                      Wesentliche nach unten. */}

                  {/* EIN Zustand, nicht drei Plaketten nebeneinander.
                      Vorher standen „Vorgeschlagen", „Fehler" und „Wird geclippt" nebeneinander,
                      und wer die Karte ansah, musste sie selbst zusammenzählen. Die vier Zustände
                      beantworten die Frage, um die es hier geht: darf das so gepostet werden?
                      „Wird geclippt" steht weiter daneben, denn das ist keine Antwort darauf,
                      sondern eine laufende Maschine. */}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <Pille ton={FREIGABE_TON[freigabe_stand]} titel={FREIGABE_SATZ[freigabe_stand]}>
                      {FREIGABE_LABEL[freigabe_stand]}
                    </Pille>
                    {/* Die Maschine daneben, getrennt von der Zusage: „wird geclippt" und „das
                        Clippen ist gescheitert" sind keine Antwort auf „darf das raus", aber man
                        muss sie sehen. */}
                    {p.datei !== "aktuell" && (
                      <Pille ton={p.datei === "fehlgeschlagen" ? "achtung" : "ruhig"} titel={DATEI_SATZ[p.datei]}>
                        {DATEI_LABEL[p.datei]}
                      </Pille>
                    )}
                    {/* Die Plattform als Plakette: bei mehreren Formaten desselben Ausschnitts ist
                        sie der Unterschied, und der muss ins Auge fallen. */}
                    <Badge className="h-6 px-2.5 text-[11px]">{PLATFORM_LABELS[clip.platform]}</Badge>
                    <span className="font-mono text-xs tabular-nums text-text-2">{formatClipDuration(duration)}</span>
                    <span className="text-xs text-text-3">{ASPECT_LABELS[clip.aspect]}</span>
                    {/* „Aufbau zur Pointe", „Schritt für Schritt" stand hier einmal: die Form,
                        die die Analyse im Clip erkannt hat. Das ist eine Einordnung für die
                        Maschine und keine Auskunft, mit der jemand etwas entscheidet. */}
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

                  {/* Hier stand ein Warnstreifen mit dem wichtigsten Befund - „Ohne KI gefunden",
                      „An mehreren Stellen wird zügig gesprochen". Er ist weg. An fast jeder Karte
                      stand einer, die Sätze sagten dem Kunden nichts, und was wirklich sperrt,
                      steht ohnehin am gesperrten Knopf: dort, wo es gerade im Weg ist. */}

                  {/* Was rechtlich am Clip hängt, bleibt sichtbar. */}
                  {isDone(clip) && (clip.ad_label || clip.provenance.source_credit) && (
                    <div className="flex flex-wrap gap-1.5">
                      {clip.ad_label && <Badge>Werbelabel: {clip.ad_label}</Badge>}
                      {clip.provenance.source_credit && <Badge>{clip.provenance.source_credit}</Badge>}
                    </div>
                  )}

                  {/* Eine Zeile, eine hervorgehobene Handlung, der Rest eine Ebene tiefer.
                      Vorher standen hier sechs gleichrangige Knöpfe. Sechs Möglichkeiten sind
                      keine Führung, sondern eine Auswahlaufgabe vor der eigentlichen Aufgabe. */}
                  {/* Immer derselbe erste Knopf: Herunterladen.
                      Vorher stand hier je nach Zustand „Clip prüfen", „Fehler beheben", „Video
                      clippen" oder „Herunterladen" - vier verschiedene Knöpfe an derselben Stelle,
                      und man musste jede Karte einzeln lesen, um zu wissen, was der Klick tut.
                      Gesperrt sagt er, was ihm fehlt. */}
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-2">
                    {darfLaden.erlaubt && mp4 ? (
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
                    )}
                    {naechste.id === "zurueckholen" && (
                      <Button size="sm" variant="ghost" disabled={sammelLaeuft} onClick={() => void reviewSetzen([clip.id], "offen")}>
                        Zurückholen
                      </Button>
                    )}

                    <Weitere
                      onOffen={(o) => setKlappeOffen(o ? clip.id : null)}
                      onFassung={() => setFassungFuer(clip)}
                      clip={clip}
                      stand={p}
                      bearbeiten={bearbeiten}
                      mp4={mp4}
                      darfLaden={darfLaden}
                      canDelete={canDelete}
                      laeuft={sammelLaeuft}
                      onReview={(r) => void reviewSetzen([clip.id], r)}
                      onLoeschen={() => setDeleteTarget(clip)}
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

                  {/* Was die gefragte Person geschrieben hat.
                      Hier stand „Noch gesperrt: Du wartest auf die Antwort" - an einem Clip, der
                      längst eine Antwort hatte. Das war die Sperrbegründung des Downloads, und die
                      passte nicht mehr: seit jede Antwort die Datei freigibt, ist sie nur noch
                      richtig, solange wirklich niemand geantwortet hat. An ihrer Stelle steht das,
                      wofür gefragt wurde: das Feedback. */}
                  {approval?.decision != null && (
                    <p className="text-sm text-text-2">
                      <span className="text-text-3">Rückmeldung: </span>
                      {approval.comment?.trim() ? approval.comment : "Kein Feedback"}
                    </p>
                  )}

                  {/* Der Gast hat eine andere Fassung gesehen: ein ganzer Satz, der eine eigene
                      Zeile braucht. */}
                  {freigabeAlt && <p className="text-xs text-attention">{FREIGABE_VERALTET_MESSAGE}</p>}
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
        /* Grün, und zwar sichtbar: auch das WORT ist grün. Mit weisser Schrift auf zartem
           Grün las sich „Freigegeben" auf der blauen Karte wie jede andere Plakette - der eine
           Zustand, den man aus zwei Metern Entfernung erkennen will, war der unauffälligste. */
        ton === "gut" && "border-gut/70 bg-gut/20 text-gut",
        ton === "achtung" && "border-attention/60 bg-attention/15 text-text",
        ton === "fehler" && "border-danger/60 bg-danger/15 text-text",
        ton === "ruhig" && "border-line text-text-2",
      )}
    >
      {children}
    </span>
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

/* Clips zur Bestätigung schicken.
 *
 * Die Freigabe ist die Zusage der Person, für die die Clips gemacht werden. Sie stand vorher als
 * „Jemanden um Freigabe bitten" an JEDER Karte: bei vierzehn Clips vierzehnmal derselbe Knopf,
 * vierzehnmal dieselbe Mailadresse eintippen, und die Person bekam vierzehn Links. Gefragt wird
 * aber einmal, für alles, was hinausgehen soll - und sie bekommt EINEN Link.
 *
 * DIE E-MAIL IST FREIWILLIG. Der Link entsteht so oder so und steht sofort zum Kopieren da; die
 * meisten schicken ihn über WhatsApp oder Slack weiter. Ist eine Adresse dabei, geht zusätzlich
 * eine Mail hinaus.
 *
 * WARUM DIE FREIGABE EINEN NAMEN HAT. Wer das Fenster schliesst, ohne den Link zu verschicken,
 * findet ihn unter „Freigaben" in der Seitenleiste wieder - aber nur, wenn dort etwas steht, das
 * er wiedererkennt. Ohne eigenen Namen heisst sie „Freigabe 7". */
function FreigabeSenden({
  clips,
  erlaubt,
  tarifErlaubt,
  tarifName,
  ausgewaehlt,
  onFreigabe,
  onFertig,
}: {
  /* Die Clips, um die es geht, mit ihrer Beschriftung für die Liste im Fenster. */
  clips: { id: string; label: string }[];
  /* Wie viele Clips angekreuzt sind. Null heisst: es gilt die ganze sichtbare Liste. */
  ausgewaehlt: number;
  erlaubt: boolean;
  tarifErlaubt: boolean;
  tarifName: string;
  /* Je angefragtem Clip: die Antwort der Route, damit die Karte sofort stimmt. */
  onFreigabe: (approvals: GuestApproval[]) => void;
  /* Wenn das Fenster geschlossen wird und etwas hinausging. */
  onFertig: () => void;
}) {
  const [offen, setOffen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [text, setText] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [kopiert, setKopiert] = useState(false);
  const nameId = useId();
  const emailId = useId();
  const textId = useId();

  if (!erlaubt) return null;

  const oeffnen = () => {
    setName("");
    setEmail("");
    setText("");
    setLink(null);
    setFehler(null);
    setKopiert(false);
    setOffen(true);
  };

  const anlegen = async () => {
    setLaeuft(true);
    setFehler(null);
    try {
      const res = await fetch("/api/freigaben", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          clip_ids: clips.map((c) => c.id),
          guest_email: email.trim() || null,
          message: text.trim(),
        }),
      });
      const data = (await res.json()) as { link?: string; error?: string; approvals?: GuestApproval[] };
      if (!res.ok || !data.link) throw new Error(data.error ?? "Die Freigabe konnte nicht angelegt werden");
      setLink(data.link);
      if (data.approvals) onFreigabe(data.approvals);
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Die Freigabe konnte nicht angelegt werden");
    } finally {
      setLaeuft(false);
    }
  };

  const kopieren = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setKopiert(true);
      window.setTimeout(() => setKopiert(false), 2000);
    } catch {
      /* Manche Browser verweigern die Zwischenablage ohne Nutzergeste im selben Takt. Dann bleibt
       * der Link im Feld stehen und lässt sich von Hand markieren - deshalb ein Eingabefeld und
       * kein reiner Text. */
      setKopiert(false);
    }
  };

  const schliessen = () => {
    setOffen(false);
    if (link) onFertig();
  };

  return (
    <>
      <Button size="sm" variant="ghost" onClick={oeffnen} title="Die Person fragen, auf deren Konto gepostet wird">
        <IconFreigabe />
        {/* Die Zahl steht am Knopf und nicht mehr in einer eigenen Leiste: sie ist die einzige
            Auskunft, die man beim Ankreuzen braucht. */}
        Zur Freigabe senden{ausgewaehlt > 0 ? ` (${ausgewaehlt})` : ""}
      </Button>

      <Modal
        open={offen}
        onClose={() => !laeuft && schliessen()}
        title="Zur Freigabe senden"
        description="Die Person bekommt einen Link, sieht die Clips und sagt zu jedem Ja, Nein oder „da stimmt etwas nicht“. Ohne Konto bei chopstr."
      >
        {!tarifErlaubt ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-text-2">Im Tarif {tarifName} ist die Freigabe durch Externe nicht enthalten.</p>
            <div className="flex justify-end">
              <Button variant="ghost" onClick={schliessen}>
                Schliessen
              </Button>
            </div>
          </div>
        ) : clips.length === 0 ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-text-2">
              Gerade gibt es nichts zu schicken: entweder wurde schon alles verschickt, oder es liegt
              noch keine fertige Datei vor. Kreuz einzelne Clips an, wenn du bestimmte meinst.
            </p>
            <div className="flex justify-end">
              <Button variant="ghost" onClick={schliessen}>
                Schliessen
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-text-2">
              {clips.length === 1 ? "Ein Clip geht hinaus:" : `${clips.length} Clips gehen hinaus:`}{" "}
              <span className="text-text">{clips.map((c) => c.label).join(", ")}</span>
            </p>

            <label className="flex flex-col gap-1.5" htmlFor={nameId}>
              <span className="text-sm text-text">Name dieser Freigabe</span>
              <span className="text-xs text-text-3">
                Damit du sie unter „Freigaben“ wiederfindest. Leer lassen geht auch.
              </span>
              <input
                id={nameId}
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={link != null}
                placeholder="Jobster, Woche 12"
                className="transition-soft rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none disabled:opacity-60"
              />
            </label>

            <label className="flex flex-col gap-1.5" htmlFor={emailId}>
              <span className="text-sm text-text">E-Mail (freiwillig)</span>
              <span className="text-xs text-text-3">Mit Adresse geht zusätzlich eine Mail hinaus.</span>
              <input
                id={emailId}
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={link != null}
                placeholder="name@firma.at"
                className="transition-soft rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none disabled:opacity-60"
              />
            </label>

            <label className="flex flex-col gap-1.5" htmlFor={textId}>
              <span className="text-sm text-text">Kommentar (freiwillig)</span>
              <textarea
                id={textId}
                rows={2}
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={link != null}
                placeholder="Schau bitte drüber, ob das so raus darf."
                className="transition-soft rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none disabled:opacity-60"
              />
            </label>

            {/* Der Link steht im selben Fenster, direkt unter den Feldern. Wer ihn hier übersieht,
                findet ihn unter „Freigaben" in der Seitenleiste wieder. */}
            <div className="flex flex-col gap-1.5 rounded-inner border border-line p-3">
              <span className="text-sm text-text">Freigabe-Link</span>
              {link ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      readOnly
                      value={link}
                      onFocus={(e) => e.currentTarget.select()}
                      aria-label="Freigabe-Link"
                      className="min-w-0 flex-1 rounded-inner border border-line bg-black/40 px-3 py-2 text-sm text-text"
                    />
                    <Button size="sm" variant="ghost" onClick={() => void kopieren()}>
                      {kopiert ? "Kopiert" : "Kopieren"}
                    </Button>
                  </div>
                  <span className="text-xs text-text-3">
                    Auch später zu finden unter „Freigaben“ in der Seitenleiste.
                  </span>
                </>
              ) : (
                <>
                  <span className="text-xs text-text-3">
                    Entsteht, sobald du unten auf „Link erzeugen“ drückst. Vorher gibt es nichts zu kopieren.
                  </span>
                  <Button size="sm" onClick={() => void anlegen()} disabled={laeuft} className="self-start">
                    {laeuft ? "Wird angelegt" : "Link erzeugen"}
                  </Button>
                </>
              )}
            </div>

            {fehler && <p className="text-sm text-attention">{fehler}</p>}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant={link ? "primary" : "ghost"} onClick={schliessen} disabled={laeuft}>
                Fertig
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

/* Die Zustände in Farbe. Grau, solange niemand geantwortet hat: eine bunte Karte für „es fehlt
 * noch eine Antwort" wäre Lärm. Farbe erst, wenn jemand etwas gesagt hat. */
const FREIGABE_TON: Record<FreigabeStand, "gut" | "achtung" | "fehler" | "ruhig"> = {
  nicht_gesendet: "ruhig",
  ausstehend: "ruhig",
  abgelehnt: "fehler",
  fehlerhaft: "achtung",
  freigegeben: "gut",
};

/* Eine Person mit einem Haken: jemanden um eine Zusage bitten. */
const IconFreigabe = () => (
  <Svg size={16}>
    <path d="M15 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1" />
    <circle cx="8.5" cy="7" r="3.5" />
    <path d="m16 11.5 2 2 4-4" />
  </Svg>
);

/* Die zweite Ebene: alles, was es auch noch gibt, hinter einer benannten Klappe.
 *
 * Bewusst kurz. „Groß ansehen" stand hier einmal - überflüssig, ein Klick auf die Vorschau tut
 * dasselbe. „Vorschlag verwerfen" auch; aussortiert wird über die Auswahl mehrerer Clips, und
 * dort gehört es hin. */
function Weitere({
  clip,
  stand,
  bearbeiten,
  mp4,
  darfLaden,
  canDelete,
  laeuft,
  onReview,
  onLoeschen,
  onFassung,
  onOffen,
}: {
  clip: Clip;
  stand: Pruefstand;
  bearbeiten: string;
  mp4: string | null;
  darfLaden: { erlaubt: boolean; grund: string | null };
  canDelete: boolean;
  laeuft: boolean;
  onReview: (r: Clip["review"]) => void;
  onLoeschen: () => void;
  onFassung: () => void;
  onOffen: (offen: boolean) => void;
}) {
  const [offen, setOffen] = useState(false);
  const umschalten = (o: boolean) => {
    setOffen(o);
    onOffen(o);
  };
  return (
    <div className="relative">
      {/* Ein Stift statt des Wortes „Mehr": die Karte hat schon einen Knopf mit Text daneben, und
          zwei gleich aussehende Knoepfe nebeneinander sind eine Auswahlaufgabe. Der Name bleibt
          fuer Vorleseprogramme erhalten. */}
      <button
        type="button"
        onClick={() => umschalten(!offen)}
        aria-expanded={offen}
        aria-label="Mehr zu diesem Clip"
        title="Mehr"
        className="transition-soft inline-flex h-9 w-9 items-center justify-center rounded-pill border border-line text-text-2 hover:border-line-strong hover:text-text"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M11.2 1.9a1.6 1.6 0 0 1 2.3 2.3l-7.4 7.4-3 .7.7-3 7.4-7.4Z"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
          <path d="M10 3.1 12.3 5.4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>
      {offen && (
        <>
          {/* Klick daneben schliesst. Ohne das bleibt die Klappe offen, wenn man woanders hinsieht. */}
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => umschalten(false)}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div className="absolute right-0 z-40 mt-1 flex w-[260px] flex-col gap-1 rounded-inner border border-line-strong bg-[#0b0b14] p-1.5 shadow-xl">
            <MenuLink href={bearbeiten} onClick={() => umschalten(false)}>
              Bearbeiten
            </MenuLink>
            {mp4 && darfLaden.erlaubt && (
              <MenuLink href={mp4} download onClick={() => umschalten(false)}>
                Herunterladen
              </MenuLink>
            )}
            {clip.candidate_id && (
              <MenuKnopf
                onClick={() => { umschalten(false); onFassung(); }}
                hinweis="Denselben Moment in einem anderen Format, etwa quadratisch."
              >
                Weitere Fassung anlegen
              </MenuKnopf>
            )}
            {stand.redaktion === "freigegeben" && (
              <MenuKnopf disabled={laeuft} onClick={() => { umschalten(false); onReview("offen"); }}>
                Freigabe zurücknehmen
              </MenuKnopf>
            )}
            {stand.redaktion === "verworfen" && (
              <MenuKnopf disabled={laeuft} onClick={() => { umschalten(false); onReview("offen"); }}>
                Zurückholen
              </MenuKnopf>
            )}
            {canDelete && (
              <MenuKnopf ton="danger" disabled={clip.status === "rendering"} onClick={() => { umschalten(false); onLoeschen(); }}>
                Löschen
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


/* Die Formatauswahl für eine weitere Fassung.
 *
 * Eine eigene Komponente, damit die Liste nicht im Rumpf des Dialogs über die Clips läuft: die
 * Auswahl ist eine Anzeige, das Anlegen eine Handlung, und die beiden gehören getrennt. */
function FassungWahl({
  vorhanden,
  busy,
  onWaehlen,
}: {
  vorhanden: Aspect[];
  busy: boolean;
  onWaehlen: (a: Aspect) => void;
}) {
  return (
    <>
      {FASSUNG_FORMATE.map((a) => {
        const schon = !fassungMoeglich(vorhanden, a);
        const groesse = ASPECT_SIZE[a];
        return (
          <button
            key={a}
            type="button"
            disabled={schon || busy}
            onClick={() => onWaehlen(a)}
            className="transition-soft flex items-center justify-between gap-3 rounded-inner border border-line px-4 py-3 text-left hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-45"
          >
            <span className="min-w-0">
              <span className="block text-sm text-text">{ASPECT_LABELS[a]}</span>
              <span className="block text-xs text-text-3">
                {groesse.width} mal {groesse.height} · gut für {FORMAT_HILFT_BEI[a]}
              </span>
            </span>
            <span className="shrink-0 text-xs text-text-3">{schon ? "gibt es schon" : "anlegen"}</span>
          </button>
        );
      })}
    </>
  );
}
