"use client";

import Link from "next/link";
import { useCallback, useId, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Toggle } from "@/components/ui/Toggle";
import { cn } from "@/components/ui/cn";
import type { TranscriptWord } from "@/lib/repo/types";
import {
  aktiverLook,
  FONTS,
  FONT_RUECKLAUF,
  GRENZEN,
  HIGHLIGHT_FARBEN,
  LOOKS,
  type CaptionStyle,
  type Look,
  maxZeichen,
  mitVorgabe,
} from "@/lib/clips/caption-style";
import {
  befundSatz,
  karten,
  korrektur,
  MAX_CPS,
  pruefen,
  tempo,
  type Befund,
  type Korrektur,
} from "@/lib/clips/untertitel-pruefung";

export interface GespeicherteVorlage {
  id: string;
  name: string;
  style: Record<string, unknown>;
}

/* Untere Kante der sicheren Fläche je Grundlage, in Pixeln bei 1920 Höhe. Die Vorschau braucht sie,
 * um den Text dort zu zeigen, wo er später steht. Spiegel der SafeZone aus captions_de.PRESETS. */
const SAFE_UNTEN: Record<string, number> = {
  "": 1600,
  tiktok_words: 1600,
  tiktok_bold: 1600,
  reels_clean: 1610,
  linkedin_static: 1700,
};
const BILD_H = 1920;
const BILD_B = 1080;

interface VorschauProps {
  stil: CaptionStyle;
  woerter: TranscriptWord[];
  /* Stelle im ganzen Video, an der der Player gerade steht. */
  zeit: number;
  /* Verschieben erlaubt? Nur mit Bearbeitungsrecht und nur, wenn es jemanden gibt, der die neue
   * Höhe entgegennimmt. */
  onHoehe?: (bottomMarginPx: number) => void;
}

/* Die Untertitel, wie sie im fertigen Clip stehen, über das laufende Bild gelegt.
 *
 * Gerechnet wird in Bildpunkten bei 1080x1920 und mit Containereinheiten ausgegeben, damit die
 * Vorschau in jeder Größe stimmt: 1 cqw ist ein Hundertstel der Breite des Videos. So braucht es
 * keinen Messcode, der bei jeder Fenstergröße neu laufen müsste. */
export function CaptionVorschau({ stil, woerter, zeit, onHoehe }: VorschauProps) {
  const s = mitVorgabe(stil);
  const safeUnten = SAFE_UNTEN[stil.preset ?? ""] ?? 1600;
  const rahmen = useRef<HTMLDivElement | null>(null);
  const [zieht, setZieht] = useState(false);
  const budget = maxZeichen(s.font_px) * s.max_lines;
  /* Dieselbe Einteilung wie im Renderer: karten() ist der Spiegel von captions_de.build_cards,
   * inklusive des Teilens zu langer Gruppen. Vorher hatte die Vorschau eine eigene Rechnung, und
   * genau da kam der Unterschied zwischen Vorschau und fertigem Video her. */
  const gruppen = useMemo(
    () => karten(woerter, s.words_per_card, budget, s.all_caps).map((k) => k.woerter),
    [woerter, s.words_per_card, budget, s.all_caps],
  );

  const aktiv = useMemo(() => {
    if (!gruppen.length) return null;
    for (const g of gruppen) {
      const von = g[0]?.start ?? 0;
      const bis = g[g.length - 1]?.end ?? 0;
      if (zeit >= von && zeit <= bis) return g;
    }
    /* Vor dem ersten Wort und in Sprechpausen: die erste Karte zeigen, damit die Einstellung
     * überhaupt zu sehen ist. Ein leeres Bild sagt dem Nutzer nichts über seinen Stil. */
    return gruppen[0];
  }, [gruppen, zeit]);

  if (!aktiv?.length) return null;
  const grundlinie = ((BILD_H - (safeUnten - s.bottom_margin_px)) / BILD_H) * 100;

  /* Ziehen: die Mausposition im Rahmen wird in „Bildpunkte über der Unterkante der sicheren
   * Fläche" zurückgerechnet und auf den erlaubten Bereich gezogen. Der Text kann so nie in einen
   * Bereich rutschen, in dem ihn Plattform-Elemente verdecken. */
  const ziehen = (e: React.PointerEvent) => {
    if (!onHoehe) return;
    e.preventDefault();
    e.stopPropagation();
    setZieht(true);
    const bewegen = (ev: PointerEvent) => {
      const el = rahmen.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      if (r.height <= 0) return;
      const yImBild = ((ev.clientY - r.top) / r.height) * BILD_H;
      const roh = safeUnten - yImBild;
      const [min, max] = GRENZEN.bottom_margin_px;
      onHoehe(Math.round(Math.max(min, Math.min(max, roh)) / 10) * 10);
    };
    const ende = () => {
      setZieht(false);
      window.removeEventListener("pointermove", bewegen);
      window.removeEventListener("pointerup", ende);
    };
    window.addEventListener("pointermove", bewegen);
    window.addEventListener("pointerup", ende);
  };

  return (
    <div
      ref={rahmen}
      className="pointer-events-none absolute inset-0 z-20 overflow-hidden"
      style={{ containerType: "inline-size" }}
    >
      {/* Die sichere Fläche, solange gezogen wird. Ohne sie ist „geht nicht weiter" ein Rätsel. */}
      {zieht && (
        <div
          aria-hidden="true"
          className="absolute rounded-[4px] border border-dashed border-white/40"
          style={{
            left: `${(60 / BILD_B) * 100}%`,
            right: `${(120 / BILD_B) * 100}%`,
            top: `${((safeUnten - GRENZEN.bottom_margin_px[1]) / BILD_H) * 100}%`,
            bottom: `${((BILD_H - safeUnten) / BILD_H) * 100}%`,
          }}
        />
      )}
      <div
        /* Über der Fläche, die Start und Pause schaltet: sonst schluckt die den Griff, und das
         * Ziehen startet nur das Video. Nur dieser Streifen liegt darüber, der Rest des Bildes
         * bleibt Start und Pause. */
        className={cn(
          "absolute z-20 flex justify-center text-center",
          onHoehe && "pointer-events-auto cursor-ns-resize",
        )}
        onPointerDown={ziehen}
        style={{
          left: `${(60 / BILD_B) * 100}%`,
          right: `${(120 / BILD_B) * 100}%`,
          bottom: `${grundlinie}%`,
        }}
      >
        <span
          style={{
            fontFamily: `"${s.font}", "Inter", system-ui, sans-serif`,
            fontSize: `${(s.font_px / BILD_B) * 100}cqw`,
            fontWeight: s.bold ? 800 : 500,
            lineHeight: 1.12,
            color: s.base_color,
            textTransform: s.all_caps ? "uppercase" : "none",
            /* Die Kontur von libass wird hier mit vier Schatten nachgestellt. Genau ist das nicht,
             * aber es zeigt, wie viel Gewicht die Kontur dem Text gibt. */
            textShadow: s.outline_px
              ? `0 0 ${(s.outline_px / BILD_B) * 100}cqw ${s.outline_color}, ${(s.outline_px / BILD_B) * 60}cqw 0 ${s.outline_color}, -${(s.outline_px / BILD_B) * 60}cqw 0 ${s.outline_color}, 0 ${(s.outline_px / BILD_B) * 60}cqw ${s.outline_color}, 0 -${(s.outline_px / BILD_B) * 60}cqw ${s.outline_color}`
              : "none",
            background: s.box ? s.box_color : "transparent",
            padding: s.box ? "0.12em 0.3em" : 0,
            borderRadius: s.box ? "0.1em" : 0,
          }}
        >
          {aktiv.map((w, i) => {
            const hell = s.highlight_words && zeit >= w.start && zeit <= w.end;
            return (
              <span key={`${w.start}-${i}`} style={{ color: hell ? s.highlight_color : undefined }}>
                {w.text}
                {i < aktiv.length - 1 ? " " : ""}
              </span>
            );
          })}
        </span>
      </div>
    </div>
  );
}

interface StudioProps {
  stil: CaptionStyle;
  onChange: (next: CaptionStyle) => void;
  vorlagen: GespeicherteVorlage[];
  onVorlagenChange: (next: GespeicherteVorlage[]) => void;
  /* Ein Beispielwort für die Längenwarnung, meist das längste im Clip. */
  canEdit: boolean;
  gespeichert: boolean;
  speichern: () => void;
  zuruecksetzen: () => void;
  saving: boolean;
  /* Die Schriften, für die in dieser Installation wirklich eine Datei vorliegt. Alles andere
   * kann weder die Vorschau zeigen noch der Renderer einbrennen. */
  schriftenVorhanden: string[];
  /* Die Wörter dieses Clips. Daraus entstehen die Proben auf den Stilkarten und die Prüfung,
   * ob der Text lesbar durchläuft. */
  woerter: TranscriptWord[];
  /* Zu einer Stelle springen, wenn jemand eine Warnung anklickt. */
  onSeek: (quellzeit: number) => void;
}

/* Untertitel einstellen, auf das Nötige gebracht.
 *
 * Sichtbar sind vier Looks, zwei Schieber und eine Reihe Farbpunkte. Das ist die ganze Bedienung.
 * „Welche Schrift, wie fett, wie dick die Kontur" sind drei Fragen, die niemand beantworten will,
 * der einen Clip fertig machen möchte; „wie soll es aussehen" ist eine. Wer doch an einer einzelnen
 * Schraube drehen will, findet alles unter „Mehr einstellen" — aber niemand muss dort hinein. */
export function CaptionStudio({
  stil,
  onChange,
  vorlagen,
  onVorlagenChange,
  canEdit,
  gespeichert,
  speichern,
  zuruecksetzen,
  saving,
  schriftenVorhanden,
  woerter,
  onSeek,
}: StudioProps) {
  const s = mitVorgabe(stil);
  const [mehr, setMehr] = useState(false);
  const [vorlageName, setVorlageName] = useState("");
  const [vorlageMeldung, setVorlageMeldung] = useState<string | null>(null);
  const idWoerter = useId();
  const idGroesse = useId();
  const idPosition = useId();
  const look = aktiverLook(stil);

  /* Ein echter Satz aus diesem Clip für die Proben. Sechs Wörter reichen, um Schrift, Farbe und
   * Großschreibung zu beurteilen, und passen in eine Kachel. */
  const probeSatz = useMemo(
    () => woerter.slice(0, 6).map((w) => w.text).join(" ") || "So sieht dein Text aus",
    [woerter],
  );

  /* Was am eingestellten Stil nicht aufgeht, gerechnet auf den GERADE eingestellten Stil. Aus dem
   * letzten Render wäre es eine Aussage über ein Aussehen, das vielleicht gar nicht mehr gilt. */
  const befunde = useMemo(() => pruefen(woerter, stil), [woerter, stil]);
  const lesetempo = useMemo(() => tempo(woerter, stil), [woerter, stil]);
  /* Die eine Einstellung, die alle „passt nicht"-Stellen auflöst. Ausgerechnet, nicht geraten. */
  const behebung = useMemo(() => korrektur(woerter, stil), [woerter, stil]);

  const setzen = useCallback(
    (teil: Partial<CaptionStyle>) => {
      const next = { ...stil, ...teil };
      /* Ein Wort kann keine zweite Zeile füllen. Gleiche Regel wie im Renderer, hier damit die
       * Vorschau sofort stimmt statt erst nach dem Speichern. */
      if (next.words_per_card === 1) next.max_lines = 1;
      onChange(next);
    },
    [stil, onChange],
  );

  /* Ob die gewählte Schrift wirklich vorliegt, weiß der Server: er sieht den Schriftordner.
   * Im Browser zu messen war ein Umweg mit falschem Ergebnis - der Browser kann jeden Text mit
   * einer Ersatzschrift setzen, und der Renderer hat davon ohnehin nichts.
   *
   * Dieselbe Liste gilt für beide Seiten: was in apps/web/public/fonts liegt, kann die Vorschau
   * zeigen UND der Renderer einbrennen (scripts/sync-fonts.mjs spiegelt es aus workers/fonts). */
  const schriftFehlt = useCallback((name: string) => !schriftenVorhanden.includes(name), [schriftenVorhanden]);
  const fehlendeSchrift = schriftFehlt(s.font);

  const vorlageSpeichern = async () => {
    const name = vorlageName.trim();
    if (!name) return;
    setVorlageMeldung(null);
    try {
      const res = await fetch("/api/caption-presets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, style: stil }),
      });
      const data = (await res.json()) as { error?: string; preset?: GespeicherteVorlage };
      if (!res.ok || !data.preset) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
      onVorlagenChange([...vorlagen.filter((v) => v.id !== data.preset!.id), data.preset].sort((a, b) => a.name.localeCompare(b.name)));
      setVorlageName("");
      setVorlageMeldung(`„${name}" gespeichert.`);
    } catch (err) {
      setVorlageMeldung(err instanceof Error ? err.message : "Das Speichern hat nicht geklappt");
    }
  };

  const vorlageLoeschen = async (v: GespeicherteVorlage) => {
    setVorlageMeldung(null);
    try {
      const res = await fetch(`/api/caption-presets/${v.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Die Vorlage ließ sich nicht entfernen");
      onVorlagenChange(vorlagen.filter((x) => x.id !== v.id));
      setVorlageMeldung(`„${v.name}" entfernt.`);
    } catch (err) {
      setVorlageMeldung(err instanceof Error ? err.message : "Die Vorlage ließ sich nicht entfernen");
    }
  };

  return (
    <GlassCard padding="md" selected={!gespeichert}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Untertitel</h2>
        {/* Der Unterschied zur Zeitleiste muss dastehen: dort gilt etwas ab einer Stelle, hier
          * fuer den ganzen Clip. Ohne diesen Satz sieht beides gleich aus. */}
        <p className="text-sm text-text-2">Für den ganzen Clip</p>
      </div>

      <div className="mt-5 flex flex-col gap-6">
        {/* 1. Wie soll es aussehen? Vier Karten, eine Berührung. Die Probe zeigt einen echten
          * Satz aus diesem Clip: „Wort Wort" sagt nichts darüber, wie der eigene Text wirkt. */}
        <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {LOOKS.map((l) => {
            /* Ein Stil, dessen Schrift nicht vorliegt, ist nicht wählbar. Ihn anzubieten hiesse,
             * eine Wahl zu ermöglichen, die im Export anders aussieht - und der Austausch fände
             * still statt. */
            const fehlt = schriftFehlt(mitVorgabe(l.stil).font);
            return (
              <button
                key={l.id}
                type="button"
                disabled={!canEdit || fehlt}
                onClick={() => setzen(l.stil)}
                aria-pressed={look === l.id}
                title={fehlt ? `Für diesen Stil fehlt die Schrift ${mitVorgabe(l.stil).font}` : undefined}
                className={cn(
                  "transition-soft flex flex-col items-center gap-2 rounded-inner border p-3",
                  fehlt && "cursor-not-allowed opacity-50",
                  !fehlt && "disabled:opacity-60",
                  look === l.id ? "border-white/60 bg-white/10" : "border-line hover:border-line-strong",
                )}
              >
                <LookProbe look={l} probe={probeSatz} ersatzschrift={fehlt} />
                <span className={cn("text-sm font-medium", look === l.id ? "text-text" : "text-text-2")}>{l.name}</span>
                <span className="text-center text-xs text-text-3">
                  {fehlt ? `Schrift ${mitVorgabe(l.stil).font} fehlt` : l.hinweis}
                </span>
              </button>
            );
          })}
        </section>

        {fehlendeSchrift && (
          <SchriftFehltHinweis name={s.font} onInter={() => setzen({ font: FONT_RUECKLAUF })} canEdit={canEdit} />
        )}

        {/* 2. Wie viele Wörter auf einmal */}
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <label htmlFor={idWoerter} className="text-sm font-medium text-text">
              Wörter auf einmal
            </label>
            <span className="text-sm tabular-nums text-text-2">{s.words_per_card}</span>
          </div>
          <input
            id={idWoerter}
            type="range"
            min={GRENZEN.words_per_card[0]}
            max={GRENZEN.words_per_card[1]}
            step={1}
            value={s.words_per_card}
            disabled={!canEdit}
            onChange={(e) => setzen({ words_per_card: Number(e.target.value) })}
            className="w-full accent-white disabled:opacity-60"
          />
          <p className="text-sm text-text-2">
            {s.words_per_card === 1 ? "Ein Wort nach dem anderen." : `Je ${s.words_per_card} Wörter zusammen.`}
          </p>
        </section>

        {/* 3. Wie groß */}
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <label htmlFor={idGroesse} className="text-sm font-medium text-text">
              Größe
            </label>
            <span className="text-sm tabular-nums text-text-2">{s.font_px} px</span>
          </div>
          <input
            id={idGroesse}
            type="range"
            min={GRENZEN.font_px[0]}
            max={GRENZEN.font_px[1]}
            step={2}
            value={s.font_px}
            disabled={!canEdit}
            onChange={(e) => setzen({ font_px: Number(e.target.value) })}
            className="w-full accent-white disabled:opacity-60"
          />
        </section>

        {/* 4. Position im Bild. Ziehen geht auch direkt in der Vorschau; der Schieber ist der
          * genaue Weg und der, den man mit der Tastatur bedienen kann. */}
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <label htmlFor={idPosition} className="text-sm font-medium text-text">
              Position
            </label>
            <span className="text-sm tabular-nums text-text-2">{s.bottom_margin_px} px über der Kante</span>
          </div>
          <input
            id={idPosition}
            type="range"
            min={GRENZEN.bottom_margin_px[0]}
            max={GRENZEN.bottom_margin_px[1]}
            step={10}
            value={s.bottom_margin_px}
            disabled={!canEdit}
            onChange={(e) => setzen({ bottom_margin_px: Number(e.target.value) })}
            className="w-full accent-white disabled:opacity-60"
          />
          <p className="text-sm text-text-2">
            Du kannst den Text auch in der Vorschau nach oben und unten ziehen. Weiter nach unten geht es nicht:
            dort liegen auf den Plattformen Bedienleiste und Beschreibung über dem Bild.
          </p>
        </section>

        {/* 5. Hervorhebung */}
        <section className="flex flex-col gap-3">
          <Toggle
            checked={s.highlight_words}
            disabled={!canEdit}
            onChange={(v) => setzen({ highlight_words: v })}
            label="Gesprochenes Wort hervorheben"
          />
          {s.highlight_words && (
            <div className="flex flex-wrap gap-2">
              {HIGHLIGHT_FARBEN.map((f) => (
                <button
                  key={f}
                  type="button"
                  disabled={!canEdit}
                  onClick={() => setzen({ highlight_color: f })}
                  aria-label={`Farbe ${f}`}
                  aria-pressed={s.highlight_color.toLowerCase() === f}
                  className={cn(
                    "transition-soft h-9 w-9 rounded-full border-2 disabled:opacity-60",
                    s.highlight_color.toLowerCase() === f ? "border-white" : "border-white/20 hover:border-white/50",
                  )}
                  style={{ background: f }}
                />
              ))}
            </div>
          )}
        </section>

        {/* 6. Hintergrund */}
        <section className="flex flex-col gap-3">
          <Toggle checked={s.box} disabled={!canEdit} onChange={(v) => setzen({ box: v })} label="Kasten hinter dem Text" />
          {s.box && (
            <Farbwahl label="Farbe des Kastens" wert={s.box_color} disabled={!canEdit} onChange={(v) => setzen({ box_color: v })} />
          )}
        </section>

        {/* 7. Was nicht aufgeht, als durchgehbare Aufgabe mit ausführbarer Korrektur. */}
        <Befunde
          befunde={befunde}
          onSeek={onSeek}
          tempo={lesetempo}
          behebung={behebung}
          canEdit={canEdit}
          onBeheben={(k) => setzen({ [k.feld]: k.wert } as Partial<CaptionStyle>)}
        />

        {/* 8. Vorlagen. Bewusst vom Speichern getrennt: „für diesen Clip übernehmen" und „für
          * alle nächsten merken" sind zwei Entscheidungen, und wer sie verwechselt, ändert
          * ungewollt das Aussehen aller künftigen Clips. */}
        {(vorlagen.length > 0 || canEdit) && (
          <section className="flex flex-col gap-2 border-t border-line pt-5">
            <p className="text-sm font-medium text-text">Vorlagen</p>
            <p className="text-sm text-text-2">
              Eine Vorlage ist ein gemerktes Aussehen. Sie ändert nichts an Videos, die schon geclippt sind.
            </p>
            {vorlagen.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {vorlagen.map((v) => (
                  <span key={v.id} className="inline-flex items-center gap-1 rounded-pill border border-line pl-3 pr-1 text-sm text-text-2">
                    <button type="button" disabled={!canEdit} onClick={() => onChange(v.style as CaptionStyle)} className="py-1.5 hover:text-text disabled:opacity-60">
                      {v.name}
                    </button>
                    <button
                      type="button"
                      disabled={!canEdit}
                      onClick={() => void vorlageLoeschen(v)}
                      aria-label={`Vorlage ${v.name} entfernen`}
                      className="transition-soft inline-flex h-6 w-6 items-center justify-center rounded-full text-text-3 hover:bg-white/10 hover:text-text disabled:opacity-60"
                    >
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                        <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                      </svg>
                    </button>
                  </span>
                ))}
              </div>
            )}
            {canEdit && (
              <div className="flex flex-wrap gap-2">
                <input
                  value={vorlageName}
                  onChange={(e) => setVorlageName(e.target.value)}
                  maxLength={60}
                  placeholder="Name, zum Beispiel Podcast fett"
                  aria-label="Name der Vorlage"
                  className="transition-soft min-w-[180px] flex-1 rounded-inner border border-line bg-black/40 px-4 py-3 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none"
                />
                <Button variant="ghost" disabled={!vorlageName.trim()} onClick={() => void vorlageSpeichern()}>
                  Als Vorlage speichern
                </Button>
              </div>
            )}
            {vorlageMeldung && (
              <p role="status" aria-live="polite" className="text-sm text-text-2">
                {vorlageMeldung}
              </p>
            )}
          </section>
        )}

        <button
          type="button"
          onClick={() => setMehr((v) => !v)}
          className="transition-soft self-start text-sm text-text-2 underline underline-offset-4 hover:text-text"
        >
          {mehr ? "Fein einstellen schließen" : "Fein einstellen"}
        </button>

        {mehr && (
          <section className="flex flex-col gap-4 border-t border-line pt-5">
            <Schriftwahl
              wert={s.font}
              disabled={!canEdit}
              vorhanden={schriftenVorhanden}
              onChange={(v) => setzen({ font: v })}
            />
            <Farbwahl label="Textfarbe" wert={s.base_color} disabled={!canEdit} onChange={(v) => setzen({ base_color: v })} />
            <Toggle checked={s.bold} disabled={!canEdit} onChange={(v) => setzen({ bold: v })} label="Fett" />
            <Toggle checked={s.all_caps} disabled={!canEdit} onChange={(v) => setzen({ all_caps: v })} label="Großbuchstaben" />
            <Regler
              label="Kontur"
              einheit="px"
              wert={s.outline_px}
              min={GRENZEN.outline_px[0]}
              max={GRENZEN.outline_px[1]}
              disabled={!canEdit}
              onChange={(v) => setzen({ outline_px: v })}
            />
            <Farbwahl label="Farbe der Kontur" wert={s.outline_color} disabled={!canEdit || s.outline_px === 0} onChange={(v) => setzen({ outline_color: v })} />
            {s.words_per_card > 1 && (
              <Regler
                label="Zeilen"
                wert={s.max_lines}
                min={GRENZEN.max_lines[0]}
                max={GRENZEN.max_lines[1]}
                disabled={!canEdit}
                onChange={(v) => setzen({ max_lines: v })}
              />
            )}
          </section>
        )}

        {canEdit && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
            <button
              type="button"
              onClick={zuruecksetzen}
              className="transition-soft text-sm text-text-2 underline underline-offset-4 hover:text-text"
            >
              Zurücksetzen
            </button>
            <Button variant={gespeichert ? "ghost" : "primary"} disabled={gespeichert || saving} onClick={speichern}>
              {saving ? "Wird gespeichert" : gespeichert ? "Gespeichert" : "Nur für diesen Clip speichern"}
            </Button>
          </div>
        )}
      </div>
    </GlassCard>
  );
}

/* Eine Probe des Looks mit einem echten Satz aus diesem Clip.
 *
 * Vorher stand hier „Wort Wort". Das zeigt Schrift und Farbe, aber nicht, wie der eigene Text
 * wirkt - und genau darum geht es bei der Wahl. Liegt die Schrift nicht vor, wird mit Inter
 * gesetzt und das steht daneben; eine Probe, die etwas anderes zeigt als der Export, ist
 * schlimmer als keine. */
function LookProbe({ look, probe, ersatzschrift }: { look: Look; probe: string; ersatzschrift: boolean }) {
  const v = mitVorgabe(look.stil);
  return (
    <span
      aria-hidden="true"
      className="flex h-10 w-full items-center justify-center overflow-hidden rounded-[6px] bg-black/60 px-1"
      style={{
        fontFamily: ersatzschrift ? `"Inter", system-ui, sans-serif` : `"${v.font}", "Inter", system-ui, sans-serif`,
        fontWeight: v.bold ? 800 : 500,
        color: v.base_color,
        textTransform: v.all_caps ? "uppercase" : "none",
        fontSize: 13,
        lineHeight: 1.15,
        letterSpacing: v.all_caps ? "0.02em" : undefined,
      }}
    >
      <span
        style={{
          background: v.box ? v.box_color : "transparent",
          padding: v.box ? "2px 6px" : 0,
          borderRadius: v.box ? 3 : 0,
          textShadow: v.outline_px ? `0 0 ${Math.max(1, v.outline_px / 3)}px ${v.outline_color}, 0 1px 2px ${v.outline_color}` : "none",
        }}
      >
        <span className="line-clamp-2 text-center">
          {probe.split(" ").map((w, i) => (
            <span key={i} style={{ color: i === 1 && v.highlight_words ? v.highlight_color : v.base_color }}>
              {w}{" "}
            </span>
          ))}
        </span>
      </span>
    </span>
  );
}

/* Die Schriftwahl. Nicht installierte Schriften bleiben sichtbar, aber nicht waehlbar: sie
 * verschweigen waere eine zweite Unwahrheit, und wer sie sucht, soll erfahren, warum sie fehlt. */
function Schriftwahl({
  wert,
  onChange,
  disabled,
  vorhanden,
}: {
  wert: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  vorhanden: string[];
}) {
  const id = useId();
  const fehlende = FONTS.filter((f) => !vorhanden.includes(f.id));
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium text-text">
        Schrift
      </label>
      <select
        id={id}
        value={wert}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="transition-soft w-full rounded-inner border border-line bg-black/40 px-4 py-3 text-[15px] text-text hover:border-line-strong focus:border-white/50 focus:outline-none disabled:opacity-60"
      >
        {FONTS.map((f) => (
          <option key={f.id} value={f.id} disabled={!vorhanden.includes(f.id)}>
            {f.id} — {vorhanden.includes(f.id) ? f.beschreibung : "hier nicht installiert"}
          </option>
        ))}
      </select>
      {fehlende.length > 0 && (
        <p className="text-sm text-text-3">
          Nicht jede Schrift liegt hier vor. Eine eigene, lizenzierte Schrift kannst du unter{" "}
          <Link href="/marke" className="underline underline-offset-4 hover:text-text">
            Aussehen
          </Link>{" "}
          hochladen.
        </p>
      )}
    </div>
  );
}

/* Die gewaehlte Schrift gibt es hier nicht.
 *
 * Kein Dateipfad und kein Terminalbefehl: wer diese Seite bedient, arbeitet nicht in der
 * Kommandozeile. Zwei Wege, die er selbst gehen kann: eine andere Schrift nehmen oder die eigene
 * hochladen. Solange nichts davon geschehen ist, zeigen Vorschau UND Export Inter - und das steht
 * hier, statt still zu passieren. */
function SchriftFehltHinweis({
  name,
  onInter,
  canEdit,
}: {
  name: string;
  onInter: () => void;
  canEdit: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-inner border border-attention/50 bg-attention/10 p-3">
      <p className="text-sm text-text">
        Die Schrift {name} liegt hier nicht vor. Vorschau und fertiger Clip nehmen deshalb Inter.
      </p>
      {canEdit && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onInter}
            className="transition-soft text-sm text-text underline underline-offset-4 hover:text-white"
          >
            Inter nehmen
          </button>
          <Link href="/marke" className="transition-soft text-sm text-text-2 underline underline-offset-4 hover:text-text">
            Eigene Schrift hochladen
          </Link>
        </div>
      )}
    </div>
  );
}

/* Was am eingestellten Stil nicht aufgeht, als anklickbare Liste. Ein Klick springt zur Stelle:
 * eine Warnung, die man nicht finden kann, ist nur ein schlechtes Gefuehl. */
/* Was an den eingestellten Untertiteln nicht aufgeht, mit dem Weg zur Stelle.
 *
 * Getrennt nach dem, was hier zu beheben ist (Text passt nicht in die Zeilen), und dem, was am
 * Sprechtempo haengt. Die Trennung ist der Punkt: die alte Warnung „Untertitel laufen schnell
 * durch" stand an 86 Prozent aller Einblendungen und liess sich durch keine Einstellung
 * abstellen. Eine Warnung, gegen die es nichts zu tun gibt, ist keine Warnung. */
function Befunde({
  befunde,
  onSeek,
  tempo: t,
  behebung,
  canEdit,
  onBeheben,
}: {
  befunde: Befund[];
  onSeek: (zeit: number) => void;
  tempo: { mittel: number; ueberGrenze: boolean };
  behebung: Korrektur | null;
  canEdit: boolean;
  onBeheben: (k: Korrektur) => void;
}) {
  const passtNicht = befunde.filter((b) => b.grund === "passt_nicht");
  const schnell = befunde.filter((b) => b.grund === "zu_schnell");
  if (!passtNicht.length && !schnell.length) return null;

  return (
    <section className="flex flex-col gap-4">
      {passtNicht.length > 0 && (
        <Aufgabe
          ton="achtung"
          titel={
            passtNicht.length === 1
              ? "Einen Untertitel anpassen"
              : `${passtNicht.length} Untertitel anpassen`
          }
          satz="Diese Wörter sind länger, als in die erlaubten Zeilen passt. Sie ragen dann über den sicheren Bereich hinaus."
          liste={passtNicht}
          onSeek={onSeek}
          aktion={
            behebung && canEdit
              ? { label: behebung.label, tun: () => onBeheben(behebung) }
              : null
          }
        />
      )}

      {/* Die Zahl gehört in die Überschrift. Vorher stand dort „Hier wird zügig gesprochen" und
          erst weiter unten „Stelle 1 von 27" - man sah den Umfang der Aufgabe erst, wenn man
          schon mittendrin war. */}
      {schnell.length > 0 && (
        <Aufgabe
          ton="ruhig"
          titel={
            schnell.length === 1
              ? "1 Stelle mit schnellem Sprechen"
              : `${schnell.length} Stellen mit schnellem Sprechen`
          }
          satz={
            t.ueberGrenze
              ? `Im Schnitt ${Math.round(t.mittel)} Zeichen je Sekunde, mitlesen lassen sich etwa ${MAX_CPS}. Das hängt am Sprechtempo und nicht am Aussehen: keine Einstellung hier ändert es. Wer will, kann die Stelle im Text straffen oder in der Timeline herausnehmen.`
              : "Beim Mitlesen ohne Ton könnte es hier eng werden. Straffen im Text oder Herausnehmen in der Timeline hilft."
          }
          liste={schnell}
          onSeek={onSeek}
          aktion={null}
        />
      )}
    </section>
  );
}

/* Ein Befund als Aufgabe, die man abarbeiten kann.
 *
 * Vorher standen hier drei Stellen und darunter „Und 21 weitere". Eine Zahl, die man nicht
 * erreichen kann, ist keine Aufgabe, sondern ein Vorwurf. Jetzt steht genau eine Stelle da, mit
 * „Stelle 4 von 24" und zwei Pfeilen: man arbeitet sich durch und sieht, wo man ist. Wo es eine
 * Einstellung gibt, die alle Stellen auf einmal auflöst, steht sie als Knopf daneben. */
function Aufgabe({
  ton,
  titel,
  satz,
  liste,
  onSeek,
  aktion,
}: {
  ton: "achtung" | "ruhig";
  titel: string;
  satz: string;
  liste: Befund[];
  onSeek: (zeit: number) => void;
  aktion: { label: string; tun: () => void } | null;
}) {
  const [nr, setNr] = useState(0);
  /* Wird eine Stelle behoben, schrumpft die Liste unter den Zeiger. Ohne das Nachführen stünde
   * eine leere Karte da. */
  const i = Math.min(nr, liste.length - 1);
  const b = liste[i];

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-inner border p-3",
        ton === "achtung" ? "border-attention/50 bg-attention/10" : "border-line",
      )}
    >
      <p className="text-sm font-medium text-text">{titel}</p>
      <p className="text-sm text-text-2">{satz}</p>

      <button
        type="button"
        onClick={() => onSeek(b.karte.von)}
        className="transition-soft mt-1 w-full rounded-[8px] border border-line px-3 py-2 text-left hover:border-line-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
      >
        <span className="block text-sm text-text">{`„${b.karte.text}“`}</span>
        <span className="mt-0.5 block text-xs text-text-2">{befundSatz(b)} Zum Anhören anklicken.</span>
      </button>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {liste.length > 1 ? (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              disabled={i === 0}
              onClick={() => setNr(Math.max(i - 1, 0))}
              aria-label="Vorige Stelle"
            >
              Zurück
            </Button>
            <span className="text-xs tabular-nums text-text-3">
              Stelle {i + 1} von {liste.length}
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={i >= liste.length - 1}
              onClick={() => setNr(Math.min(i + 1, liste.length - 1))}
              aria-label="Nächste Stelle"
            >
              Weiter
            </Button>
          </div>
        ) : (
          <span />
        )}
        {aktion && (
          <Button size="sm" onClick={aktion.tun}>
            {aktion.label}
          </Button>
        )}
      </div>
    </div>
  );
}

function Regler({
  label,
  wert,
  min,
  max,
  schritt = 1,
  einheit,
  onChange,
  disabled,
}: {
  label: string;
  wert: number;
  min: number;
  max: number;
  schritt?: number;
  einheit?: string;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium text-text">
          {label}
        </label>
        <span className="text-sm tabular-nums text-text-2">
          {wert}
          {einheit ? ` ${einheit}` : ""}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={schritt}
        value={wert}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-white disabled:opacity-60"
      />
    </div>
  );
}

function Farbwahl({
  label,
  wert,
  onChange,
  disabled,
}: {
  label: string;
  wert: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium text-text">
        {label}
      </label>
      <div className="flex items-center gap-3">
        <input
          id={id}
          type="color"
          value={wert}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="h-10 w-14 cursor-pointer rounded-inner border border-line bg-transparent disabled:cursor-not-allowed disabled:opacity-60"
        />
        <span className="text-sm text-text-2">{wert}</span>
      </div>
    </div>
  );
}
