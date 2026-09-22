"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Toggle } from "@/components/ui/Toggle";
import { Badge } from "@/components/ui/Badge";
import { Checkbox } from "@/components/ui/Field";
import { Timecode } from "@/components/ui/Timecode";
import { cn } from "@/components/ui/cn";
import { reclassify, countFillers } from "@/lib/transcript/fillers";
import type { TranscriptVersion, TranscriptWord } from "@/lib/repo/types";
import { usePlayer } from "./usePlayer";
import { VideoStage } from "./VideoStage";

interface Props {
  sourceId: string;
  title: string;
  durationS: number;
  videoSrc: string | null;
  transcript: TranscriptVersion;
}

interface Correction {
  old_text: string;
  new_text: string;
  add_to_vocab: boolean;
}

interface Paragraph {
  speaker: string;
  start: number;
  end: number;
  indices: number[];
}

const LOW_CONFIDENCE = 0.9;

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

function buildParagraphs(words: TranscriptWord[]): Paragraph[] {
  const out: Paragraph[] = [];
  words.forEach((w, i) => {
    const last = out[out.length - 1];
    if (last && last.speaker === w.speaker) {
      last.indices.push(i);
      last.end = w.end;
    } else {
      out.push({ speaker: w.speaker, start: w.start, end: w.end, indices: [i] });
    }
  });
  return out;
}

function findActiveIndex(words: TranscriptWord[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  let best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].start <= t) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

export function TranscriptEditor({ sourceId, title, durationS, videoSrc, transcript }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const player = usePlayer(videoRef, durationS);

  const [original, setOriginal] = useState<TranscriptWord[]>(transcript.words);
  const [words, setWords] = useState<TranscriptWord[]>(transcript.words);
  const [corrections, setCorrections] = useState<Map<number, Correction>>(new Map());
  const [speakerNames, setSpeakerNames] = useState<Record<string, string>>(transcript.stats.speaker_names ?? {});
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editingSpeaker, setEditingSpeaker] = useState<number | null>(null);
  const [removeFillers, setRemoveFillers] = useState(false);
  const [version, setVersion] = useState(transcript.version);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [followPlayback, setFollowPlayback] = useState(true);

  const paragraphs = useMemo(() => buildParagraphs(words), [words]);
  const activeIndex = useMemo(() => findActiveIndex(words, player.currentTime), [words, player.currentTime]);
  const activeSpeaker = activeIndex >= 0 ? (speakerNames[words[activeIndex].speaker] ?? words[activeIndex].speaker) : null;
  const fillers = useMemo(() => countFillers(words), [words]);
  const lowCount = useMemo(() => words.filter((w) => w.prob < LOW_CONFIDENCE).length, [words]);
  const dirty = corrections.size > 0 || JSON.stringify(speakerNames) !== JSON.stringify(transcript.stats.speaker_names ?? {});

  const wordRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  /* Aktives Wort im Blick halten */
  useEffect(() => {
    if (!followPlayback || !player.playing || activeIndex < 0) return;
    const el = wordRefs.current.get(activeIndex);
    el?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [activeIndex, followPlayback, player.playing]);

  /* Tastatur: Leertaste Play/Pause, Pfeile ±5 s (nur wenn Fokus nicht in einem Eingabefeld) */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || editingIndex != null || editingSpeaker != null) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      const isWordButton = target?.dataset.word === "true";
      /* Andere Buttons (Play, Sprecher, Speichern) behalten ihr natives Verhalten bei Leertaste */
      const otherButton = target?.tagName === "BUTTON" && !isWordButton;
      if (e.code === "Space" || e.key === " ") {
        if (otherButton) return;
        e.preventDefault();
        player.toggle();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        player.seekBy(-5);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        player.seekBy(5);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      /* Verhindert, dass die Leertaste auf einem Wort-Button zusätzlich einen Klick (Sprung) auslöst */
      const target = e.target instanceof HTMLElement ? e.target : null;
      if ((e.code === "Space" || e.key === " ") && target?.dataset.word === "true") e.preventDefault();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
    };
  }, [player, editingIndex, editingSpeaker]);

  const commitWord = useCallback(
    (index: number, raw: string) => {
      const text = raw.trim();
      setEditingIndex(null);
      if (!text) return;
      setWords((prev) => {
        if (prev[index].text === text) return prev;
        const next = [...prev];
        next[index] = reclassify(prev[index], text);
        return next;
      });
      setCorrections((prev) => {
        const next = new Map(prev);
        const orig = original[index];
        if (!orig || orig.text === text) {
          next.delete(index);
        } else {
          const existing = next.get(index);
          next.set(index, {
            old_text: orig.text,
            new_text: text,
            add_to_vocab: existing?.add_to_vocab ?? /^[A-ZÄÖÜ]/.test(text),
          });
        }
        return next;
      });
    },
    [original],
  );

  const renameSpeaker = (speaker: string, raw: string) => {
    const value = raw.trim();
    setSpeakerNames((prev) => {
      const next = { ...prev };
      if (value && value !== speaker) next[speaker] = value;
      else delete next[speaker];
      return next;
    });
    setEditingSpeaker(null);
  };

  const toggleVocab = (index: number, value: boolean) => {
    setCorrections((prev) => {
      const next = new Map(prev);
      const c = next.get(index);
      if (c) next.set(index, { ...c, add_to_vocab: value });
      return next;
    });
  };

  const revert = (index: number) => {
    setWords((prev) => {
      const next = [...prev];
      next[index] = original[index];
      return next;
    });
    setCorrections((prev) => {
      const next = new Map(prev);
      next.delete(index);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const body = {
        words,
        corrections: [...corrections.entries()].map(([word_index, c]) => ({ word_index, ...c })),
        speaker_names: speakerNames,
      };
      const res = await fetch(`/api/projects/${sourceId}/transcript`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await res.json()) as { ok?: boolean; error?: string; version?: TranscriptVersion; vocab_added?: string[] };
      if (!res.ok || !data.version) throw new Error(data.error ?? "Speichern fehlgeschlagen");
      setVersion(data.version.version);
      setOriginal(words);
      setCorrections(new Map());
      const n = data.vocab_added?.length ?? 0;
      const vocabNote = n === 0 ? "" : n === 1 ? ", 1 Wort ins Marken-Wörterbuch übernommen" : `, ${n} Wörter ins Marken-Wörterbuch übernommen`;
      setMessage({ tone: "ok", text: `Version ${data.version.version} gespeichert${vocabNote}.` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Speichern fehlgeschlagen" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:items-start">
      <div className="lg:sticky lg:top-28">
        <VideoStage videoRef={videoRef} videoSrc={videoSrc} title={title} player={player} activeSpeaker={activeSpeaker} />
        <GlassCard padding="md" className="mt-5">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <Toggle
              checked={removeFillers}
              onChange={setRemoveFillers}
              label="Füllwörter entfernen"
              description={`${fillers.hard} harte Füller, ${fillers.soft} Vorschläge. Modalpartikeln bleiben.`}
            />
            <Toggle checked={followPlayback} onChange={setFollowPlayback} label="Text folgt Wiedergabe" />
          </div>
          <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-4 text-sm">
            <div>
              <dt className="text-text-2">Wörter</dt>
              <dd className="font-mono text-text">{words.length}</dd>
            </div>
            <div>
              <dt className="text-text-2">Unsicher</dt>
              <dd className="font-mono text-attention">{lowCount}</dd>
            </div>
            <div>
              <dt className="text-text-2">Version</dt>
              <dd className="font-mono text-text">{version}</dd>
            </div>
          </dl>
        </GlassCard>
      </div>

      <div className="flex flex-col gap-5">
        <GlassCard padding="lg" className="max-h-[70vh] overflow-y-auto lg:max-h-[calc(100dvh-9rem)]">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Badge>{transcript.asr_model_id?.split("/").pop() ?? "ASR"}</Badge>
              {lowCount > 0 && <Badge tone="attention">{lowCount} Wörter prüfen</Badge>}
            </div>
            <p className="text-xs text-text-2">
              Orange unterstrichen: Konfidenz unter {Math.round(LOW_CONFIDENCE * 100)} %
            </p>
          </div>

          <div className="flex flex-col gap-6">
            {paragraphs.map((p, pi) => {
              const label = speakerNames[p.speaker] ?? p.speaker;
              const isEditingSpeaker = editingSpeaker === pi;
              return (
                <section key={`${p.speaker}-${pi}`} aria-label={`${label} ab ${Math.floor(p.start)} Sekunden`}>
                  <div className="mb-2 flex items-center gap-3">
                    {isEditingSpeaker ? (
                      <input
                        autoFocus
                        defaultValue={label}
                        aria-label={`Name für ${p.speaker}`}
                        onFocus={(e) => e.currentTarget.select()}
                        className="h-8 rounded-pill border border-white/50 bg-black/60 px-3 text-sm text-text focus:outline-none"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            renameSpeaker(p.speaker, e.currentTarget.value);
                          } else if (e.key === "Escape") {
                            setEditingSpeaker(null);
                          }
                        }}
                        onBlur={(e) => renameSpeaker(p.speaker, e.currentTarget.value)}
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => setEditingSpeaker(pi)}
                        title={`${p.speaker} umbenennen`}
                        className={cn(
                          "transition-soft inline-flex h-8 items-center gap-2 rounded-pill border px-3 text-sm font-medium hover:border-white/50",
                          activeIndex >= 0 && words[activeIndex].speaker === p.speaker ? "border-ai-soft/60 text-text" : "border-line-strong text-text",
                        )}
                      >
                        {label}
                        {label !== p.speaker && <span className="font-mono text-xs text-text-3">{p.speaker}</span>}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => player.seek(p.start)}
                      className="font-mono text-xs text-text-2 hover:text-text"
                      aria-label={`Zu ${Math.floor(p.start)} Sekunden springen`}
                    >
                      <Timecode seconds={p.start} className="text-inherit" />
                    </button>
                  </div>
                  <p className="text-[17px] leading-[1.9] text-text">
                    {p.indices.map((i) => {
                      const w = words[i];
                      const low = w.prob < LOW_CONFIDENCE;
                      const corrected = corrections.has(i);
                      const active = i === activeIndex;
                      if (editingIndex === i) {
                        return (
                          <input
                            key={i}
                            autoFocus
                            defaultValue={w.text}
                            aria-label={`Wort bearbeiten: ${w.text}`}
                            size={Math.max(3, w.text.length + 1)}
                            onFocus={(e) => e.currentTarget.select()}
                            className="mx-0.5 inline-block rounded-md border border-white/60 bg-black/70 px-1.5 py-0.5 font-sans text-[17px] text-text focus:outline-none"
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                commitWord(i, e.currentTarget.value);
                              } else if (e.key === "Escape") {
                                setEditingIndex(null);
                              }
                            }}
                            onBlur={(e) => commitWord(i, e.currentTarget.value)}
                          />
                        );
                      }
                      const hardRemoved = removeFillers && w.filler === "hard";
                      const softSuggested = removeFillers && w.filler === "soft";
                      const tooltip = [
                        low ? `Konfidenz ${Math.round(w.prob * 100)} %` : null,
                        hardRemoved ? "Harter Füller, wird entfernt" : null,
                        softSuggested ? "Weicher Füller, Vorschlag zur Entfernung" : null,
                        w.negation ? "Verneinung" : null,
                        corrected ? `Korrigiert (vorher „${corrections.get(i)?.old_text}“)` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ");
                      return (
                        <button
                          key={i}
                          type="button"
                          ref={(el) => {
                            if (el) wordRefs.current.set(i, el);
                            else wordRefs.current.delete(i);
                          }}
                          data-word="true"
                          onClick={() => player.seek(w.start)}
                          onDoubleClick={() => setEditingIndex(i)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              setEditingIndex(i);
                            }
                          }}
                          title={tooltip || undefined}
                          aria-label={tooltip ? `${w.text}. ${tooltip}` : undefined}
                          className={cn(
                            "transition-soft mx-px inline rounded-md px-0.5 py-0.5 text-left align-baseline hover:bg-white/10",
                            low && "word-low",
                            hardRemoved && "word-hard",
                            softSuggested && "word-soft",
                            corrected && "text-ai-soft",
                            w.negation && "font-semibold",
                            active && "word-active",
                          )}
                        >
                          {w.text}
                        </button>
                      );
                    })}
                  </p>
                </section>
              );
            })}
          </div>
        </GlassCard>

        <GlassCard padding="md" selected={corrections.size > 0}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-medium">
                {corrections.size === 0 ? "Keine Korrekturen" : corrections.size === 1 ? "1 Korrektur" : `${corrections.size} Korrekturen`}
              </p>
              <p className="text-sm text-text-2">Speichern legt eine neue Version an. Nichts wird überschrieben.</p>
            </div>
            <Button onClick={save} disabled={saving || !dirty}>
              {saving ? "Wird gespeichert" : "Speichern"}
            </Button>
          </div>
          {corrections.size > 0 && (
            <ul className="mt-4 flex flex-col gap-3 border-t border-line pt-4">
              {[...corrections.entries()].map(([i, c]) => (
                <li key={i} className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2 text-sm">
                    <Timecode seconds={words[i].start} className="text-xs" />
                    <span className="text-text-3 line-through">{c.old_text}</span>
                    <span className="text-text">{c.new_text}</span>
                    <button type="button" onClick={() => revert(i)} className="text-xs text-text-2 underline hover:text-text">
                      zurück
                    </button>
                  </div>
                  <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm text-text-2">
                    <Checkbox checked={c.add_to_vocab} onChange={(e) => toggleVocab(i, e.target.checked)} />
                    ins Marken-Wörterbuch übernehmen
                  </label>
                </li>
              ))}
            </ul>
          )}
          {message && (
            <p className={cn("mt-3 text-sm", message.tone === "ok" ? "text-text" : "text-attention")} role="status" aria-live="polite">
              {message.text}
            </p>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
