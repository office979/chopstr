"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ausschnittBerechnen, blickraumAnker } from "@/lib/clips/ausschnitt";
import type { CaptionStyle } from "@/lib/clips/caption-style";
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
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  stil: CaptionStyle;
  woerter: TranscriptWord[];
}

/* Die Vorschau aus dem Quellvideo, mit allem was gerade eingestellt ist.
 *
 * Der fertige Clip ist das Ergebnis des letzten Bauens. Wer etwas aendert und ihn ansieht, sieht
 * die alte Entscheidung - und bei den Untertiteln sogar zwei Texte uebereinander, weil sie dort
 * eingebrannt sind. Deshalb wird hier stattdessen das Quellvideo gezeigt und der Ausschnitt per
 * CSS so gelegt, wie der Renderer ihn schneiden wuerde. Die Untertitel kommen als Ueberlagerung
 * darueber.
 *
 * Das Ergebnis: jede Aenderung ist sofort zu sehen, ohne zu rendern. */
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
  shots,
  zeitmarken,
  stil,
  woerter,
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

  /* Was gilt an dieser Stelle? Eine Marke von Hand schlaegt den Plan; ohne Marke gilt, was die
   * Automatik beim letzten Lauf entschieden hat. */
  const jetzt = useMemo(() => {
    const imClip = zeit - clipStart;
    const shot = shots.find((s) => zeit >= s.start && zeit < s.end) ?? null;
    const marke = [...zeitmarken]
      .filter((m) => m.ab_s <= imClip + 1e-6)
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
  }, [zeit, clipStart, shots, zeitmarken, srcW, srcH]);

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
      <div className="relative mx-auto w-full max-w-[340px] overflow-hidden bg-black" style={{ aspectRatio: ASPEKT[aspect] }}>
        {/* Keine eigenen Bedienelemente des Browsers: das Video ist vergroessert, damit der
          * Ausschnitt den Rahmen fuellt, und seine Leiste waere es dann auch - halb ausserhalb des
          * Bildes. Gespult wird in der Zeitleiste darunter, hier braucht es nur Start und Pause. */}
        <video
          ref={videoRef}
          src={src}
          poster={posterSrc ?? undefined}
          playsInline
          preload="metadata"
          style={lage}
          onPlay={() => setLaeuft(true)}
          onPause={() => setLaeuft(false)}
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
        {woerter.length > 0 && <CaptionVorschau stil={stil} woerter={woerter} zeit={zeit} />}
        {/* Das geteilte Bild zeigt die Vorschau nicht: dafuer braeuchte es zwei Videoelemente aus
          * derselben Quelle, synchron gehalten. Ein Hinweis ist ehrlicher als ein Einzelbild, das
          * so tut, als sei nichts eingestellt. */}
        {jetzt.geteilt && (
          <span className="pointer-events-none absolute left-2 top-2 rounded-pill bg-black/70 px-2.5 py-1 text-xs text-white">
            Geteiltes Bild · erst im gebauten Clip zu sehen
          </span>
        )}
        <button
          type="button"
          aria-label={laeuft ? "Anhalten" : "Abspielen"}
          onClick={() => {
            const v = videoRef.current;
            if (!v) return;
            if (v.paused) void v.play();
            else v.pause();
          }}
          className="transition-soft absolute inset-0 flex items-center justify-center text-white/0 hover:text-white/90 focus:text-white/90 focus:outline-none"
        >
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-black/55 backdrop-blur-sm">
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
    </GlassCard>
  );
}
