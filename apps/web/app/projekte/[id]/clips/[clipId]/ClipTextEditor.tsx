"use client";

import { useEffect, useRef, useState } from "react";
import { sprecherName } from "@/lib/transcript/sprechername";
import { GlassCard } from "@/components/ui/GlassCard";
import { Select } from "@/components/ui/Field";
import { Timecode } from "@/components/ui/Timecode";
import { cn } from "@/components/ui/cn";
import type { TranscriptWord } from "@/lib/repo/types";
import { WortKorrektur } from "./WortKorrektur";

/* Zusammenhängende Wörter desselben Sprechers. Geht aus review/ClipText.tsx hervor, dort waren
 * die Blöcke nur zum Lesen da; hier lässt sich jedes Wort ändern und jeder Block einem anderen
 * Sprecher zuordnen. */
interface Block {
  speaker: string;
  start: number;
  end: number;
  indices: number[];
}

const LOW_CONFIDENCE = 0.9;

export function blocksInRange(words: TranscriptWord[], from: number, to: number): Block[] {
  const out: Block[] = [];
  for (let i = from; i <= to; i += 1) {
    const w = words[i];
    if (!w) continue;
    const last = out[out.length - 1];
    if (last && last.speaker === w.speaker) {
      last.indices.push(i);
      last.end = w.end;
    } else {
      out.push({ speaker: w.speaker, start: w.start, end: w.end, indices: [i] });
    }
  }
  return out;
}

interface Props {
  words: TranscriptWord[];
  original: TranscriptWord[];
  wordFrom: number;
  wordTo: number;
  speakers: string[];
  speakerNames: Record<string, string>;
  /* Stelle im ganzen Video, die gerade läuft */
  currentTime: number;
  canEdit: boolean;
  /* ``merken`` heisst: die Schreibweise kommt ins Woerterbuch der Marke und gilt fuer die
   * naechsten Videos. Gedacht fuer Namen, nicht fuer jeden Tippfehler. */
  onEditWord: (index: number, text: string, merken: boolean) => void;
  onChangeSpeaker: (indices: number[], speaker: string) => void;
  onSeek: (secondsInSource: number) => void;
  /* Ohne Markenprofil gibt es kein Woerterbuch, in das man etwas merken koennte. */
  markeVorhanden: boolean;
}

/* Text des Clips: Wortlaut ändern und zuordnen, wer spricht. */
export function ClipTextEditor({
  words,
  original,
  wordFrom,
  wordTo,
  speakers,
  speakerNames,
  currentTime,
  canEdit,
  onEditWord,
  onChangeSpeaker,
  onSeek,
  markeVorhanden,
}: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  /* Im Korrekturmodus oeffnet ein einfacher Klick die Korrektur statt zu springen. Der
   * Doppelklick bleibt, aber er ist nicht mehr der einzige Weg: eine Handlung, die man nur
   * findet, wenn man sie schon kennt, ist keine Handlung. */
  const [korrigieren, setKorrigieren] = useState(false);
  const [ganz, setGanz] = useState(false);
  const blocks = blocksInRange(words, wordFrom, wordTo);
  const kasten = useRef<HTMLDivElement | null>(null);
  const aktivesWort = useRef<HTMLButtonElement | null>(null);

  /* Das gesprochene Wort in Sicht halten. Der Text ist lang, die Stelle wandert, und wer zusieht
   * soll nicht scrollen muessen um zu lesen, was gerade gesagt wird.
   *
   * Gescrollt wird im Kasten selbst und nicht mit scrollIntoView: das zieht sonst die ganze Seite
   * mit, und die Vorschau oben springt aus dem Bild. */
  useEffect(() => {
    if (ganz || editingIndex != null) return;
    const box = kasten.current;
    const wort = aktivesWort.current;
    if (!box || !wort) return;
    const ziel = wort.offsetTop - box.clientHeight / 2 + wort.offsetHeight / 2;
    box.scrollTo({ top: Math.max(0, ziel), behavior: "smooth" });
  }, [currentTime, ganz, editingIndex]);

  if (blocks.length === 0) {
    return (
      <GlassCard padding="md">
        <p className="text-sm text-text-2">Zu diesem Clip steht kein Text bereit.</p>
      </GlassCard>
    );
  }

  return (
    <GlassCard padding="md">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Text</h2>
        <div className="flex flex-wrap items-center gap-3">
          {canEdit && (
            <button
              type="button"
              onClick={() => {
                setKorrigieren((v) => !v);
                setEditingIndex(null);
              }}
              aria-pressed={korrigieren}
              className={cn(
                "transition-soft rounded-pill border px-3 py-1.5 text-sm",
                korrigieren ? "border-white/60 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong",
              )}
            >
              {korrigieren ? "Fertig mit Korrigieren" : "Text korrigieren"}
            </button>
          )}
          <button
            type="button"
            onClick={() => setGanz((v) => !v)}
            className="transition-soft text-sm text-text-2 underline underline-offset-4 hover:text-text"
          >
            {ganz ? "Nur die Stelle zeigen" : "Ganzen Text zeigen"}
          </button>
        </div>
      </div>
      <p className="mb-3 text-sm text-text-2">
        {!canEdit
          ? "Klick ein Wort an, um dorthin zu springen."
          : korrigieren
            ? "Klick das Wort an, dessen Schreibweise du ändern willst. Der Ton bleibt, wie er ist."
            : "Klick ein Wort an, um dorthin zu springen. Zum Ändern auf „Text korrigieren“."}
      </p>

      {/* Zusammengeklappt nur rund drei Zeilen, die mit dem Ton mitlaufen. Der ganze Text stand
        * vorher offen da und hat die halbe Seite gefuellt, obwohl fast immer nur die Stelle
        * interessiert, die gerade laeuft. */}
      <div
        ref={kasten}
        className={cn(
          "flex flex-col gap-5 overflow-y-auto pr-1",
          ganz ? "max-h-[60dvh]" : "max-h-[8.6rem]",
        )}
      >
        {blocks.map((b, bi) => {
          const label = sprecherName(b.speaker, speakerNames);
          return (
            <section key={`${b.speaker}-${bi}`} aria-label={`${label} ab ${Math.floor(b.start)} Sekunden`}>
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <div className="w-[150px]">
                  <Select
                    aria-label={`Wer spricht ab ${Math.floor(b.start)} Sekunden`}
                    value={b.speaker}
                    disabled={!canEdit}
                    onChange={(e) => onChangeSpeaker(b.indices, e.target.value)}
                  >
                    {/* „SPEAKER_00" ist eine Kennung aus der Spracherkennung, kein Name. Wer
                        hier entscheidet, wem ein Satz gehört, kann damit nichts anfangen. */}
                    {speakers.map((s) => (
                      <option key={s} value={s}>
                        {sprecherName(s, speakerNames)}
                      </option>
                    ))}
                  </Select>
                </div>
                <button
                  type="button"
                  onClick={() => onSeek(b.start)}
                  className="font-mono text-xs text-text-2 hover:text-text"
                  aria-label={`Zu ${Math.floor(b.start)} Sekunden springen`}
                >
                  <Timecode seconds={b.start} className="text-inherit" />
                </button>
              </div>

              <p className="text-[16px] leading-[1.75] text-text">
                {b.indices.map((i) => {
                  const w = words[i];
                  const changed = original[i] != null && original[i].text !== w.text;
                  const low = w.prob < LOW_CONFIDENCE;
                  const active = currentTime >= w.start && currentTime < w.end + 0.15;
                  return (
                    <button
                      key={i}
                      ref={active ? aktivesWort : undefined}
                      type="button"
                      onClick={() => (korrigieren && canEdit ? setEditingIndex(i) : onSeek(w.start))}
                      onDoubleClick={() => canEdit && setEditingIndex(i)}
                      onKeyDown={(e) => {
                        if (canEdit && e.key === "Enter") {
                          e.preventDefault();
                          setEditingIndex(i);
                        }
                      }}
                      aria-label={korrigieren && canEdit ? `${w.text} korrigieren` : `Zu ${w.text} springen`}
                      title={changed ? `Im Video gesprochen: ${original[i].text}` : low ? "Der Computer war sich hier nicht sicher" : undefined}
                      className={cn(
                        "transition-soft mx-px inline rounded-md px-0.5 py-0.5 text-left align-baseline hover:bg-white/10",
                        low && "word-low",
                        changed && "text-ai-soft",
                        active && "word-active",
                        editingIndex === i && "bg-white/20",
                        korrigieren && canEdit && "cursor-text underline decoration-dotted decoration-white/30 underline-offset-4",
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

      {/* Die Korrektur steht UNTER dem Textkasten und nicht darin: der Kasten zeigt
        * zusammengeklappt nur drei Zeilen, und eine Eingabe mit Knöpfen passt dort nicht hinein.
        * Im Kasten war das Feld sichtbar und „Übernehmen" abgeschnitten. */}
      {editingIndex != null && words[editingIndex] && (
        <WortKorrektur
          key={editingIndex}
          wort={words[editingIndex]}
          /* Das Original aus der Spracherkennung, nicht die letzte Fassung: sonst stünde nach der
           * zweiten Korrektur die erste Korrektur als „gesprochen" da. */
          gehoert={original[editingIndex]?.text ?? words[editingIndex].text}
          markeVorhanden={markeVorhanden}
          onSpeichern={(text, merken) => {
            onEditWord(editingIndex, text, merken);
            setEditingIndex(null);
          }}
          onAbbrechen={() => setEditingIndex(null)}
        />
      )}
    </GlassCard>
  );
}
