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
  /* Der Wortlaut beim Öffnen der Seite, unveränderlich. Nur daraus lässt sich ein aus dem
   * Untertitel genommenes Wort noch anzeigen und zurückholen - ``original`` ist nach dem
   * Speichern selbst leer. Siehe ClipDetail. */
  gesprochen: TranscriptWord[];
  wordFrom: number;
  wordTo: number;
  speakers: string[];
  speakerNames: Record<string, string>;
  /* War die Sprechertrennung eingerichtet? Ohne sie hängen alle Wörter an einem Sprecher, und die
   * Auswahlliste unten hat genau einen Eintrag. Das muss dabeistehen, sonst sucht jemand den
   * zweiten Sprecher, den es hier nie geben wird. */
  sprechertrennung?: "done" | "skipped" | null;
  /* Stelle im ganzen Video, die gerade läuft */
  currentTime: number;
  canEdit: boolean;
  /* ``merken`` heisst: die Schreibweise kommt ins Woerterbuch der Marke und gilt fuer die
   * naechsten Videos. Gedacht fuer Namen, nicht fuer jeden Tippfehler. */
  onEditWord: (index: number, text: string, merken: boolean) => void;
  /* Wörter aus dem Untertitel nehmen. Gesagt bleibt gesagt: nur die Schrift verschwindet. */
  onDeleteWords: (indices: number[]) => void;
  onChangeSpeaker: (indices: number[], speaker: string) => void;
  onSeek: (secondsInSource: number) => void;
  /* Ohne Markenprofil gibt es kein Woerterbuch, in das man etwas merken koennte. */
  markeVorhanden: boolean;
}

/* Text des Clips: Wortlaut ändern und zuordnen, wer spricht. */
export function ClipTextEditor({
  words,
  original,
  gesprochen,
  wordFrom,
  wordTo,
  speakers,
  speakerNames,
  sprechertrennung = null,
  currentTime,
  canEdit,
  onEditWord,
  onDeleteWords,
  onChangeSpeaker,
  onSeek,
  markeVorhanden,
}: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  /* Im Korrekturmodus oeffnet ein einfacher Klick die Korrektur statt zu springen. Der
   * Doppelklick bleibt, aber er ist nicht mehr der einzige Weg: eine Handlung, die man nur
   * findet, wenn man sie schon kennt, ist keine Handlung. */
  /* Das ausgewählte Wort, als Wortnummer. Genau eines, nicht mehrere.
   *
   * Vorher war das eine Menge und jeder Klick legte ein Wort dazu. Wer zwei Wörter nacheinander
   * anklickte, hatte zwei ausgewählt und löschte beim nächsten Druck beide - ohne dass irgendwo
   * stand, dass das erste noch dabei ist. Ein Klick wählt jetzt genau das an, worauf er zeigt;
   * derselbe Klick nochmal hebt die Auswahl wieder auf. */
  const [gewaehlt, setGewaehlt] = useState<number | null>(null);
  /* Der Text steht ganz da. Zusammengeklappt liess sich nichts auswählen, was weiter unten stand. */
  const ganz = true;
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

  const umschalten = (i: number) => setGewaehlt((prev) => (prev === i ? null : i));

  /* Ist das gewählte Wort schon aus dem Untertitel genommen? Dann heisst derselbe Knopf oben
   * „Wiederherstellen" - wer aus Versehen löscht, soll es an derselben Stelle zurückholen, an
   * der er es weggenommen hat, und nicht erst lernen, dass ein Doppelklick eine Korrektur
   * öffnet, in die man den alten Wortlaut von Hand einträgt. */
  const geloescht = gewaehlt != null && words[gewaehlt] != null && words[gewaehlt].text.trim() === "";
  /* Zurückholen geht nur, solange der gesprochene Wortlaut bekannt ist. Bei einem Wort, das in
   * einer früheren Sitzung genommen und gespeichert wurde, steht er nicht mehr hier - dann ist
   * der Knopf aus und sagt, warum. Ein Knopf, der sich drücken lässt und nichts tut, ist
   * schlimmer als keiner. */
  const alterWortlaut = gewaehlt == null ? "" : gesprochen[gewaehlt]?.text?.trim() || original[gewaehlt]?.text?.trim() || "";
  const kannZurueckholen = geloescht && alterWortlaut !== "";
  const zurueckHolen = () => {
    if (gewaehlt == null) return;
    if (!alterWortlaut) return;
    onEditWord(gewaehlt, alterWortlaut, false);
    setGewaehlt(null);
  };

  const loeschen = () => {
    if (gewaehlt == null) return;
    if (geloescht) {
      zurueckHolen();
      return;
    }
    onDeleteWords([gewaehlt]);
    setGewaehlt(null);
  };

  if (blocks.length === 0) {
    return (
      <GlassCard padding="md">
        <p className="text-sm text-text-2">Zu diesem Clip steht kein Text bereit.</p>
      </GlassCard>
    );
  }

  return (
    <GlassCard padding="md">
      {/* Ein Papierkorb statt zweier Knöpfe.
        *
        * Hier standen „Text korrigieren" und „Nur die Stelle zeigen". Der erste schaltete einen
        * Modus ein, den man nicht braucht: ein Doppelklick auf das Wort öffnet die Korrektur
        * ohnehin. Der zweite klappte den Text auf drei Zeilen zusammen - praktisch beim Mitlesen,
        * im Weg, sobald man Wörter auswählt.
        *
        * An ihrer Stelle das, was wirklich fehlte: Wörter aus dem Untertitel nehmen. Der Knopf
        * zählt mit, wie viele ausgewählt sind, und ist ohne Auswahl aus - ein Papierkorb, der
        * immer klickbar ist, lädt zum blinden Drücken ein. */}
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Text</h2>
        {canEdit && (
          <button
            type="button"
            onClick={loeschen}
            disabled={gewaehlt == null || (geloescht && !kannZurueckholen)}
            aria-label={
              gewaehlt == null
                ? "Erst ein Wort auswählen"
                : geloescht
                  ? "Das Wort wieder in den Untertitel aufnehmen"
                  : "Das Wort aus dem Untertitel nehmen"
            }
            title={
              gewaehlt == null
                ? undefined
                : geloescht
                  ? kannZurueckholen
                    ? "Wiederherstellen"
                    : "Dieses Wort wurde schon vor dem Öffnen der Seite aus dem Untertitel genommen. Der gesprochene Wortlaut steht hier nicht mehr; mit einem Doppelklick lässt er sich von Hand eintragen."
                  : "Aus dem Untertitel nehmen"
            }
            className={cn(
              "transition-soft inline-flex h-9 items-center gap-2 rounded-pill border px-3 text-sm",
              gewaehlt == null || (geloescht && !kannZurueckholen)
                ? "cursor-not-allowed border-line text-text-3"
                : geloescht
                  ? "border-brand/60 text-text hover:bg-brand/15"
                  : "border-danger/50 text-danger hover:bg-danger/10",
            )}
          >
            {geloescht ? (
              /* Ein Pfeil, der zurückkommt. Er sagt ohne Wort, dass es rückgängig geht. */
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="M3 8a5 5 0 1 0 1.6-3.7M3 2.8v2.9h2.9"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="M2.8 4.2h10.4M6.4 4.2V2.9h3.2v1.3M4.2 4.2l.6 8.2a1 1 0 0 0 1 .9h4.4a1 1 0 0 0 1-.9l.6-8.2"
                  stroke="currentColor"
                  strokeWidth="1.3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path d="M6.7 6.6v4M9.3 6.6v4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
            )}
            {geloescht && <span>Wiederherstellen</span>}
          </button>
        )}
      </div>
      <p className="mb-3 text-sm text-text-2">
        {!canEdit
          ? "Klick ein Wort an, um dorthin zu springen."
          : "Klick ein Wort an. Mit dem Papierkorb oben nimmst du es aus dem Untertitel: gesagt bleibt gesagt, geschrieben steht es nicht mehr. Es bleibt durchgestrichen stehen - klickst du es wieder an, holt derselbe Knopf es zurück. Doppelklick ändert die Schreibweise. Soll ein Wort ganz aus dem Video, geht das unter „Schnitt“ mit „Teil entfernen“."}
      </p>

      {/* Zusammengeklappt nur rund drei Zeilen, die mit dem Ton mitlaufen. Der ganze Text stand
        * vorher offen da und hat die halbe Seite gefuellt, obwohl fast immer nur die Stelle
        * interessiert, die gerade laeuft. */}
      {sprechertrennung === "skipped" && (
        <p className="text-xs text-text-3">
          Die Sprechertrennung ist auf diesem Server nicht eingerichtet. Alle Wörter hängen an einer
          Person. Du kannst sie unten von Hand zuordnen.
        </p>
      )}
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
                  /* Aus dem Untertitel genommen: das Wort bleibt lesbar, damit man es
                     zurückholen kann, aber durchgestrichen. */
                  const leer = w.text.trim() === "";
                  const active = currentTime >= w.start && currentTime < w.end + 0.15;
                  return (
                    <button
                      key={i}
                      ref={active ? aktivesWort : undefined}
                      type="button"
                      /* Ein Klick tut beides: auswählen und dorthin springen. Das ist kein
                         Kompromiss, sondern hilfreich - wer ein Wort zum Löschen anfasst, will
                         hören, ob es das richtige ist. */
                      onClick={() => {
                        onSeek(w.start);
                        if (canEdit) umschalten(i);
                      }}
                      onDoubleClick={() => canEdit && setEditingIndex(i)}
                      onKeyDown={(e) => {
                        if (!canEdit) return;
                        if (e.key === "Enter") {
                          e.preventDefault();
                          setEditingIndex(i);
                        }
                      }}
                      aria-pressed={canEdit ? gewaehlt === i : undefined}
                      aria-label={
                        canEdit
                          ? leer
                            ? `${gesprochen[i]?.text || original[i]?.text || "Wort"} ist aus dem Untertitel genommen, auswählen zum Wiederherstellen`
                            : `${w.text} auswählen`
                          : `Zu ${w.text} springen`
                      }
                      title={changed ? `Im Video gesprochen: ${original[i].text}` : low ? "Der Computer war sich hier nicht sicher" : undefined}
                      className={cn(
                        "transition-soft mx-px inline rounded-md px-0.5 py-0.5 text-left align-baseline hover:bg-white/10",
                        low && "word-low",
                        changed && "text-ai-soft",
                        active && "word-active",
                        editingIndex === i && "bg-white/20",
                        /* Ausgewählt mit Rahmen UND Hintergrund: nur über die Farbe zu gehen liesse
                           die Auswahl für jemanden verschwinden, der sie nicht unterscheiden kann
                           (WCAG 1.4.1). */
                        gewaehlt === i &&
                          (leer
                            ? "bg-brand/20 shadow-[inset_0_0_0_1.5px_var(--brand)]"
                            : "bg-danger/20 shadow-[inset_0_0_0_1.5px_var(--danger)]"),
                        leer && "text-text-3 line-through decoration-danger/70",
                      )}
                    >
                      {leer ? gesprochen[i]?.text || original[i]?.text || "leer" : w.text}
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
