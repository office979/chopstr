"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Toggle } from "@/components/ui/Toggle";
import { cn } from "@/components/ui/cn";
import type { TranscriptWord } from "@/lib/repo/types";
import {
  aktiverLook,
  FONTS,
  GRENZEN,
  HIGHLIGHT_FARBEN,
  LOOKS,
  type CaptionStyle,
  type Look,
  maxZeichen,
  mitVorgabe,
} from "@/lib/clips/caption-style";

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

/* Wörter in Einblendungen gruppieren.
 *
 * Bei einer festen Wortzahl ist das genau, was der Renderer tut (captions_de.build_cards). Ohne
 * feste Wortzahl gruppiert der Renderer nach Sinn, mit Silbentrennung und Sperrwörtern; das hier
 * ist dann eine Näherung über das Zeichenbudget. Sie zeigt die Größenverhältnisse richtig, die
 * Schnittstellen zwischen den Karten können abweichen. */
function karten(woerter: TranscriptWord[], proKarte: number | undefined, budget: number): TranscriptWord[][] {
  if (proKarte && proKarte > 0) {
    const aus: TranscriptWord[][] = [];
    for (let i = 0; i < woerter.length; i += proKarte) aus.push(woerter.slice(i, i + proKarte));
    return aus;
  }
  const aus: TranscriptWord[][] = [];
  let lauf: TranscriptWord[] = [];
  let laenge = 0;
  for (const w of woerter) {
    const n = w.text.length + 1;
    if (lauf.length && laenge + n > budget) {
      aus.push(lauf);
      lauf = [];
      laenge = 0;
    }
    lauf.push(w);
    laenge += n;
  }
  if (lauf.length) aus.push(lauf);
  return aus;
}

interface VorschauProps {
  stil: CaptionStyle;
  woerter: TranscriptWord[];
  /* Stelle im ganzen Video, an der der Player gerade steht. */
  zeit: number;
}

/* Die Untertitel, wie sie im fertigen Clip stehen, über das laufende Bild gelegt.
 *
 * Gerechnet wird in Bildpunkten bei 1080x1920 und mit Containereinheiten ausgegeben, damit die
 * Vorschau in jeder Größe stimmt: 1 cqw ist ein Hundertstel der Breite des Videos. So braucht es
 * keinen Messcode, der bei jeder Fenstergröße neu laufen müsste. */
export function CaptionVorschau({ stil, woerter, zeit }: VorschauProps) {
  const s = mitVorgabe(stil);
  const safeUnten = SAFE_UNTEN[stil.preset ?? ""] ?? 1600;
  const budget = maxZeichen(s.font_px) * s.max_lines;
  const gruppen = useMemo(() => karten(woerter, s.words_per_card, budget), [woerter, s.words_per_card, budget]);

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

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" style={{ containerType: "inline-size" }}>
      <div
        className="absolute flex justify-center text-center"
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
              ? `0 0 ${(s.outline_px / BILD_B) * 100}cqw #000, ${(s.outline_px / BILD_B) * 60}cqw 0 #000, -${(s.outline_px / BILD_B) * 60}cqw 0 #000, 0 ${(s.outline_px / BILD_B) * 60}cqw #000, 0 -${(s.outline_px / BILD_B) * 60}cqw #000`
              : "none",
            background: s.box ? "rgba(0,0,0,0.55)" : "transparent",
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
  laengstesWort: string;
  canEdit: boolean;
  gespeichert: boolean;
  speichern: () => void;
  zuruecksetzen: () => void;
  saving: boolean;
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
  laengstesWort,
  canEdit,
  gespeichert,
  speichern,
  zuruecksetzen,
  saving,
}: StudioProps) {
  const s = mitVorgabe(stil);
  const [mehr, setMehr] = useState(false);
  const [vorlageName, setVorlageName] = useState("");
  const [vorlageMeldung, setVorlageMeldung] = useState<string | null>(null);
  const [fehlendeSchrift, setFehlendeSchrift] = useState(false);
  const idWoerter = useId();
  const idGroesse = useId();
  const look = aktiverLook(stil);

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

  /* Ob die gewählte Schrift im Browser überhaupt vorliegt. Tut sie es nicht, zeigt die Vorschau
   * Inter, und das muss dastehen statt den Nutzer raten zu lassen.
   *
   * Der naheliegende Weg über document.fonts.check() taugt dafür nicht: der gibt auch für eine
   * Schrift true zurück, die es gar nicht gibt, weil der Browser den Text ja mit der Ersatzschrift
   * darstellen kann. An „Anton" geprüft: kam true, obwohl keine Datei vorlag.
   *
   * Deshalb gemessen: derselbe Text einmal mit der gesuchten Schrift vor einer Ersatzschrift und
   * einmal nur mit der Ersatzschrift. Sind beide Breiten gleich, wurde sie nicht verwendet. */
  useEffect(() => {
    let abgebrochen = false;
    const pruefen = async () => {
      try {
        await document.fonts.ready;
        const ctx = document.createElement("canvas").getContext("2d");
        if (!ctx) return;
        const probe = "HAMBURGEFONSTIV hamburgefonstiv 0123456789";
        const vorhanden = ["monospace", "serif"].some((ersatz) => {
          ctx.font = `700 48px ${ersatz}`;
          const ohne = ctx.measureText(probe).width;
          ctx.font = `700 48px "${s.font}", ${ersatz}`;
          return Math.abs(ctx.measureText(probe).width - ohne) > 0.5;
        });
        if (!abgebrochen) setFehlendeSchrift(!vorhanden);
      } catch {
        /* Im Zweifel nichts behaupten: eine falsche Warnung ist schlimmer als keine. */
        if (!abgebrochen) setFehlendeSchrift(false);
      }
    };
    void pruefen();
    return () => {
      abgebrochen = true;
    };
  }, [s.font]);

  const zeichenGrenze = maxZeichen(s.font_px);
  /* Gewarnt wird erst, wenn auch die Silbentrennung nicht mehr hilft. Der Renderer trennt lange
   * Komposita an der Morphemgrenze (captions_de.hyphenate); ein Wort, das knapp ueber die Zeile
   * geht, wird also sauber umbrochen. Beim ersten Versuch stand die Warnung schon im
   * Ausgangszustand da, also bevor jemand etwas eingestellt hatte, und das Werkzeug beschwerte
   * sich ueber sich selbst. */
  const zuLang = laengstesWort.length > zeichenGrenze * 1.6;

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
        <p className="text-sm text-text-2">Wirkt beim nächsten Render</p>
      </div>

      <div className="mt-5 flex flex-col gap-6">
        {/* 1. Wie soll es aussehen? Vier Karten, eine Berührung. */}
        <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {LOOKS.map((l) => (
            <button
              key={l.id}
              type="button"
              disabled={!canEdit}
              onClick={() => setzen(l.stil)}
              aria-pressed={look === l.id}
              className={cn(
                "transition-soft flex flex-col items-center gap-2 rounded-inner border p-3 disabled:opacity-60",
                look === l.id ? "border-white/60 bg-white/10" : "border-line hover:border-line-strong",
              )}
            >
              <LookProbe look={l} />
              <span className={cn("text-sm font-medium", look === l.id ? "text-text" : "text-text-2")}>{l.name}</span>
              <span className="text-center text-xs text-text-3">{l.hinweis}</span>
            </button>
          ))}
        </section>

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
          {zuLang && (
            <p className="text-sm text-attention">
              „{laengstesWort}&ldquo; passt so nicht in eine Zeile. Kleiner stellen oder mehr Zeilen erlauben.
            </p>
          )}
        </section>

        {/* 4. Farbe der Hervorhebung */}
        {s.highlight_words && (
          <section className="flex flex-col gap-2">
            <p className="text-sm font-medium text-text">Farbe des gesprochenen Worts</p>
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
          </section>
        )}

        {fehlendeSchrift && (
          <p className="text-sm text-attention">
            Die Schrift dieses Looks liegt in deinem Browser nicht vor, die Vorschau zeigt Inter. Im fertigen Clip wird
            sie verwendet, sobald die Datei im Schriftordner des Workers liegt.
          </p>
        )}

        {/* 5. Vorlagen */}
        {(vorlagen.length > 0 || canEdit) && (
          <section className="flex flex-col gap-2 border-t border-line pt-5">
            <p className="text-sm font-medium text-text">Vorlagen</p>
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
                  Merken
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
          {mehr ? "Weniger einstellen" : "Mehr einstellen"}
        </button>

        {mehr && (
          <section className="flex flex-col gap-4 border-t border-line pt-5">
            <Schriftwahl wert={s.font} disabled={!canEdit} onChange={(v) => setzen({ font: v })} />
            <Farbwahl label="Textfarbe" wert={s.base_color} disabled={!canEdit} onChange={(v) => setzen({ base_color: v })} />
            <Toggle checked={s.bold} disabled={!canEdit} onChange={(v) => setzen({ bold: v })} label="Fett" />
            <Toggle checked={s.all_caps} disabled={!canEdit} onChange={(v) => setzen({ all_caps: v })} label="Großbuchstaben" />
            <Toggle
              checked={s.highlight_words}
              disabled={!canEdit}
              onChange={(v) => setzen({ highlight_words: v })}
              label="Gesprochenes Wort hervorheben"
            />
            <Toggle checked={s.box} disabled={!canEdit} onChange={(v) => setzen({ box: v })} label="Kasten hinter dem Text" />
            <Regler
              label="Kontur"
              einheit="px"
              wert={s.outline_px}
              min={GRENZEN.outline_px[0]}
              max={GRENZEN.outline_px[1]}
              disabled={!canEdit}
              onChange={(v) => setzen({ outline_px: v })}
            />
            <Regler
              label="Höhe im Bild"
              einheit="px über der Kante"
              wert={s.bottom_margin_px}
              min={GRENZEN.bottom_margin_px[0]}
              max={GRENZEN.bottom_margin_px[1]}
              schritt={10}
              disabled={!canEdit}
              onChange={(v) => setzen({ bottom_margin_px: v })}
            />
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
              {saving ? "Wird gespeichert" : gespeichert ? "Gespeichert" : "Untertitel speichern"}
            </Button>
          </div>
        )}
      </div>
    </GlassCard>
  );
}

/* Eine kleine Probe des Looks: das Wort „Aa" so gesetzt, wie die Untertitel aussehen werden.
 * Ein Bild sagt hier mehr als der Name der Schrift. */
function LookProbe({ look }: { look: Look }) {
  const v = mitVorgabe(look.stil);
  return (
    <span
      aria-hidden="true"
      className="flex h-10 w-full items-center justify-center overflow-hidden rounded-[6px] bg-black/60"
      style={{
        fontFamily: `"${v.font}", "Inter", system-ui, sans-serif`,
        fontWeight: v.bold ? 800 : 500,
        color: v.base_color,
        textTransform: v.all_caps ? "uppercase" : "none",
        fontSize: 17,
        letterSpacing: v.all_caps ? "0.02em" : undefined,
      }}
    >
      <span
        style={{
          background: v.box ? "rgba(0,0,0,0.6)" : "transparent",
          padding: v.box ? "2px 6px" : 0,
          borderRadius: v.box ? 3 : 0,
          textShadow: v.outline_px ? `0 0 ${Math.max(1, v.outline_px / 3)}px #000, 0 1px 2px #000` : "none",
        }}
      >
        Wort <span style={{ color: v.highlight_words ? v.highlight_color : v.base_color }}>Wort</span>
      </span>
    </span>
  );
}

function Schriftwahl({ wert, onChange, disabled }: { wert: string; onChange: (v: string) => void; disabled?: boolean }) {
  const id = useId();
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
          <option key={f.id} value={f.id}>
            {f.id} — {f.beschreibung}
          </option>
        ))}
      </select>
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
