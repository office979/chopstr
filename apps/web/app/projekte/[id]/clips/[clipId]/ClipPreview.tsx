"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Mark } from "@/components/brand/Mark";
import { Grain } from "@/components/ui/Grain";
import type { Aspect } from "@/lib/repo/types";

const ASPECT_RATIO_CSS: Record<Aspect, string> = {
  "9:16": "9 / 16",
  "4:5": "4 / 5",
  "1:1": "1 / 1",
  "16:9": "16 / 9",
};

interface Props {
  src: string | null;
  posterSrc: string | null;
  aspect: Aspect;
  /* Sekunden, die zur Videozeit dazukommen, um die Stelle im ganzen Video zu erhalten.
   * Beim fertigen Clip ist das sein Anfang, beim ganzen Video null. */
  timeOffset: number;
  /* Nur wenn das ganze Video läuft: hier fängt der Clip an, hier hört er auf */
  trim: { start: number; end: number | null } | null;
  /* Gerade gespielte Stelle, gemessen im ganzen Video */
  onTime: (secondsInSource: number) => void;
  /* Sprung an eine Stelle des ganzen Videos, von außen gesetzt */
  seekTo: { at: number; nonce: number } | null;
  /* Über das Bild gelegt, zum Beispiel die Untertitel-Vorschau. Nimmt keine Klicks an, damit die
   * Steuerung des Browsers erreichbar bleibt. */
  overlay?: ReactNode;
  /* Zaehler von aussen: jede Erhoehung startet oder stoppt das Video, damit der Knopf in der
   * Timeline denselben Player bedient. */
  spielen?: number;
  onLaeuft?: (laeuft: boolean) => void;
}

/* Vorschau des Clips. Die Steuerung ist die des Browsers: abspielen, anhalten, schieben.
 * Mehr steht hier nicht, der Schnitt kommt später. */
export function ClipPreview({
  src,
  posterSrc,
  aspect,
  timeOffset,
  trim,
  onTime,
  seekTo,
  overlay,
  spielen = 0,
  onLaeuft,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  /* Läuft das ganze Video, soll es dort beginnen, wo der Clip beginnt. */
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !trim) return undefined;
    const toStart = () => {
      if (video.currentTime < trim.start - 0.3) video.currentTime = trim.start;
    };
    if (video.readyState >= 1) toStart();
    video.addEventListener("loadedmetadata", toStart);
    return () => video.removeEventListener("loadedmetadata", toStart);
  }, [trim]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !seekTo) return;
    video.currentTime = Math.max(0, seekTo.at - timeOffset);
  }, [seekTo, timeOffset]);

  /* Der erste Lauf ist kein Klick: ohne diese Sperre startete das Video beim Laden von selbst. */
  const ersterZaehler = useRef(spielen);
  useEffect(() => {
    const video = videoRef.current;
    if (!video || spielen === ersterZaehler.current) return;
    if (video.paused) void video.play();
    else video.pause();
  }, [spielen]);

  if (!src) {
    return (
      <GlassCard padding="none" className="overflow-hidden">
        <div
          className="relative mx-auto flex w-full max-w-[320px] flex-col items-center justify-center gap-3 bg-raised"
          style={{ aspectRatio: ASPECT_RATIO_CSS[aspect] }}
        >
          <Grain opacity={0.07} />
          <Mark size={40} className="relative" />
          <p className="relative max-w-[240px] px-4 text-center text-sm text-text-2">
            Der Clip ist noch nicht gebaut. Sobald er fertig ist, läuft er hier.
          </p>
          {/* Der Untertitel-Stil gehört auch hierher: sonst könnte man ihn erst einstellen, wenn
            * der Clip schon gebaut ist, und müsste ihn danach noch einmal bauen lassen. */}
          {overlay}
        </div>
      </GlassCard>
    );
  }

  /* Genau so breit wie die Karte, wie die Live-Vorschau daneben: beide liegen an derselben Stelle
   * und werden mit einem Umschalter getauscht. Waeren sie verschieden breit, huepfte die halbe
   * Seite bei jedem Umschalten. Das Overlay liegt deshalb auf diesem Behaelter, nicht auf der
   * Karte - er hat jetzt dieselben Masse wie das Bild. */
  return (
    <GlassCard padding="none" className="overflow-hidden">
      <div className="relative w-full bg-black" style={{ aspectRatio: ASPECT_RATIO_CSS[aspect] }}>
        <video
          ref={videoRef}
          src={src}
          poster={posterSrc ?? undefined}
          controls
          playsInline
          preload="metadata"
          aria-label="Clip abspielen"
          onPlay={() => onLaeuft?.(true)}
          onPause={() => onLaeuft?.(false)}
          /* object-contain und nicht cover: das ist der FERTIGE Clip, an dem nichts mehr
             beschnitten werden darf. Hat er wider Erwarten ein anderes Seitenverhaeltnis, sieht
             man schwarze Balken - und das ist die ehrliche Anzeige. */
          className="absolute inset-0 block h-full w-full bg-black object-contain"
          onTimeUpdate={(e) => {
            const video = e.currentTarget;
            if (trim && trim.end != null && video.currentTime > trim.end) {
              video.pause();
              video.currentTime = trim.end;
            }
            onTime(video.currentTime + timeOffset);
          }}
        >
          Dein Browser kann dieses Video nicht abspielen.
        </video>
        {overlay}
      </div>
    </GlassCard>
  );
}
