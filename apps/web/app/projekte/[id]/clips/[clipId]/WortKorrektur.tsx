"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Timecode } from "@/components/ui/Timecode";
import type { TranscriptWord } from "@/lib/repo/types";

interface Props {
  /* Das Wort, wie es jetzt im Untertitel steht. */
  wort: TranscriptWord;
  /* Dasselbe Wort, wie der Computer es gehört hat. Bleibt stehen, auch nach mehreren Korrekturen. */
  gehoert: string;
  /* Gibt es ein Markenprofil? Ohne eins kann man sich keine Schreibweise merken. */
  markeVorhanden: boolean;
  onSpeichern: (text: string, merken: boolean) => void;
  onAbbrechen: () => void;
}

/* Eine Wortkorrektur mit dem Unterschied, auf den es ankommt.
 *
 * Eine Korrektur ändert die Schreibweise im Untertitel. Sie ändert NICHT, was im Video gesagt
 * wird: der Ton ist der Ton. Das steht hier ausdrücklich, weil sonst der Eindruck entsteht, man
 * könne hier den Clip umschreiben, und weil der Unterschied bei Eigennamen der ganze Punkt ist:
 * gesprochen wurde „placemedia", geschrieben gehört „PLACEMedia".
 */
export function WortKorrektur({ wort, gehoert, markeVorhanden, onSpeichern, onAbbrechen }: Props) {
  const [text, setText] = useState(wort.text);
  const [merken, setMerken] = useState(false);
  const feld = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    feld.current?.focus();
    feld.current?.select();
  }, []);

  const sauber = text.trim();
  const geaendert = sauber.length > 0 && sauber !== wort.text;

  return (
    <div
      className="mt-2 flex flex-col gap-3 rounded-inner border border-line bg-black/30 p-3"
      role="group"
      aria-label="Wort korrigieren"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onAbbrechen();
        }
      }}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-xs uppercase tracking-wide text-text-3">Im Video gesprochen</p>
        <p className="text-sm text-text">
          {`„${gehoert}“`}
          <span className="ml-2 text-text-3">
            <Timecode seconds={wort.start} className="text-inherit" />
          </span>
        </p>
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-xs uppercase tracking-wide text-text-3">Im Untertitel geschrieben</span>
        <input
          ref={feld}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (geaendert) onSpeichern(sauber, merken);
              else onAbbrechen();
            }
          }}
          /* Satzzeichen, Großschreibung und Eigennamen sollen genau so ankommen, wie sie getippt
           * werden. Deshalb hier keine Korrektur der Eingabe, nur die Leerzeichen am Rand. */
          spellCheck={false}
          autoComplete="off"
          className="transition-soft w-full rounded-inner border border-line bg-black/40 px-3 py-2 text-[17px] text-text focus:border-white/60 focus:outline-none"
        />
      </label>

      <p className="text-sm text-text-2">
        Das ändert nur den Untertitel. Was im Video gesagt wird, bleibt, wie es ist.
      </p>

      {markeVorhanden && (
        <label className="flex items-start gap-2.5 text-sm text-text-2">
          <input
            type="checkbox"
            checked={merken}
            onChange={(e) => setMerken(e.target.checked)}
            aria-label="Schreibweise für die Marke merken"
            className="mt-0.5 h-4 w-4 shrink-0 accent-white"
          />
          <span>
            Schreibweise merken. Der Computer schreibt dieses Wort dann in allen nächsten Videos so.
            Gedacht für Namen und Marken.
          </span>
        </label>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={!geaendert} onClick={() => onSpeichern(sauber, merken)}>
          Übernehmen
        </Button>
        <Button size="sm" variant="ghost" onClick={onAbbrechen}>
          Abbrechen
        </Button>
      </div>
    </div>
  );
}
