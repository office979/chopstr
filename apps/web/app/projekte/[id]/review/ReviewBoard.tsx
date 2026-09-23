"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { playDoneSound } from "@/lib/sound";
import type { Candidate, Clip, Platform, ReviseCandidateInput } from "@/lib/repo/types";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import type { Sentence } from "@/lib/transcript/sentences";
import { warningsOf } from "@/lib/candidates/labels";
import { usePlayer } from "../transkript/usePlayer";
import { VideoStage } from "../transkript/VideoStage";
import { CandidateCard } from "./CandidateCard";
import { CandidateDetail } from "./CandidateDetail";
import { ClipText } from "./ClipText";

/* So lange bleibt die Erfolgsmeldung stehen, bevor es zu den Clips geht. Gleiche Zeit wie am Ende
 * der Analyse (PipelineLive), damit sich beide Übergänge gleich anfühlen. */
const HANDOFF_MS = 1400;

interface Props {
  sourceId: string;
  title: string;
  durationS: number;
  videoSrc: string | null;
  initialCandidates: Candidate[];
  initialClips: Clip[];
  defaultPlatform: Platform;
  /* Maße der Quelle für den Hochformat-Schalter */
  sourceWidth: number | null;
  sourceHeight: number | null;
  sentences: Sentence[];
  speakerNames: Record<string, string>;
}

type Filter = "all" | "passed" | "warning" | "accepted" | "rejected";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Alle" },
  { key: "passed", label: "Vollständig geprüft" },
  { key: "warning", label: "Mit Hinweis" },
  { key: "accepted", label: "Angenommen" },
  { key: "rejected", label: "Abgelehnt" },
];

export const PREVIEW_SECONDS = 8;

function matches(c: Candidate, filter: Filter): boolean {
  switch (filter) {
    case "passed":
      return c.gate_passed;
    case "warning":
      return warningsOf(c).length > 0;
    case "accepted":
      return c.human_verdict === "accepted";
    case "rejected":
      return c.human_verdict === "rejected";
    default:
      return true;
  }
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

interface ApiError {
  error?: string;
}

/* Kandidaten-Review: Player links, Liste rechts, Detail mit Aktionen. Urteile werden optimistisch gesetzt. */
export function ReviewBoard({ sourceId, title, durationS, videoSrc, initialCandidates, initialClips, defaultPlatform, sourceWidth, sourceHeight, sentences, speakerNames }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const player = usePlayer(videoRef, durationS);
  const { currentTime, playing, seek, play, pause } = player;

  const [candidates, setCandidates] = useState<Candidate[]>(initialCandidates);
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(initialCandidates[0]?.id ?? null);
  const [glitchId, setGlitchId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; href?: string; hrefLabel?: string } | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const router = useRouter();
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [clips, setClips] = useState<Clip[]>(initialClips);
  /* Ende der 8-Sekunden-Vorschau (Sekunden im Original); null = keine Vorschau aktiv */
  const [previewEnd, setPreviewEnd] = useState<number | null>(null);

  const cardRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const seededSeek = useRef(false);
  const maxSentence = sentences.length ? sentences[sentences.length - 1].idx : 0;

  const visible = useMemo(() => candidates.filter((c) => matches(c, filter)), [candidates, filter]);
  const counts = useMemo(
    () =>
      FILTERS.reduce(
        (acc, f) => {
          acc[f.key] = candidates.filter((c) => matches(c, f.key)).length;
          return acc;
        },
        {} as Record<Filter, number>,
      ),
    [candidates],
  );
  /* Auswahl bleibt im Filter sichtbar: fällt die Auswahl aus dem Filter, gilt der erste sichtbare Kandidat */
  const effectiveId = visible.some((c) => c.id === selectedId) ? selectedId : (visible[0]?.id ?? null);
  const selected = candidates.find((c) => c.id === effectiveId) ?? null;

  /* Beim ersten Rendern zum Start des ersten Kandidaten springen */
  useEffect(() => {
    if (seededSeek.current) return;
    seededSeek.current = true;
    const first = initialCandidates[0];
    if (first) seek(first.start_s);
  }, [initialCandidates, seek]);

  /* 8-Sekunden-Vorschau: Stop bei start_s + 8. Der Player ist das externe System; das Vorschau-Ende
   * wird nach dem Stopp asynchron geleert, damit die Wiedergabe danach wieder frei läuft. */
  useEffect(() => {
    if (!playing || previewEnd == null || currentTime < previewEnd) return;
    pause();
    window.setTimeout(() => setPreviewEnd((end) => (end === previewEnd ? null : end)), 0);
  }, [currentTime, playing, previewEnd, pause]);

  const select = useCallback(
    (id: string) => {
      const c = candidates.find((x) => x.id === id);
      if (!c) return;
      setSelectedId(id);
      setRejectOpen(false);
      setAcceptOpen(false);
      setPreviewEnd(null);
      pause();
      seek(c.start_s);
      cardRefs.current.get(id)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    [candidates, pause, seek],
  );

  const startPreview = useCallback(() => {
    if (!selected) return;
    seek(selected.start_s);
    setPreviewEnd(selected.start_s + PREVIEW_SECONDS);
    play();
  }, [selected, seek, play]);

  const togglePreview = useCallback(() => {
    if (playing) {
      setPreviewEnd(null);
      pause();
    } else {
      startPreview();
    }
  }, [playing, pause, startPreview]);

  const step = useCallback(
    (delta: 1 | -1) => {
      if (visible.length === 0) return;
      const idx = visible.findIndex((c) => c.id === effectiveId);
      const next = visible[Math.min(visible.length - 1, Math.max(0, (idx < 0 ? 0 : idx) + delta))];
      if (next && next.id !== effectiveId) select(next.id);
    },
    [visible, effectiveId, select],
  );

  const replace = (id: string, next: Candidate) =>
    setCandidates((prev) => prev.map((c) => (c.id === id ? next : c)));

  /* setVerdict haengt nur an sourceId, sieht die Liste also veraltet. Ueber diese Referenz kommt es
   * an den aktuellen Stand, ohne bei jeder Aenderung neu gebaut zu werden. */
  const candidatesRef = useRef(candidates);
  useEffect(() => {
    candidatesRef.current = candidates;
  }, [candidates]);

  const setVerdict = useCallback(
    async (c: Candidate, verdict: "accepted" | "rejected", reason?: string, platforms?: Platform[], keepSourceAspect = false) => {
      const before = c;
      const optimistic: Candidate = {
        ...c,
        human_verdict: verdict,
        verdict_reason: reason ?? null,
        verdict_at: new Date().toISOString(),
      };
      replace(c.id, optimistic);
      setMessage(null);
      if (verdict === "accepted") {
        setAcceptOpen(false);
        setGlitchId(c.id);
        window.setTimeout(() => setGlitchId((g) => (g === c.id ? null : g)), 1000);
      } else {
        setRejectOpen(false);
      }
      try {
        const res = await fetch(`/api/projects/${sourceId}/candidates/${c.id}/verdict`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ verdict, reason, platforms, keep_source_aspect: keepSourceAspect }),
        });
        const data = (await res.json()) as ApiError & { candidate?: Candidate; clips?: Clip[]; signaled?: Platform[]; demo?: boolean };
        if (!res.ok || !data.candidate) throw new Error(data.error ?? "Urteil konnte nicht gespeichert werden");
        replace(c.id, data.candidate);
        const created = data.clips ?? [];
        if (created.length > 0) {
          setClips((prev) => [...prev.filter((k) => !created.some((n) => n.id === k.id)), ...created]);
        }
        const names = created.map((k) => PLATFORM_LABELS[k.platform]).join(", ");
        setMessage(
          verdict === "accepted"
            ? {
                tone: "ok",
                text:
                  created.length === 0
                    ? "Angenommen."
                    : (data.signaled?.length ?? 0) > 0
                      ? `Angenommen. ${created.length} Clips angelegt (${names}), Render angestoßen.`
                      : data.demo
                        ? `Angenommen. ${created.length} Clips angelegt (${names}), Demo-Render läuft.`
                        : `Angenommen. ${created.length} Clips angelegt (${names}). Render eingeplant, lokaler Worker holt ab.`,
                href: `/projekte/${sourceId}/clips`,
                hrefLabel: "Clips ansehen",
              }
            : { tone: "ok", text: "Abgelehnt. Der Grund fließt als Lernsignal ein." },
        );

        /* Der Weg darf hier nicht abreißen. Ist noch etwas offen, springt die Auswahl zum nächsten
         * unentschiedenen Moment — das ist der Takt, in dem jemand zwanzig Stück durchgeht. Ist
         * nichts mehr offen, ist der Schritt zu Ende: Klang und weiter zu den fertigen Clips,
         * genau wie nach der Analyse. Wer nach dem ersten Annehmen hinausgeworfen wird, kann
         * nicht im Stapel arbeiten; wer nie hinausgeführt wird, findet seine Clips nicht. */
        const offen = candidatesRef.current.filter((k) => k.id !== c.id && k.human_verdict == null);
        if (offen.length > 0) {
          select(offen[0].id);
        } else if (verdict === "accepted" && created.length > 0) {
          playDoneSound();
          window.setTimeout(() => router.push(`/projekte/${sourceId}/clips`), HANDOFF_MS);
        }
      } catch (err) {
        replace(c.id, before);
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Urteil konnte nicht gespeichert werden" });
      }
    },
    [sourceId, select, router],
  );

  const revise = useCallback(
    async (c: Candidate, input: ReviseCandidateInput) => {
      setBusyId(c.id);
      setMessage(null);
      try {
        const res = await fetch(`/api/projects/${sourceId}/candidates/${c.id}/revise`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        });
        const data = (await res.json()) as ApiError & { candidate?: Candidate };
        if (!res.ok || !data.candidate) throw new Error(data.error ?? "Anpassen fehlgeschlagen");
        const next = data.candidate;
        replace(c.id, next);
        setSelectedId(next.id);
        seek(next.start_s);
        const changedBounds = next.first_sent !== c.first_sent || next.last_sent !== c.last_sent;
        setMessage({
          tone: "ok",
          text: changedBounds
            ? `Neue Fassung gespeichert: Satz ${next.first_sent} bis ${next.last_sent}. Alles neu geprüft, die Bewertung stammt noch vom alten Ausschnitt.`
            : `Version ${next.version} angelegt: Titelkarte gespeichert.`,
        });
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Anpassen fehlgeschlagen" });
      } finally {
        setBusyId(null);
      }
    },
    [sourceId, seek],
  );

  /* Tastatur: J/K Kandidat, A annehmen, R ablehnen, Leertaste Vorschau */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      const key = e.key.toLowerCase();
      if (key === "j") {
        e.preventDefault();
        step(1);
      } else if (key === "k") {
        e.preventDefault();
        step(-1);
      } else if (key === "a") {
        /* Nimmt sofort an, mit der Standard-Plattform. Vorher klappte „A" nur ein Feld auf, und der
         * Knopf darin bekam keinen Fokus — der häufigste Handgriff war damit der einzige, den man
         * nicht mit der Tastatur zu Ende bringen konnte. */
        if (selected && selected.human_verdict !== "accepted" && busyId == null) {
          e.preventDefault();
          setRejectOpen(false);
          setAcceptOpen(false);
          void setVerdict(selected, "accepted", undefined, [defaultPlatform], false);
        }
      } else if (key === "r") {
        if (selected && selected.human_verdict !== "rejected") {
          e.preventDefault();
          setRejectOpen(true);
        }
      } else if (e.code === "Space" || e.key === " ") {
        /* Buttons außer Kandidaten-Karten behalten ihr natives Verhalten */
        if (target?.tagName === "BUTTON" && target.dataset.card !== "true") return;
        e.preventDefault();
        togglePreview();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      const target = e.target instanceof HTMLElement ? e.target : null;
      if ((e.code === "Space" || e.key === " ") && target?.dataset.card === "true") e.preventDefault();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
    };
  }, [step, selected, busyId, setVerdict, togglePreview, defaultPlatform]);

  const previewActive = playing && previewEnd != null && currentTime < previewEnd;
  const previewLeft = previewActive ? Math.max(0, previewEnd - currentTime) : PREVIEW_SECONDS;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-[auto_1fr] lg:items-start">
      {/* Player und Clip-Text */}
      <div className="flex flex-col gap-5 lg:col-start-1 lg:row-start-1">
        <VideoStage
          videoRef={videoRef}
          videoSrc={videoSrc}
          title={title}
          player={player}
          activeSpeaker={null}
          hint="Tastatur: J und K blättern · A nimmt den Clip · R lehnt ihn ab · Leertaste spielt 8 Sekunden"
        />
        {selected && (
          <ClipText
            candidate={selected}
            sentences={sentences}
            speakerNames={speakerNames}
            currentTime={currentTime}
            onSeek={(t) => {
              setPreviewEnd(null);
              seek(t);
            }}
            preview={
              <Button size="sm" onClick={togglePreview} aria-pressed={previewActive}>
                {previewActive ? `Stopp (${Math.ceil(previewLeft)} s)` : `${PREVIEW_SECONDS} s Vorschau`}
              </Button>
            }
          />
        )}
      </div>

      {/* Liste */}
      <div className="flex flex-col gap-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Clips filtern">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                aria-pressed={active}
                className={cn(
                  "transition-soft inline-flex h-9 items-center gap-2 rounded-pill border px-3.5 text-sm",
                  active ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong hover:text-text",
                )}
              >
                {f.label}
                <span className="font-mono text-xs text-text-3">{counts[f.key]}</span>
              </button>
            );
          })}
        </div>

        {message && (
          <p
            role="status"
            aria-live="polite"
            className={cn("rounded-inner border px-4 py-3 text-sm", message.tone === "ok" ? "border-line text-text" : "border-attention/50 bg-attention/10 text-text")}
          >
            {message.text}
            {message.href && (
              <>
                {" "}
                <Link href={message.href} className="font-medium text-text underline-offset-4 hover:underline">
                  {message.hrefLabel ?? "Öffnen"}
                </Link>
              </>
            )}
          </p>
        )}

        {visible.length === 0 ? (
          <GlassCard padding="lg" className="text-center">
            <p className="font-medium">Hier ist gerade nichts</p>
            <p className="mt-1 text-sm text-text-2">Klick auf „Alle“, um wieder alle Clips zu sehen.</p>
          </GlassCard>
        ) : (
          <ul className="flex flex-col gap-3 lg:max-h-[calc(100dvh-14rem)] lg:overflow-y-auto lg:pr-1 lg:pb-8" aria-label="Clips">
            {visible.map((c, i) => (
              <li key={c.id}>
                <CandidateCard
                  candidate={c}
                  index={i + 1}
                  selected={c.id === effectiveId}
                  glitch={c.id === glitchId}
                  onSelect={() => select(c.id)}
                  cardRef={(el) => {
                    if (el) cardRefs.current.set(c.id, el);
                    else cardRefs.current.delete(c.id);
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Detail des ausgewählten Kandidaten */}
      <div className="lg:col-start-1 lg:row-start-2">
        {selected && (
          <CandidateDetail
            key={selected.id}
            candidate={selected}
            sourceId={sourceId}
            maxSentence={maxSentence}
            busy={busyId === selected.id}
            rejectOpen={rejectOpen}
            onRejectOpen={(open) => {
              setRejectOpen(open);
              if (open) setAcceptOpen(false);
            }}
            acceptOpen={acceptOpen}
            onAcceptOpen={(open) => {
              setAcceptOpen(open);
              if (open) setRejectOpen(false);
            }}
            defaultPlatform={defaultPlatform}
            clips={clips.filter((k) => k.candidate_id === selected.id)}
            sourceWidth={sourceWidth}
            sourceHeight={sourceHeight}
            onAccept={(platforms, keepSourceAspect) => setVerdict(selected, "accepted", undefined, platforms, keepSourceAspect)}
            onReject={(reason) => setVerdict(selected, "rejected", reason)}
            onRevise={(input) => revise(selected, input)}
          />
        )}
      </div>
    </div>
  );
}
