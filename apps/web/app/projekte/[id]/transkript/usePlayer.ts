"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export interface PlayerState {
  currentTime: number;
  playing: boolean;
  duration: number;
}

export interface PlayerControls extends PlayerState {
  toggle: () => void;
  play: () => void;
  pause: () => void;
  seek: (t: number) => void;
  seekBy: (delta: number) => void;
}

/* Einheitliche Player-Steuerung: echtes <video> (Proxy aus der Medien-URL) oder simulierte Zeitachse (Demo ohne Datei).
 * Mit echtem Video ist das Element die Wahrheit: currentTime, play/pause und seek laufen über das Element, die
 * React-Zeit wird während der Wiedergabe per requestAnimationFrame nachgeführt (timeupdate feuert nur etwa 4x pro Sekunde). */
export function usePlayer(videoRef: RefObject<HTMLVideoElement | null>, fallbackDuration: number): PlayerControls {
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(fallbackDuration);
  const simulated = useRef(false);
  const rafRef = useRef<number | null>(null);
  const lastTick = useRef<number>(0);
  const timeRef = useRef(0);

  useEffect(() => {
    const video = videoRef.current;
    simulated.current = !video;
    if (video) {
      const onTime = () => {
        timeRef.current = video.currentTime;
        setCurrentTime(video.currentTime);
      };
      const onMeta = () => setDuration(Number.isFinite(video.duration) && video.duration > 0 ? video.duration : fallbackDuration);
      const onPlay = () => setPlaying(true);
      const onPause = () => {
        setPlaying(false);
        onTime();
      };
      if (video.readyState >= 1) onMeta();
      video.addEventListener("timeupdate", onTime);
      video.addEventListener("seeked", onTime);
      video.addEventListener("loadedmetadata", onMeta);
      video.addEventListener("durationchange", onMeta);
      video.addEventListener("play", onPlay);
      video.addEventListener("pause", onPause);
      video.addEventListener("ended", onPause);
      return () => {
        video.removeEventListener("timeupdate", onTime);
        video.removeEventListener("seeked", onTime);
        video.removeEventListener("loadedmetadata", onMeta);
        video.removeEventListener("durationchange", onMeta);
        video.removeEventListener("play", onPlay);
        video.removeEventListener("pause", onPause);
        video.removeEventListener("ended", onPause);
      };
    }
    return undefined;
  }, [videoRef, fallbackDuration]);

  /* Echtes Video: Zeit während der Wiedergabe flüssig nachführen */
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !playing) return undefined;
    let frame: number | null = null;
    const tick = () => {
      timeRef.current = video.currentTime;
      setCurrentTime(video.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      if (frame != null) cancelAnimationFrame(frame);
    };
  }, [videoRef, playing]);

  useEffect(() => {
    if (!simulated.current || !playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      return;
    }
    lastTick.current = performance.now();
    const step = (now: number) => {
      const delta = (now - lastTick.current) / 1000;
      lastTick.current = now;
      const next = Math.min(duration, timeRef.current + delta);
      timeRef.current = next;
      setCurrentTime(next);
      if (next >= duration) {
        setPlaying(false);
        return;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, duration]);

  const play = useCallback(() => {
    const video = videoRef.current;
    if (video) void video.play();
    else setPlaying(true);
  }, [videoRef]);

  const pause = useCallback(() => {
    const video = videoRef.current;
    if (video) video.pause();
    else setPlaying(false);
  }, [videoRef]);

  const toggle = useCallback(() => {
    const video = videoRef.current;
    const isPlaying = video ? !video.paused : playing;
    if (isPlaying) pause();
    else play();
  }, [videoRef, playing, play, pause]);

  const seek = useCallback(
    (t: number) => {
      const clamped = Math.max(0, Math.min(duration, t));
      const video = videoRef.current;
      if (video) video.currentTime = clamped;
      timeRef.current = clamped;
      setCurrentTime(clamped);
    },
    [videoRef, duration],
  );

  const seekBy = useCallback(
    (delta: number) => {
      const video = videoRef.current;
      const base = video ? video.currentTime : timeRef.current;
      seek(base + delta);
    },
    [videoRef, seek],
  );

  return { currentTime, playing, duration, toggle, play, pause, seek, seekBy };
}
