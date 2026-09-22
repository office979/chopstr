"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import type { Aspect, CaptionCard, CaptionPreset } from "@/lib/repo/types";
import { layoutFor, presetFor } from "@/lib/clips/presets";
import { cardAt } from "@/lib/clips/captions";
import { formatTimecode } from "@/lib/format";

interface Props {
  aspect: Aspect;
  preset: CaptionPreset | string;
  durationS: number;
  cards: CaptionCard[];
  /* On-Screen-Hook in den ersten 3 s (null = kein Overlay) */
  hookText: string | null;
  /* Titelkarte 2,5 s oben */
  titleCard: string | null;
  highlightColor?: string;
  lowerThird?: { name: string; role: string } | null;
  /* Marken-Font aus dem CI-Manager (Block B): per @font-face aus der Medien-URL geladen */
  font?: PreviewFont | null;
  className?: string;
}

export interface PreviewFont {
  family: string;
  url: string;
  format: string;
  weight?: number | null;
}

export function fontFaceCss(font: PreviewFont): string {
  const family = font.family.replace(/["\\]/g, "");
  return `@font-face{font-family:"${family}";src:url("${font.url}") format("${font.format}");font-weight:${font.weight ?? 400};font-display:swap;}`;
}

export const HOOK_OVERLAY_SECONDS = 3;
export const TITLE_CARD_SECONDS = 2.5;
const LOWER_THIRD_SECONDS = 4;

/* Stumme CSS-Vorschau des Ausgabeformats: Safe Zones als Haarlinien, Caption-Karten im Preset-Stil an der
 * Baseline, On-Screen-Hook und Titelkarte oben. Maße kommen aus lib/clips/presets (Spiegel des Workers),
 * alle Größen skalieren über Container-Query-Einheiten mit dem Rahmen. Ersetzt keinen Render. */
export function SilentPreview({ aspect, preset: presetName, durationS, cards, hookText, titleCard, highlightColor, lowerThird, font, className }: Props) {
  const preset = presetFor(presetName);
  const layout = layoutFor(preset, aspect);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const tRef = useRef(0);
  const sliderId = useId();
  const duration = Math.max(0.1, durationS);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      return;
    }
    lastRef.current = performance.now();
    const tick = (now: number) => {
      const delta = (now - lastRef.current) / 1000;
      lastRef.current = now;
      const next = tRef.current + delta;
      if (next >= duration) {
        tRef.current = duration;
        setT(duration);
        setPlaying(false);
        return;
      }
      tRef.current = next;
      setT(next);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, duration]);

  const toggle = () => {
    if (!playing && tRef.current >= duration - 0.01) {
      tRef.current = 0;
      setT(0);
    }
    setPlaying((p) => !p);
  };

  const pct = (px: number, total: number) => `${(px / total) * 100}%`;
  const cq = (px: number) => `${(px / layout.width) * 100}cqw`;
  const card = cardAt(cards, t);
  const showHook = Boolean(hookText) && t < HOOK_OVERLAY_SECONDS;
  const showTitle = Boolean(titleCard) && t < TITLE_CARD_SECONDS;
  const showLowerThird = Boolean(lowerThird?.name) && t >= 0.6 && t < LOWER_THIRD_SECONDS;
  const highlight = highlightColor ?? "#ffd700";
  const bold = preset.bold;
  const boxed = preset.box;

  const renderLine = (line: string, keyword?: string) => {
    const words = line.split(" ");
    return words.map((w, i) => {
      const isKey = keyword != null && w.replace(/[.,!?;:]/g, "") === keyword;
      return (
        <span
          key={`${w}-${i}`}
          className={cn(isKey && preset.animated && "silent-caption-pop")}
          style={
            isKey
              ? preset.highlight_words
                ? { color: highlight }
                : { fontWeight: 700 }
              : undefined
          }
        >
          {w}
          {i < words.length - 1 ? " " : ""}
        </span>
      );
    });
  };

  const fontFamily = font ? `"${font.family.replace(/["\\]/g, "")}", Inter, sans-serif` : undefined;

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {font && <style>{fontFaceCss(font)}</style>}
      <div
        className="relative mx-auto w-full max-w-[300px] overflow-hidden rounded-inner border border-line-strong bg-black"
        style={{ aspectRatio: `${layout.width} / ${layout.height}`, containerType: "inline-size", fontFamily }}
        role="img"
        aria-label={`Stumme Vorschau ${aspect}, Sekunde ${t.toFixed(1)} von ${duration.toFixed(1)}`}
      >
        {/* Bildplatzhalter: neutraler Crop */}
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at 50% 38%, rgba(91,140,255,0.28) 0%, rgba(27,26,98,0.35) 38%, rgba(0,0,0,0) 72%), linear-gradient(180deg, #0a0a13, #000)",
          }}
        />
        <div
          aria-hidden="true"
          className="absolute left-1/2 -translate-x-1/2 rounded-full border border-white/10"
          style={{ top: "26%", width: "34%", aspectRatio: "1 / 1.25", background: "rgba(244,245,254,0.06)" }}
        />

        {/* Safe Zones als Haarlinien */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <span className="absolute left-0 right-0 border-t border-dashed border-white/25" style={{ top: pct(layout.safe.top, layout.height) }} />
          <span className="absolute left-0 right-0 border-t border-dashed border-white/25" style={{ top: pct(layout.safe.bottom, layout.height) }} />
          <span className="absolute bottom-0 top-0 border-l border-dashed border-white/25" style={{ left: pct(layout.safe.left, layout.width) }} />
          <span className="absolute bottom-0 top-0 border-l border-dashed border-white/25" style={{ left: pct(layout.safe.right, layout.width) }} />
          <span
            className="absolute left-0 right-0 border-t border-dotted border-ai-soft/60"
            style={{ top: pct(layout.baseline_y, layout.height) }}
          />
        </div>

        {/* Titelkarte und On-Screen-Hook oben, innerhalb der Safe Zone */}
        <div
          className="absolute flex flex-col items-center gap-[2cqw]"
          style={{
            top: pct(layout.safe.top + 24, layout.height),
            left: pct(layout.safe.left, layout.width),
            right: pct(layout.width - layout.safe.right, layout.width),
          }}
        >
          {showTitle && (
            <p
              className="w-full rounded-[2cqw] bg-black/70 px-[4cqw] py-[2.5cqw] text-center font-medium leading-tight text-white"
              style={{ fontSize: cq(Math.round(layout.font_px * 0.9)) }}
            >
              {titleCard}
            </p>
          )}
          {showHook && (
            <p
              className="line-clamp-2 w-full rounded-[2cqw] bg-white px-[4cqw] py-[3cqw] text-center font-semibold leading-tight text-black [overflow-wrap:anywhere]"
              style={{ fontSize: cq(Math.round(layout.font_px * 0.82)) }}
            >
              {hookText}
            </p>
          )}
        </div>

        {/* Bauchbinde */}
        {showLowerThird && lowerThird && (
          <div
            className="absolute rounded-[1.5cqw] bg-white/90 px-[3cqw] py-[1.5cqw] text-black"
            style={{ left: pct(layout.safe.left, layout.width), top: pct(layout.baseline_y - layout.font_px * 5.5, layout.height), fontSize: cq(Math.round(layout.font_px * 0.62)) }}
          >
            <span className="block font-semibold">{lowerThird.name}</span>
            {lowerThird.role && <span className="block opacity-80">{lowerThird.role}</span>}
          </div>
        )}

        {/* Caption-Karte an der Baseline */}
        {card && (
          <div
            key={`${card.start}-${card.end}`}
            className={cn("absolute flex -translate-y-full flex-col items-center text-center", preset.animated && "silent-card-in")}
            style={{
              top: pct(layout.baseline_y, layout.height),
              left: pct(layout.safe.left, layout.width),
              right: pct(layout.width - layout.safe.right, layout.width),
            }}
          >
            <div
              className={cn("leading-[1.15] text-white", boxed && "rounded-[1.5cqw] bg-black/75 px-[3cqw] py-[2cqw]")}
              style={{
                fontSize: cq(layout.font_px),
                fontWeight: bold ? 800 : 400,
                textShadow: preset.outline_px > 0 ? `0 0 ${cq(preset.outline_px)} #000, 0 0 ${cq(preset.outline_px * 2)} #000` : undefined,
              }}
            >
              {card.lines.map((line, i) => (
                <span key={i} className="block">
                  {renderLine(line, card.keyword)}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="mx-auto flex w-full max-w-[300px] items-center gap-3">
        <Button size="sm" variant="ghost" onClick={toggle} aria-pressed={playing} aria-label={playing ? "Pause" : "Abspielen ohne Ton"}>
          {playing ? "Pause" : "Play"}
        </Button>
        <label htmlFor={sliderId} className="sr-only">
          Position in Sekunden
        </label>
        <input
          id={sliderId}
          type="range"
          className="timeline flex-1"
          min={0}
          max={duration}
          step={0.05}
          value={Math.min(t, duration)}
          onChange={(e) => {
            const v = Number(e.target.value);
            tRef.current = v;
            setT(v);
          }}
          style={{ ["--progress" as string]: `${(Math.min(t, duration) / duration) * 100}%` }}
        />
        <span className="font-mono text-xs tabular-nums text-text-2">
          {formatTimecode(t)} / {formatTimecode(duration)}
        </span>
      </div>
      <p className="text-center text-xs text-text-3">
        Stumme Vorschau ersetzt keinen Render.{font ? ` Font: ${font.family}.` : ""}
      </p>
    </div>
  );
}
