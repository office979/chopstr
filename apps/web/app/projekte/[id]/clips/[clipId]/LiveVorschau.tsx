"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/components/ui/cn";
import { ausschnittBerechnen, blickraumAnker } from "@/lib/clips/ausschnitt";
import type { CaptionStyle } from "@/lib/clips/caption-style";
import { timecode } from "@/lib/clips/timecode";
import type { Aspect, RenderShot, TranscriptWord, Zeitmarke } from "@/lib/repo/types";
import { CaptionVorschau } from "./CaptionStudio";

const ASPEKT: Record<Aspect, string> = {
  "9:16": "9 / 16",
  "4:5": "4 / 5",
  "1:1": "1 / 1",
  "16:9": "16 / 9",
};

interface Props {
  /* Das Quellvideo. Darin sind KEINE Untertitel eingebrannt, deshalb kann die Vorschau hier alles
   * zeigen, was gerade eingestellt ist. */
  src: string | null;
  posterSrc: string | null;
  aspect: Aspect;
  srcW: number | null;
  srcH: number | null;
  outW: number;
  outH: number;
  clipStart: number;
  clipEnd: number | null;
  zeit: number;
  onTime: (quellzeit: number) => void;
  seekTo: { at: number; nonce: number } | null;
  /* Zaehler von aussen: jede Erhoehung startet oder stoppt das Video. So bedient die Leertaste
   * denselben Player wie der Knopf im Bild. */
  spielen?: number;
  onLaeuft?: (laeuft: boolean) => void;
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  stil: CaptionStyle;
  woerter: TranscriptWord[];
  /* Die Höhe der Untertitel lässt sich direkt im Bild ziehen. Ohne diese Rückmeldung bleibt es
   * bei einem Schieber, und „wo steht der Text" ist eine Frage, die man sehen und nicht rechnen
   * will. */
  onCaptionHoehe?: (bottomMarginPx: number) => void;
}

/* Die Vorschau aus dem Quellvideo, mit allem was gerade eingestellt ist.
 *
 * Der fertige Clip ist das Ergebnis des letzten Bauens. Wer etwas aendert und ihn ansieht, sieht
 * die alte Entscheidung - und bei den Untertiteln sogar zwei Texte uebereinander, weil sie dort
 * eingebrannt sind. Deshalb wird hier stattdessen das Quellvideo gezeigt und der Ausschnitt per
 * CSS so gelegt, wie der Renderer ihn schneiden wuerde. Die Untertitel kommen als Ueberlagerung
 * darueber.
 *
 * Das Ergebnis: jede Aenderung ist sofort zu sehen, ohne zu rendern.
 *
 * Schnitt, Effekte und Musik zeigt sie nicht mehr: die Timeline, an der sie hingen, ist entfernt
 * (docs/decisions/050-timeline-entfernen.md). Was der Renderer daraus macht, zeigt „Zuletzt
 * geclippt“. */
export function LiveVorschau({
  src,
  posterSrc,
  aspect,
  srcW,
  srcH,
  outW,
  outH,
  clipStart,
  clipEnd,
  zeit,
  onTime,
  seekTo,
  spielen = 0,
  onLaeuft,
  shots,
  zeitmarken,
  stil,
  woerter,
  onCaptionHoehe,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    const anfang = () => {
      if (video.currentTime < clipStart - 0.3) video.currentTime = clipStart;
    };
    if (video.readyState >= 1) anfang();
    video.addEventListener("loadedmetadata", anfang);
    return () => video.removeEventListener("loadedmetadata", anfang);
  }, [clipStart]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !seekTo) return;
    video.currentTime = Math.max(0, seekTo.at);
  }, [seekTo]);

  /* Der erste Lauf ist kein Klick: ohne diese Sperre startete das Video beim Laden von selbst. */
  const ersterZaehler = useRef(spielen);
  useEffect(() => {
    const video = videoRef.current;
    if (!video || spielen === ersterZaehler.current) return;
    if (video.paused) void video.play();
    else video.pause();
  }, [spielen]);

  const melden = (l: boolean) => {
    setLaeuft(l);
    onLaeuft?.(l);
  };

  /* Was gilt an dieser Stelle? Eine Marke von Hand schlaegt den Plan; ohne Marke gilt, was die
   * Automatik beim letzten Lauf entschieden hat. */
  const jetzt = useMemo(() => {
    const shot = shots.find((s) => zeit >= s.start && zeit < s.end) ?? null;
    /* Marken liegen in QUELLZEIT, genau wie hier gemessen wird und wie der Renderer sie liest. */
    const marke = [...zeitmarken]
      .filter((m) => m.ab_s <= zeit + 1e-6)
      .sort((a, b) => a.ab_s - b.ab_s)
      .pop();
    const auswahl = shot?.auswahl ?? [];
    const cx = marke?.x ?? shot?.quelle_x ?? null;
    const andere = cx == null ? [] : auswahl.filter((x) => Math.abs(x - cx) > 1e-6);
    return {
      cx,
      cy: shot && srcH ? srcH * 0.45 : null,
      zoom: marke?.zoom ?? shot?.zoom ?? 1,
      anker: cx == null || !srcW ? 0.5 : blickraumAnker(cx, srcW, andere),
      geteilt: (marke?.layout ?? (shot?.layout === "geteilt" ? "geteilt" : "einzel")) === "geteilt",
      auswahl,
    };
  }, [zeit, shots, zeitmarken, srcW, srcH]);

  const ausschnitt = useMemo(() => {
    if (!srcW || !srcH) return null;
    return ausschnittBerechnen({ srcW, srcH, outW, outH, cx: jetzt.cx, cy: jetzt.cy, anker: jetzt.anker, zoom: jetzt.zoom });
  }, [srcW, srcH, outW, outH, jetzt]);

  if (!src) {
    return (
      <GlassCard padding="md">
        <p className="text-sm text-text-2">Für die Vorschau fehlt das Video.</p>
      </GlassCard>
    );
  }

  /* Den Ausschnitt mit CSS legen: das Video wird so vergroessert, dass der gewuenschte Ausschnitt
   * den Rahmen genau fuellt, und so verschoben, dass er an der richtigen Stelle sitzt. */
  const lage: React.CSSProperties = ausschnitt
    ? {
        position: "absolute",
        width: `${((srcW ?? 1) / ausschnitt.w) * 100}%`,
        height: `${((srcH ?? 1) / ausschnitt.h) * 100}%`,
        left: `${(-ausschnitt.x / ausschnitt.w) * 100}%`,
        top: `${(-ausschnitt.y / ausschnitt.h) * 100}%`,
        maxWidth: "none",
      }
    : { position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" };


  return (
    <GlassCard padding="none" className="overflow-hidden">
      {/* Volle Breite der Karte. Vorher stand hier max-w-[340px] in einer Spalte, die breiter ist:
          links und rechts blieb ein Streifen Kartenhintergrund neben dem Video stehen. Jetzt ist
          die Karte so breit wie das Bild, und ihre runden Ecken schneiden es mit. */}
      <div className="relative w-full overflow-hidden bg-black" style={{ aspectRatio: ASPEKT[aspect] }}>
        <div className="absolute inset-0">
        {/* Keine eigenen Bedienelemente des Browsers: das Video ist vergroessert, damit der
          * Ausschnitt den Rahmen fuellt, und seine Leiste waere es dann auch - halb ausserhalb des
          * Bildes. Gespult wird mit dem Regler unter dem Bild, hier braucht es nur Start und Pause. */}
        <video
          ref={videoRef}
          src={src}
          poster={posterSrc ?? undefined}
          playsInline
          preload="metadata"
          style={lage}
          onPlay={() => melden(true)}
          onPause={() => melden(false)}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            if (clipEnd != null && v.currentTime > clipEnd) {
              v.pause();
              v.currentTime = clipEnd;
            }
            onTime(v.currentTime);
          }}
        >
          Dein Browser kann dieses Video nicht abspielen.
        </video>
        </div>
        {woerter.length > 0 && (
          <CaptionVorschau stil={stil} woerter={woerter} zeit={zeit} onHoehe={onCaptionHoehe} />
        )}
        {/* Das geteilte Bild zeigt die Vorschau nicht: dafuer braeuchte es zwei Videoelemente aus
          * derselben Quelle, synchron gehalten. Ein Hinweis ist ehrlicher als ein Einzelbild, das
          * so tut, als sei nichts eingestellt. */}
        {jetzt.geteilt && (
          <span className="pointer-events-none absolute left-2 top-2 rounded-pill bg-black/70 px-2.5 py-1 text-xs text-white">
            Geteiltes Bild · erst im gebauten Clip zu sehen
          </span>
        )}
        {/* Abspielen und Anhalten: die ganze Fläche ist der Knopf.
         *
         * Hier verschwand vorher nur das ZEICHEN (text-white/0), die schwarze Scheibe dahinter
         * blieb stehen. Damit lag während des Abspielens dauerhaft ein dunkler Kreis mitten im
         * Bild - genau dort, wo bei einem hochkanten Clip das Gesicht ist. Jetzt geht die ganze
         * Scheibe mit.
         *
         * Sichtbar bleibt sie im Stillstand: ein stehendes Video ohne Abspielzeichen sieht aus
         * wie ein Bild, und niemand klickt darauf. Läuft es, genügt der Mauszeiger. */}
        <button
          type="button"
          aria-label={laeuft ? "Anhalten" : "Abspielen"}
          onClick={() => {
            const v = videoRef.current;
            if (!v) return;
            if (v.paused) void v.play();
            else v.pause();
          }}
          className="group absolute inset-0 z-10 flex items-center justify-center focus:outline-none"
        >
          <span
            className={cn(
              "transition-soft flex h-14 w-14 items-center justify-center rounded-full bg-black/55 text-white/90 backdrop-blur-sm",
              laeuft
                ? "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
                : "opacity-100",
            )}
          >
            {laeuft ? (
              <svg width="18" height="20" viewBox="0 0 18 20" fill="currentColor" aria-hidden="true">
                <rect x="1" y="1" width="5" height="18" rx="1.5" />
                <rect x="12" y="1" width="5" height="18" rx="1.5" />
              </svg>
            ) : (
              <svg width="18" height="20" viewBox="0 0 18 20" fill="currentColor" aria-hidden="true">
                <path d="M2 1.8v16.4a1 1 0 0 0 1.53.85l13-8.2a1 1 0 0 0 0-1.7l-13-8.2A1 1 0 0 0 2 1.8Z" />
              </svg>
            )}
          </span>
        </button>
      </div>
      {/* Die Stelle im Clip, als Regler. Kein Trimmen und kein Verschieben von Grenzen: der Regler
          reicht genau von Anfang bis Ende des Clips und bewegt nur den Abspielkopf. Gebraucht wird
          er für den Bildausschnitt, der ab der Stelle des Abspielkopfs gilt. */}
      {clipEnd != null && clipEnd > clipStart && (
        <label className="flex items-center gap-3 px-3 py-2.5">
          <span className="sr-only">Stelle im Clip</span>
          <input
            type="range"
            min={0}
            max={Math.round((clipEnd - clipStart) * 10) / 10}
            step={0.1}
            value={Math.min(Math.max(0, zeit - clipStart), clipEnd - clipStart)}
            onChange={(e) => {
              const v = videoRef.current;
              const ziel = clipStart + Number(e.target.value);
              if (v) v.currentTime = ziel;
              onTime(ziel);
            }}
            className="w-full accent-white"
          />
          <span className="shrink-0 font-mono text-xs tabular-nums text-text-2">
            {timecode(Math.max(0, zeit - clipStart))} von {timecode(clipEnd - clipStart)}
          </span>
        </label>
      )}
    </GlassCard>
  );
}
