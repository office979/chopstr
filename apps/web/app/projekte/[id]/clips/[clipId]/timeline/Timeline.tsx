"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import {
  abschnittBei,
  anfangKuerzen,
  dauer as schnittDauer,
  endeKuerzen,
  entfernen,
  istSichtbar,
  randSetzen,
  teilen,
  type Schnitt,
} from "@/lib/clips/schnitt";
import type { RenderShot, Zeitmarke } from "@/lib/repo/types";
import { Lineal, timecode } from "./Lineal";
import { Wellenform, type WellenformDaten } from "./Wellenform";

interface Props {
  /* Der volle Zeitraum, den die Leiste zeigen kann: der Clip plus etwas Luft davor und danach,
   * damit sich der Anfang auch wieder verlaengern laesst. */
  bereichVonS: number;
  bereichBisS: number;
  schnitt: Schnitt;
  onSchnitt: (neu: Schnitt, was: string) => void;
  /* Waehrend an einer Kante gezogen wird. Getrennt von onSchnitt, weil ein Zug Dutzende
   * Ereignisse liefert und der Verlauf davon nur EINEN Schritt sehen soll. */
  onZiehen: (neu: Schnitt) => void;
  onZiehenFertig: () => void;
  quelleDauerS: number;
  /* Wo der Player steht, in Quellzeit. */
  zeit: number;
  onSeek: (quellzeit: number) => void;
  laeuft: boolean;
  onPlayPause: () => void;
  wellenform: WellenformDaten | null;
  filmstreifen: string[];
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  onMarkeWeg: (abS: number) => void;
  onMarkeVerschieben: (vonS: number, nachS: number) => void;
  markeBeschriftung: (m: Zeitmarke | null) => string;
  canEdit: boolean;
  kannZurueck: boolean;
  kannVor: boolean;
  onZurueck: () => void;
  onVor: () => void;
}

const SPUR_HOEHE = 64;
const MAX_LUPE = 24;

/* Die Timeline: Bild, Ton, Schnitt und Bildausschnitt auf einer Zeitskala.
 *
 * Alles rechnet in QUELLZEIT. Die Zeit im fertigen Clip ist eine Ableitung davon (siehe
 * lib/clips/schnitt.ts) und steht nur als Anzeige daneben. Andersherum waere jede Kante eine
 * Umrechnung, und beim Verschieben einer Kante aenderte sich die Skala unter der Hand. */
export function Timeline({
  bereichVonS,
  bereichBisS,
  schnitt,
  onSchnitt,
  onZiehen,
  onZiehenFertig,
  quelleDauerS,
  zeit,
  onSeek,
  laeuft,
  onPlayPause,
  wellenform,
  filmstreifen,
  shots,
  zeitmarken,
  onMarkeWeg,
  onMarkeVerschieben,
  markeBeschriftung,
  canEdit,
  kannZurueck,
  kannVor,
  onZurueck,
  onVor,
}: Props) {
  const spurRef = useRef<HTMLDivElement | null>(null);
  const rahmenRef = useRef<HTMLDivElement | null>(null);
  const [lupe, setLupe] = useState(1);
  const [breite, setBreite] = useState(0);
  const [gewaehlt, setGewaehlt] = useState<number | null>(null);
  const [eingabe, setEingabe] = useState("");

  const gesamt = Math.max(0.1, bereichBisS - bereichVonS);
  const sichtbar = gesamt / lupe;

  useEffect(() => {
    const el = rahmenRef.current;
    if (!el) return undefined;
    const messen = () => setBreite(el.clientWidth);
    messen();
    const b = new ResizeObserver(messen);
    b.observe(el);
    return () => b.disconnect();
  }, []);

  /* Das sichtbare Fenster folgt dem Abspielkopf, damit er beim Vergroessern nicht aus dem Bild
   * laeuft. Ohne das muesste man nach jedem Zoomschritt von Hand scrollen. */
  const fensterVon = useMemo(() => {
    if (lupe <= 1) return bereichVonS;
    const mitte = zeit - sichtbar / 2;
    return Math.max(bereichVonS, Math.min(mitte, bereichBisS - sichtbar));
  }, [lupe, zeit, sichtbar, bereichVonS, bereichBisS]);
  const fensterBis = fensterVon + sichtbar;

  const anteil = useCallback((t: number) => (t - fensterVon) / sichtbar, [fensterVon, sichtbar]);
  const ausX = useCallback(
    (clientX: number) => {
      const el = spurRef.current;
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const p = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      return fensterVon + p * sichtbar;
    },
    [fensterVon, sichtbar],
  );

  /* Ziehen: am Fenster mitlesen, beim Loslassen abmelden. Ein Griff meldet sich mit einer
   * eigenen Behandlung, damit das Ziehen an einer Kante nicht zugleich den Kopf setzt. */
  const ziehen = useCallback(
    (bewegen: (t: number) => void, fertig?: () => void) => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const los = (ev: PointerEvent) => {
        const t = ausX(ev.clientX);
        if (t != null) bewegen(t);
      };
      const ende = () => {
        window.removeEventListener("pointermove", los);
        window.removeEventListener("pointerup", ende);
        fertig?.();
      };
      window.addEventListener("pointermove", los);
      window.addEventListener("pointerup", ende);
      const t = ausX(e.clientX);
      if (t != null) bewegen(t);
    },
    [ausX],
  );

  /* Einen Marker verschieben. Marker liegen in QUELLZEIT, genau wie alles andere in der Leiste:
   * ein Marker zeigt auf eine Stelle im Video und soll dort bleiben, auch wenn davor etwas
   * weggeschnitten wird. Gespeichert wird erst beim Loslassen, nicht bei jeder Mausbewegung. */
  const markeZiehen = useCallback(
    (marke: Zeitmarke) => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      let letzte = marke.ab_s;
      const los = (ev: PointerEvent) => {
        const t = ausX(ev.clientX);
        if (t != null) letzte = Math.max(0, t);
      };
      const ende = () => {
        window.removeEventListener("pointermove", los);
        window.removeEventListener("pointerup", ende);
        if (Math.abs(letzte - marke.ab_s) > 0.05) onMarkeVerschieben(marke.ab_s, letzte);
      };
      window.addEventListener("pointermove", los);
      window.addEventListener("pointerup", ende);
    },
    [ausX, onMarkeVerschieben],
  );

  const imClip = useMemo(() => {
    let vorher = 0;
    for (const a of schnitt) {
      if (zeit < a.start) return vorher;
      if (zeit <= a.end) return vorher + (zeit - a.start);
      vorher += a.end - a.start;
    }
    return vorher;
  }, [schnitt, zeit]);

  const dauerGesamt = schnittDauer(schnitt);
  const iHier = abschnittBei(schnitt, zeit);
  const kannTeilen = canEdit && iHier >= 0 && teilen(schnitt, zeit) !== schnitt;
  const kannEntfernen = canEdit && gewaehlt != null && schnitt.length > 1;

  const tastatur = (e: React.KeyboardEvent) => {
    const fein = e.shiftKey ? 1 : e.altKey ? 0.04 : 0.2;
    if (e.key === " ") {
      e.preventDefault();
      onPlayPause();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      onSeek(Math.max(bereichVonS, zeit - fein));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      onSeek(Math.min(bereichBisS, zeit + fein));
    } else if (e.key === "Home") {
      e.preventDefault();
      onSeek(schnitt[0]?.start ?? bereichVonS);
    } else if (e.key === "End") {
      e.preventDefault();
      onSeek(schnitt[schnitt.length - 1]?.end ?? bereichBisS);
    }
  };

  const springeZu = () => {
    const teile = eingabe.trim().replace(",", ".").split(":");
    const sek = teile.length === 2 ? Number(teile[0]) * 60 + Number(teile[1]) : Number(teile[0]);
    if (Number.isFinite(sek)) onSeek(Math.max(bereichVonS, Math.min(bereichBisS, sek)));
  };

  return (
    <GlassCard padding="md">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold">Timeline</h2>
          <span className="text-sm text-text-2">
            Clip <span className="tabular-nums">{timecode(dauerGesamt, true)}</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-inner border border-line px-2.5 py-1 text-sm tabular-nums text-text">
            {timecode(imClip, true)}
          </span>
          <label className="flex items-center gap-1.5 text-sm text-text-2">
            <span className="sr-only">Zu Zeitpunkt springen</span>
            <input
              value={eingabe}
              onChange={(e) => setEingabe(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  springeZu();
                }
              }}
              placeholder="0:12"
              aria-label="Zeitpunkt in der Quelle, zum Beispiel 0:12"
              className="transition-soft w-[86px] rounded-inner border border-line bg-black/40 px-2.5 py-1.5 text-sm tabular-nums text-text placeholder:text-text-3 focus:border-white/50 focus:outline-none"
            />
            <Button variant="ghost" size="sm" onClick={springeZu}>
              Springen
            </Button>
          </label>
        </div>
      </div>

      {/* Steuerung: abspielen, Lupe, ganzes Video */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onPlayPause} aria-label={laeuft ? "Anhalten" : "Abspielen"}>
          {laeuft ? "Pause" : "Abspielen"}
        </Button>
        <div className="flex items-center gap-1">
          <Werkzeug titel="Verkleinern" onClick={() => setLupe((l) => Math.max(1, l / 1.6))} disabled={lupe <= 1}>
            −
          </Werkzeug>
          <span className="w-[52px] text-center text-sm tabular-nums text-text-2">{lupe.toFixed(1)}×</span>
          <Werkzeug titel="Vergrößern" onClick={() => setLupe((l) => Math.min(MAX_LUPE, l * 1.6))} disabled={lupe >= MAX_LUPE}>
            +
          </Werkzeug>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setLupe(1)} disabled={lupe === 1}>
          Ganzes Video zeigen
        </Button>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden="true" />
        <Button variant="ghost" size="sm" onClick={onZurueck} disabled={!kannZurueck}>
          Rückgängig
        </Button>
        <Button variant="ghost" size="sm" onClick={onVor} disabled={!kannVor}>
          Wiederherstellen
        </Button>
      </div>

      {/* Die Spuren */}
      <div
        ref={rahmenRef}
        tabIndex={0}
        onKeyDown={tastatur}
        role="group"
        aria-label="Timeline, mit Pfeiltasten bewegen, Leertaste spielt ab"
        className="transition-soft mt-4 flex gap-2 rounded-inner border border-line p-2 focus:border-white/50 focus:outline-none"
      >
        {/* Die Namen der Spuren. Ohne sie stehen hier vier Streifen uebereinander und niemand
          * weiss, welcher wofuer da ist. Die Hoehen stimmen mit den Spuren rechts ueberein. */}
        <div className="hidden w-[104px] shrink-0 flex-col pt-5 text-xs text-text-2 sm:flex">
          <Name hoehe={SPUR_HOEHE}>Bild</Name>
          <Name hoehe={44} oben>Ton</Name>
          <Name hoehe={36} oben>Schnitt</Name>
          <Name hoehe={36} oben>Bildausschnitt</Name>
        </div>

        <div className="min-w-0 flex-1">
        <Lineal vonS={fensterVon} bisS={fensterBis} breitePx={breite} />

        <div
          ref={spurRef}
          onPointerDown={ziehen((t) => onSeek(t))}
          className="relative w-full cursor-pointer touch-none select-none"
        >
          {/* Bild */}
          <div className="relative h-[64px] w-full overflow-hidden rounded-[6px] bg-black/50" style={{ height: SPUR_HOEHE }}>
            {/* Immer aus der Quelle gezeichnet und nie der gebaute Streifen: der zeigt den
              * FERTIGEN Clip, also die Abschnitte aneinandergehaengt. Ueber die Zeitskala hier
              * gelegt saessen seine Bilder an den falschen Stellen. */}
            {filmstreifen.length > 0 ? (
              <div className="pointer-events-none flex h-full w-full">
                {filmstreifen.map((b, i) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={i} src={b} alt="" draggable={false} className="h-full flex-1 object-cover" style={{ minWidth: 0 }} />
                ))}
              </div>
            ) : (
              <span className="flex h-full items-center justify-center text-xs text-text-3">Einzelbilder werden geholt</span>
            )}

            {/* Wo die Automatik den Bildausschnitt wechselt. Ein duenner Strich reicht: er sagt,
              * warum das Bild an dieser Stelle springt, und laedt zum Setzen einer Marke ein. */}
            {shots.slice(1).map((sh) => (
              <div
                key={sh.start}
                className="pointer-events-none absolute top-0 h-full w-px bg-white/45"
                style={{ left: `${anteil(sh.start) * 100}%` }}
              />
            ))}

            {/* Was weggeschnitten ist, liegt unter einem Schleier. Der Clip ist das Helle. */}
            {luecken(schnitt, bereichVonS, bereichBisS).map((l) => (
              <div
                key={`${l.von}-${l.bis}`}
                className="pointer-events-none absolute top-0 h-full bg-black/70"
                style={{ left: `${anteil(l.von) * 100}%`, width: `${((l.bis - l.von) / sichtbar) * 100}%` }}
              />
            ))}
          </div>

          {/* Ton */}
          <div className="mt-1 w-full overflow-hidden rounded-[6px] bg-black/40">
            <Wellenform daten={wellenform} vonS={fensterVon} bisS={fensterBis} />
          </div>

          {/* Schnitt: Abschnitte mit Griffen */}
          <div className="relative mt-1 h-9 w-full">
            {schnitt.map((a, i) => (
              <div
                key={`${a.start}-${i}`}
                className={cn(
                  "absolute top-0 h-full rounded-[6px] border",
                  gewaehlt === i ? "border-white/70 bg-white/15" : "border-line bg-white/5",
                )}
                style={{ left: `${anteil(a.start) * 100}%`, width: `${((a.end - a.start) / sichtbar) * 100}%` }}
              >
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => setGewaehlt(gewaehlt === i ? null : i)}
                  aria-pressed={gewaehlt === i}
                  aria-label={`Abschnitt ${i + 1}, ${timecode(a.start)} bis ${timecode(a.end)}`}
                  className="absolute inset-0 px-3 text-left text-xs tabular-nums text-text-2 focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
                >
                  <span className="truncate">{timecode(a.end - a.start, true)}</span>
                </button>
                {canEdit && (
                  <>
                    <Griff
                      seite="links"
                      onPointer={ziehen((t) => onZiehen(randSetzen(schnitt, i, 0, t, quelleDauerS)), onZiehenFertig)}
                    />
                    <Griff
                      seite="rechts"
                      onPointer={ziehen((t) => onZiehen(randSetzen(schnitt, i, 1, t, quelleDauerS)), onZiehenFertig)}
                    />
                  </>
                )}
              </div>
            ))}
          </div>

          {/* Bildausschnitt: eine eigene, beschriftete Spur */}
          <div className="relative mt-1 h-9 w-full rounded-[6px] bg-black/25">
            {marken_abschnitte(zeitmarken, schnitt).map((m) => (
              <div
                key={`${m.vonQuelle}-${m.bisQuelle}`}
                /* Der ganze Block laesst sich fassen, nicht nur der schmale Griff: ein Ziel von
                 * zwoelf Bildpunkten trifft man nicht zuverlaessig. */
                onPointerDown={m.marke && canEdit ? markeZiehen(m.marke) : undefined}
                className={cn(
                  "absolute top-0 flex h-full items-center overflow-hidden rounded-[6px] border px-2",
                  m.marke ? "border-attention/70 bg-attention/15" : "border-dashed border-line",
                  m.marke && canEdit && "cursor-ew-resize",
                )}
                style={{ left: `${anteil(m.vonQuelle) * 100}%`, width: `${((m.bisQuelle - m.vonQuelle) / sichtbar) * 100}%` }}
                title={`${timecode(m.vonQuelle)}: ${markeBeschriftung(m.marke)}`}
              >
                <span className="truncate pl-3 text-xs text-text-2">{markeBeschriftung(m.marke)}</span>
                {m.marke && canEdit && (
                  <>
                    <button
                      type="button"
                      onPointerDown={markeZiehen(m.marke)}
                      onKeyDown={(e) => {
                        /* Dasselbe mit der Tastatur, denn Ziehen ist nicht fuer jeden zu bedienen. */
                        const schritt = e.shiftKey ? 1 : 0.2;
                        const ziel = m.marke!.ab_s + (e.key === "ArrowLeft" ? -schritt : e.key === "ArrowRight" ? schritt : 0);
                        if (ziel === m.marke!.ab_s) return;
                        e.preventDefault();
                        /* Sonst wanderte mit derselben Taste auch der Abspielkopf. */
                        e.stopPropagation();
                        onMarkeVerschieben(m.marke!.ab_s, Math.max(0, Math.round(ziel * 100) / 100));
                      }}
                      aria-label={`Marker bei ${timecode(m.vonQuelle)} verschieben, mit Pfeiltasten oder Ziehen`}
                      className="absolute left-0 top-0 h-full w-4 cursor-ew-resize focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
                    >
                      <span className="mx-auto block h-full w-[3px] bg-attention" />
                    </button>
                    <button
                      type="button"
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={() => onMarkeWeg(m.marke!.ab_s)}
                      aria-label={`Marker bei ${timecode(m.vonQuelle)} entfernen`}
                      className="transition-soft absolute right-0.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-text-3 hover:bg-white/10 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
                    >
                      <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                        <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                      </svg>
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>

          {/* Der Abspielkopf über allem */}
          <div
            className="pointer-events-none absolute top-0 z-10 h-full w-[2px] bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.7)]"
            style={{ left: `${anteil(zeit) * 100}%` }}
          >
            <span className="absolute -left-[6px] -top-1 h-3.5 w-3.5 rounded-full border-2 border-black/70 bg-white" />
          </div>
        </div>

        <div className="mt-2 flex items-center justify-between text-xs text-text-3">
          <span className="tabular-nums">{timecode(fensterVon)}</span>
          <span>{lupe > 1 ? "Ausschnitt, folgt dem Abspielkopf" : "Ganzes Video"}</span>
          <span className="tabular-nums">{timecode(fensterBis)}</span>
        </div>
        </div>
      </div>

      {/* Schnittwerkzeuge, benannt nach dem was sie tun */}
      {canEdit && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => onSchnitt(anfangKuerzen(schnitt, zeit), "Anfang gekürzt")} disabled={!istSichtbar(schnitt, zeit)}>
            Anfang kürzen
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onSchnitt(endeKuerzen(schnitt, zeit), "Ende gekürzt")} disabled={!istSichtbar(schnitt, zeit)}>
            Ende kürzen
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onSchnitt(teilen(schnitt, zeit), "Geteilt")} disabled={!kannTeilen}>
            Hier schneiden
          </Button>
          <Button
            variant={kannEntfernen ? "danger" : "ghost"}
            size="sm"
            onClick={() => {
              if (gewaehlt == null) return;
              onSchnitt(entfernen(schnitt, gewaehlt), "Teil entfernt");
              setGewaehlt(null);
            }}
            disabled={!kannEntfernen}
          >
            Teil entfernen
          </Button>
          <span className="text-sm text-text-2">
            {gewaehlt != null
              ? `Abschnitt ${gewaehlt + 1} ausgewählt.`
              : schnitt.length > 1
                ? "Tipp einen Abschnitt an, um ihn zu entfernen."
                : "Erst „Hier schneiden“, dann lässt sich ein Teil entfernen."}
          </span>
        </div>
      )}
    </GlassCard>
  );
}

/* Was NICHT im Clip ist, innerhalb des angezeigten Bereichs. */
export function luecken(schnitt: Schnitt, vonS: number, bisS: number): { von: number; bis: number }[] {
  const aus: { von: number; bis: number }[] = [];
  let letzte = vonS;
  for (const a of schnitt) {
    if (a.start > letzte) aus.push({ von: letzte, bis: Math.min(a.start, bisS) });
    letzte = Math.max(letzte, a.end);
  }
  if (letzte < bisS) aus.push({ von: letzte, bis: bisS });
  return aus.filter((l) => l.bis > l.von);
}

/* Die Marker als Abschnitte in Quellzeit: ab welcher Stelle gilt welche Entscheidung.
 *
 * Marker liegen in QUELLZEIT, so wie der Renderer sie liest (tracking.zeitmarken_anwenden). Eine
 * Marke heisst „ab dieser Stelle im Video", nicht „ab dieser Sekunde des fertigen Clips": sonst
 * verschoebe ein Kuerzen am Anfang alle Bildausschnitte, obwohl am Bild nichts geaendert wurde.
 *
 * Ein Marker vor dem Clipanfang gilt trotzdem, denn er ist die zuletzt getroffene Entscheidung;
 * angezeigt wird er ab dem Anfang des Clips. */
export function marken_abschnitte(marken: Zeitmarke[], schnitt: Schnitt): {
  vonQuelle: number;
  bisQuelle: number;
  marke: Zeitmarke | null;
}[] {
  const anfang = schnitt[0]?.start ?? 0;
  const ende = schnitt[schnitt.length - 1]?.end ?? 0;
  const sortiert = [...marken].filter((m) => m.ab_s < ende).sort((a, b) => a.ab_s - b.ab_s);
  const grenzen: { ab: number; marke: Zeitmarke | null }[] = [{ ab: anfang, marke: null }];
  for (const m of sortiert) {
    if (m.ab_s <= anfang + 1e-6) grenzen[0].marke = m;
    else grenzen.push({ ab: m.ab_s, marke: m });
  }
  const aus: { vonQuelle: number; bisQuelle: number; marke: Zeitmarke | null }[] = [];
  for (let i = 0; i < grenzen.length; i += 1) {
    aus.push({
      vonQuelle: grenzen[i].ab,
      bisQuelle: i + 1 < grenzen.length ? grenzen[i + 1].ab : ende,
      marke: grenzen[i].marke,
    });
  }
  return aus.filter((a) => a.bisQuelle > a.vonQuelle);
}

/* Ein Name links neben einer Spur. Die Hoehe wird durchgereicht, damit Name und Spur auf einer
 * Linie liegen; ``oben`` bildet den Abstand zwischen den Spuren nach. */
function Name({ hoehe, oben, children }: { hoehe: number; oben?: boolean; children: React.ReactNode }) {
  return (
    <span className={cn("flex items-center truncate", oben && "mt-1")} style={{ height: hoehe }}>
      {children}
    </span>
  );
}

function Werkzeug({ titel, onClick, disabled, children }: { titel: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={titel}
      aria-label={titel}
      onClick={onClick}
      disabled={disabled}
      className="transition-soft flex h-8 w-8 items-center justify-center rounded-inner border border-line text-text-2 hover:border-line-strong hover:text-text disabled:opacity-40 focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
    >
      {children}
    </button>
  );
}

function Griff({ seite, onPointer }: { seite: "links" | "rechts"; onPointer: (e: React.PointerEvent) => void }) {
  return (
    <button
      type="button"
      onPointerDown={onPointer}
      aria-label={seite === "links" ? "Anfang dieses Abschnitts verschieben" : "Ende dieses Abschnitts verschieben"}
      className={cn(
        "transition-soft absolute top-0 h-full w-3 cursor-ew-resize focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60",
        seite === "links" ? "left-0" : "right-0",
      )}
    >
      <span className="mx-auto block h-full w-[3px] rounded-full bg-white/60" />
    </button>
  );
}
