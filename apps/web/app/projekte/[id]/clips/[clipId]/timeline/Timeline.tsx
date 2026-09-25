"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import {
  abschnittBei,
  anfangKuerzen,
  dauer as schnittDauer,
  endeKuerzen,
  entfernen,
  inClipzeit,
  inQuellzeit,
  istSichtbar,
  randSetzen,
  teilen,
  type Schnitt,
} from "@/lib/clips/schnitt";
import { EFFEKT_LABEL, MIN_DAUER_S, type Effekt } from "@/lib/clips/effekte";
import type { RenderShot, Zeitmarke } from "@/lib/repo/types";
import { Lineal, timecode } from "./Lineal";
import { Wellenform, type WellenformDaten, type WellenformStand } from "./Wellenform";

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
  wellenformStand: WellenformStand;
  filmstreifen: string[];
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  onMarkeWeg: (abS: number) => void;
  onMarkeVerschieben: (vonS: number, nachS: number) => void;
  /* Effekte liegen in CLIPZEIT, anders als die Zeitmarken: eine Betonung hängt an dem, was gesagt
   * wird, und soll mitwandern, wenn davor etwas herausgeschnitten wird. */
  effekte: Effekt[];
  onEffektVerschieben: (index: number, abS: number) => void;
  onEffektDauer: (index: number, dauerS: number) => void;
  onEffektWeg: (index: number) => void;
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
  wellenformStand,
  filmstreifen,
  shots,
  zeitmarken,
  onMarkeWeg,
  onMarkeVerschieben,
  effekte,
  onEffektVerschieben,
  onEffektDauer,
  onEffektWeg,
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

  /* Was gerade gezogen wird. Nur für die Anzeige: gespeichert wird beim Loslassen. */
  const [ziehtEffekt, setZiehtEffekt] = useState<{ index: number; was: "verschieben" | "dauer"; wert: number } | null>(
    null,
  );

  /* Einen Effekt verschieben oder an seinem rechten Rand verlängern.
   *
   * Der Zeiger liefert Quellzeit, gespeichert wird Clipzeit - deshalb die Umrechnung bei jedem
   * Schritt. Übernommen wird erst beim Loslassen: ein Speichern je Mausbewegung wäre ein Dutzend
   * Schreibvorgänge für eine Geste. */
  /* Einen Effekt verschieben oder an seinem rechten Rand verlängern.
   *
   * Der Block folgt der Maus, solange gezogen wird: ein Griff, der erst beim Loslassen springt,
   * fühlt sich kaputt an, und man trifft die Stelle nicht. Gespeichert wird trotzdem erst beim
   * Loslassen - ein Schreibvorgang je Mausbewegung wären Dutzende für eine Geste.
   *
   * Der Zeiger liefert Quellzeit, gespeichert wird Clipzeit; deshalb die Umrechnung bei jedem
   * Schritt. */
  const effektZiehen = useCallback(
    (index: number, was: "verschieben" | "dauer") => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const effekt = effekte[index];
      if (!effekt) return;
      let letzte: number | null = null;
      const los = (ev: PointerEvent) => {
        const quelle = ausX(ev.clientX);
        if (quelle == null) return;
        const clipzeit = inClipzeit(schnitt, quelle);
        letzte = was === "verschieben" ? Math.max(0, clipzeit) : Math.max(MIN_DAUER_S, clipzeit - effekt.ab_s);
        setZiehtEffekt({ index, was, wert: Math.round(letzte * 100) / 100 });
      };
      const ende = () => {
        window.removeEventListener("pointermove", los);
        window.removeEventListener("pointerup", ende);
        setZiehtEffekt(null);
        if (letzte == null) return;
        if (was === "verschieben") {
          if (Math.abs(letzte - effekt.ab_s) > 0.02) onEffektVerschieben(index, Math.round(letzte * 100) / 100);
        } else if (Math.abs(letzte - effekt.dauer_s) > 0.02) {
          onEffektDauer(index, Math.round(letzte * 100) / 100);
        }
      };
      window.addEventListener("pointermove", los);
      window.addEventListener("pointerup", ende);
    },
    [ausX, effekte, schnitt, onEffektVerschieben, onEffektDauer],
  );

  /* Die Effekte so, wie sie gerade aussehen sollen - mit der laufenden Bewegung darin. */
  const effekteSicht = useMemo(() => {
    if (!ziehtEffekt) return effekte;
    return effekte.map((e, i) =>
      i !== ziehtEffekt.index
        ? e
        : ziehtEffekt.was === "verschieben"
          ? { ...e, ab_s: ziehtEffekt.wert }
          : { ...e, dauer_s: Math.max(MIN_DAUER_S, ziehtEffekt.wert) },
    );
  }, [effekte, ziehtEffekt]);

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
    } else if (e.key === "s" || e.key === "S") {
      /* Schneiden an der Stelle des Abspielkopfs. Wer viele Clips schneidet, wechselt sonst für
       * jeden Schnitt zwischen Tastatur und Maus - und das ist die Bewegung, die Schneiden
       * langsam macht. Die Buchstaben sind die, die Schnittprogramme seit Jahrzehnten benutzen. */
      if (!kannTeilen) return;
      e.preventDefault();
      onSchnitt(teilen(schnitt, zeit), "Geteilt");
    } else if (e.key === "i" || e.key === "I") {
      if (!istSichtbar(schnitt, zeit)) return;
      e.preventDefault();
      onSchnitt(anfangKuerzen(schnitt, zeit), "Anfang gekürzt");
    } else if (e.key === "o" || e.key === "O") {
      if (!istSichtbar(schnitt, zeit)) return;
      e.preventDefault();
      onSchnitt(endeKuerzen(schnitt, zeit), "Ende gekürzt");
    } else if ((e.key === "Backspace" || e.key === "Delete") && kannEntfernen && gewaehlt != null) {
      e.preventDefault();
      onSchnitt(entfernen(schnitt, gewaehlt), "Teil entfernt");
      setGewaehlt(null);
    } else if ((e.key === "z" || e.key === "Z") && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (e.shiftKey) {
        if (kannVor) onVor();
      } else if (kannZurueck) {
        onZurueck();
      }
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
            Fertiger Clip: <span className="tabular-nums">{timecode(dauerGesamt, true)}</span>
          </span>
        </div>
        {/* Zwei Zeitrechnungen, und beide sind beschriftet. Vorher stand „Clip 0:36" neben einem
          * Lineal bei 3:15 und einer Eingabe ab 0:00, ohne dass irgendwo stand, worauf sich was
          * bezieht. */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-inner border border-line px-2.5 py-1 text-sm text-text-2">
            Im Originalvideo <span className="tabular-nums text-text">{timecode(zeit, true)}</span>
          </span>
          <span className="rounded-inner border border-line px-2.5 py-1 text-sm text-text-2">
            Im fertigen Clip <span className="tabular-nums text-text">{timecode(imClip, true)}</span>
          </span>
          <label className="flex items-center gap-1.5 text-sm text-text-2">
            <span className="sr-only">Zu Zeitpunkt im Originalvideo springen</span>
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
              aria-label="Zeitpunkt im Originalvideo, zum Beispiel 0:12"
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
        aria-label="Timeline. Pfeiltasten bewegen, Leertaste spielt ab, S schneidet, I kürzt den Anfang, O das Ende, Entfernen löscht den gewählten Abschnitt"
        className="transition-soft mt-4 flex gap-2 rounded-inner border border-line p-2 focus:border-white/50 focus:outline-none"
      >
        {/* Die Namen der Spuren. Ohne sie stehen hier vier Streifen uebereinander und niemand
          * weiss, welcher wofuer da ist. Die Hoehen stimmen mit den Spuren rechts ueberein. */}
        <div className="hidden w-[104px] shrink-0 flex-col pt-5 text-xs text-text-2 sm:flex">
          <Name hoehe={SPUR_HOEHE}>Bild</Name>
          <Name hoehe={44} oben>Ton</Name>
          <Name hoehe={36} oben>Schnitt</Name>
          <Name hoehe={36} oben>Bildausschnitt</Name>
          <Name hoehe={30} oben>Effekte</Name>
        </div>

        <div className="min-w-0 flex-1">
        {/* Ein Klick auf die Zeitskala setzt den Abspielkopf. Vorher war sie nur Beschriftung:
            man sah 3:30 stehen und konnte nicht hin. */}
        <div
          role="presentation"
          onPointerDown={ziehen((t) => onSeek(t))}
          className="cursor-pointer"
          title="Klicken setzt den Abspielkopf"
        >
          <Lineal vonS={fensterVon} bisS={fensterBis} breitePx={breite} />
        </div>

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
            <Wellenform daten={wellenform} vonS={fensterVon} bisS={fensterBis} stand={wellenformStand} />
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

          {/* Effekte: eine eigene Spur.
              Die Blöcke liegen in Clipzeit und werden für die Anzeige in Quellzeit umgerechnet -
              deshalb wandert ein Effekt mit, wenn davor etwas herausgeschnitten wird. */}
          <div className="relative mt-1 h-7 w-full rounded-[6px] bg-black/25">
            {effekteSicht.map((e, i) => {
              const vonQ = inQuellzeit(schnitt, e.ab_s);
              const bisQ = inQuellzeit(schnitt, e.ab_s + e.dauer_s);
              if (!(bisQ > vonQ)) return null;
              return (
                <div
                  key={`${e.art}-${e.ab_s}`}
                  onPointerDown={canEdit ? effektZiehen(i, "verschieben") : undefined}
                  className={cn(
                    "absolute top-0 flex h-full items-center overflow-hidden rounded-[6px] border border-ai/60 bg-ai/20 px-2",
                    canEdit && "cursor-grab",
                  )}
                  style={{ left: `${anteil(vonQ) * 100}%`, width: `${((bisQ - vonQ) / sichtbar) * 100}%` }}
                  title={`${EFFEKT_LABEL[e.art]} ab ${e.ab_s.toFixed(1)} s, ${e.dauer_s.toFixed(1)} s lang`}
                >
                  <span className="truncate text-[11px] text-text-2">{EFFEKT_LABEL[e.art]}</span>
                  {canEdit && (
                    <>
                      {/* Rechter Rand: länger oder kürzer ziehen. */}
                      <button
                        type="button"
                        onPointerDown={effektZiehen(i, "dauer")}
                        onKeyDown={(ev) => {
                          const schritt = ev.shiftKey ? 0.5 : 0.1;
                          const ziel =
                            e.dauer_s + (ev.key === "ArrowLeft" ? -schritt : ev.key === "ArrowRight" ? schritt : 0);
                          if (ziel === e.dauer_s) return;
                          ev.preventDefault();
                          ev.stopPropagation();
                          onEffektDauer(i, Math.round(ziel * 100) / 100);
                        }}
                        aria-label={`${EFFEKT_LABEL[e.art]} länger oder kürzer machen, mit Pfeiltasten oder Ziehen`}
                        className="absolute right-5 top-0 h-full w-3 cursor-ew-resize focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
                      >
                        <span className="mx-auto block h-full w-[3px] bg-ai" />
                      </button>
                      <button
                        type="button"
                        onPointerDown={(ev) => ev.stopPropagation()}
                        onClick={() => onEffektWeg(i)}
                        aria-label={`${EFFEKT_LABEL[e.art]} bei ${e.ab_s.toFixed(1)} Sekunden entfernen`}
                        className="transition-soft absolute right-0.5 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full text-text-3 hover:bg-white/10 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-white/60"
                      >
                        <svg width="8" height="8" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                          <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                        </svg>
                      </button>
                    </>
                  )}
                </div>
              );
            })}
            {effekteSicht.length === 0 && (
              <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[11px] text-text-3">
                Keine Effekte
              </span>
            )}
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
          <span>
            Zeiten im Originalvideo · {lupe > 1 ? "Ausschnitt, folgt dem Abspielkopf" : "ganzes Video"}
          </span>
          <span className="tabular-nums">{timecode(fensterBis)}</span>
        </div>
        </div>
      </div>

      {/* Schnittwerkzeuge, benannt nach dem was sie tun. Die Tastenkürzel stehen an den Knöpfen:
          ein Kürzel, das man nicht sieht, benutzt niemand. */}
      {canEdit && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => onSchnitt(anfangKuerzen(schnitt, zeit), "Anfang gekürzt")} disabled={!istSichtbar(schnitt, zeit)}>
            Anfang kürzen <Kuerzel>I</Kuerzel>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onSchnitt(endeKuerzen(schnitt, zeit), "Ende gekürzt")} disabled={!istSichtbar(schnitt, zeit)}>
            Ende kürzen <Kuerzel>O</Kuerzel>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onSchnitt(teilen(schnitt, zeit), "Geteilt")} disabled={!kannTeilen}>
            Hier schneiden <Kuerzel>S</Kuerzel>
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
            Teil entfernen <Kuerzel>Entf</Kuerzel>
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

/* Ein Tastenkürzel an einem Knopf. Klein und ruhig: es soll auffindbar sein, nicht laut. */
function Kuerzel({ children }: { children: ReactNode }) {
  return (
    <kbd className="ml-1.5 rounded border border-line px-1 font-mono text-[10px] font-normal text-text-3">
      {children}
    </kbd>
  );
}
