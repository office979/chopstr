"use client";

import type { RefObject } from "react";
import { Mark } from "@/components/brand/Mark";
import { GlassCard } from "@/components/ui/GlassCard";
import { Grain } from "@/components/ui/Grain";
import { Timecode } from "@/components/ui/Timecode";
import { Badge } from "@/components/ui/Badge";
import type { PlayerControls } from "./usePlayer";

interface Props {
  videoRef: RefObject<HTMLVideoElement | null>;
  videoSrc: string | null;
  title: string;
  player: PlayerControls;
  activeSpeaker: string | null;
}

/* Video als Held. Ohne Datei: Glas-Platzhalter mit Poster und funktionierender Zeitachse. */
export function VideoStage({ videoRef, videoSrc, title, player, activeSpeaker }: Props) {
  const { currentTime, duration, playing } = player;
  const pct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <GlassCard padding="none" className="overflow-hidden">
      <div className="relative aspect-video w-full bg-raised">
        {videoSrc ? (
          <video ref={videoRef} src={videoSrc} className="h-full w-full" playsInline preload="metadata" aria-label={title}>
            Dein Browser kann dieses Video nicht abspielen.
          </video>
        ) : (
          <div className="relative flex h-full w-full flex-col items-center justify-center gap-3">
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse at 50% 20%, rgba(2,12,245,0.35) 0%, rgba(27,26,98,0.25) 35%, rgba(0,0,0,0) 70%)",
              }}
            />
            <Grain opacity={0.07} />
            <Mark size={48} className="relative" />
            <p className="relative text-sm text-text-2">Demo ohne Videodatei, Zeitachse läuft simuliert</p>
            {activeSpeaker && (
              <Badge tone="ai" className="relative">
                {activeSpeaker}
              </Badge>
            )}
          </div>
        )}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 h-24"
          style={{ background: "linear-gradient(180deg, rgba(0,0,0,0), rgba(0,0,0,0.75))" }}
        />
      </div>

      <div className="flex flex-col gap-3 p-4 sm:p-5">
        <input
          type="range"
          className="timeline"
          min={0}
          max={Math.max(1, duration)}
          step={0.05}
          value={currentTime}
          onChange={(e) => player.seek(Number(e.target.value))}
          aria-label="Zeitachse"
          aria-valuetext={`${Math.floor(currentTime)} Sekunden`}
          style={{ ["--progress" as string]: `${pct}%` }}
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={player.toggle}
            aria-label={playing ? "Pause" : "Abspielen"}
            aria-pressed={playing}
            className="transition-soft inline-flex h-11 w-11 items-center justify-center rounded-full bg-text text-black hover:bg-white"
          >
            {playing ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <rect x="3" y="2.5" width="3.5" height="11" rx="1" />
                <rect x="9.5" y="2.5" width="3.5" height="11" rx="1" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <path d="M4.5 2.8v10.4c0 .8.9 1.3 1.6.9l8-5.2c.6-.4.6-1.4 0-1.8l-8-5.2c-.7-.4-1.6.1-1.6.9z" />
              </svg>
            )}
          </button>
          <button
            type="button"
            onClick={() => player.seekBy(-5)}
            className="transition-soft h-9 rounded-pill border border-line-strong px-3 font-mono text-xs text-text hover:bg-white/5"
            aria-label="5 Sekunden zurück"
          >
            -5 s
          </button>
          <button
            type="button"
            onClick={() => player.seekBy(5)}
            className="transition-soft h-9 rounded-pill border border-line-strong px-3 font-mono text-xs text-text hover:bg-white/5"
            aria-label="5 Sekunden vor"
          >
            +5 s
          </button>
          <div className="ml-auto flex items-center gap-1 font-mono text-sm">
            <Timecode seconds={currentTime} withMillis className="text-text" />
            <span className="text-text-3">/</span>
            <Timecode seconds={duration} />
          </div>
        </div>
        <p className="text-xs text-text-3">Leertaste: Play/Pause · Pfeiltasten: 5 Sekunden · Enter oder Doppelklick auf ein Wort: bearbeiten</p>
      </div>
    </GlassCard>
  );
}
