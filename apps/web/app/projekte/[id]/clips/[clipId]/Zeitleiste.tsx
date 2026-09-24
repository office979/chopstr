"use client";

import { useCallback, useMemo, useRef } from "react";
import { cn } from "@/components/ui/cn";
import type { FilmstripMeta, RenderShot, Zeitmarke } from "@/lib/repo/types";
import { useFilmstreifen } from "./useFilmstreifen";

interface Props {
  /* Einzelbilder des fertigen Clips als ein Bild, sobald gerendert wurde. */
  filmstripSrc: string | null;
  filmstripMeta: FilmstripMeta | null;
  /* Das Quellvideo. Solange es keinen gerenderten Streifen gibt, werden die Bilder daraus gezeichnet. */
  videoSrc: string | null;
  clipStart: number;
  dauerS: number;
  zeit: number;
  onSeek: (quellzeit: number) => void;
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  onMarke: (marke: Zeitmarke) => void;
  onMarkeWeg: (abS: number) => void;
  quelleBreite: number | null;
  canEdit: boolean;
}

const HOEHE = 76;

function sekunden(t: number): string {
  const s = Math.max(0, t);
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/* Wie heisst die Person an dieser Bildstelle, damit ein Mensch sie wiedererkennt?
 *
 * Nicht „Position 2" und nicht die Bildpunkte: beides sagt niemandem etwas. Bei zwei oder drei
 * Personen reicht links/Mitte/rechts, darueber wird von links durchgezaehlt. */
export function personName(x: number, alle: number[]): string {
  const sortiert = [...alle].sort((a, b) => a - b);
  const i = sortiert.findIndex((v) => Math.abs(v - x) < 1e-6);
  if (i < 0) return "diese Person";
  if (sortiert.length === 1) return "die Person";
  if (sortiert.length === 2) return i === 0 ? "links" : "rechts";
  if (sortiert.length === 3) return ["links", "Mitte", "rechts"][i];
  return `${i + 1}. von links`;
}

/* Drei Stufen statt eines Schiebereglers. „Wie nah?" hat keine sinnvolle Zwischenstufe: entweder
 * das Bild steht wie es ist, oder es geht spuerbar naeher heran. Ein Regler von 1,0 bis 1,8 laedt
 * dazu ein, 1,07 einzustellen, und das sieht niemand. */
export interface Abschnitt {
  vonS: number;
  bisS: number;
  marke: Zeitmarke | null;
}

/* Die Marken als Abschnitte lesen: eine Marke gilt „ab hier bis zur naechsten".
 *
 * Das ist der Unterschied zu Keyframes, wie sie ein Schnittprogramm kennt. Dort ist ein Punkt ein
 * Wert zu einem Zeitpunkt, und zwischen zwei Punkten wird gerechnet. Hier gilt eine Entscheidung
 * unveraendert bis zur naechsten - das ist leichter zu verstehen und deckt ab, was ein Clip
 * braucht. Deshalb werden die Marken auch als Abschnitte angezeigt und nicht als Punkte: die
 * Anzeige soll das Modell zeigen, nicht ein anderes vortaeuschen. */
export function abschnitte(marken: Zeitmarke[], dauerS: number): Abschnitt[] {
  const sortiert = [...marken].filter((m) => m.ab_s < dauerS).sort((a, b) => a.ab_s - b.ab_s);
  const aus: Abschnitt[] = [];
  let von = 0;
  let laufende: Zeitmarke | null = null;
  for (const m of sortiert) {
    if (m.ab_s > von + 1e-6) {
      aus.push({ vonS: von, bisS: m.ab_s, marke: laufende });
      von = m.ab_s;
    }
    laufende = m;
  }
  aus.push({ vonS: von, bisS: dauerS, marke: laufende });
  return aus;
}

export const NAEHE = [
  { id: 1.0, name: "Normal" },
  { id: 1.3, name: "Näher" },
  { id: 1.6, name: "Ganz nah" },
] as const;

export function Zeitleiste({
  filmstripSrc,
  filmstripMeta,
  videoSrc,
  clipStart,
  dauerS,
  zeit,
  onSeek,
  shots,
  zeitmarken,
  onMarke,
  onMarkeWeg,
  quelleBreite,
  canEdit,
}: Props) {
  const spurRef = useRef<HTMLDivElement | null>(null);
  const imClip = Math.max(0, Math.min(dauerS, zeit - clipStart));
  const anteil = dauerS > 0 ? imClip / dauerS : 0;

  /* Gibt es schon einen gerenderten Streifen, wird der genommen. Sonst zeichnet der Browser die
   * Bilder aus dem Quellvideo - gebraucht werden sie VOR dem Render, nicht danach. */
  const selbstGezeichnet = useFilmstreifen(filmstripSrc ? null : videoSrc, clipStart, clipStart + dauerS);

  const ausSpur = useCallback(
    (clientX: number) => {
      const el = spurRef.current;
      if (!el || dauerS <= 0) return null;
      const r = el.getBoundingClientRect();
      const p = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      return clipStart + p * dauerS;
    },
    [clipStart, dauerS],
  );

  /* Ziehen ohne Bibliothek: beim Druck auf die Spur die Bewegung am Fenster mitlesen, beim
   * Loslassen wieder abmelden. Pointer-Ereignisse decken Maus und Finger gleichermassen ab. */
  const greifen = useCallback(
    (e: React.PointerEvent) => {
      const erst = ausSpur(e.clientX);
      if (erst != null) onSeek(erst);
      const bewegen = (ev: PointerEvent) => {
        const t = ausSpur(ev.clientX);
        if (t != null) onSeek(t);
      };
      const los = () => {
        window.removeEventListener("pointermove", bewegen);
        window.removeEventListener("pointerup", los);
      };
      window.addEventListener("pointermove", bewegen);
      window.addEventListener("pointerup", los);
    },
    [ausSpur, onSeek],
  );

  const aktiverShot = useMemo(() => shots.find((s) => zeit >= s.start && zeit < s.end) ?? null, [shots, zeit]);
  const auswahl = useMemo(() => [...(aktiverShot?.auswahl ?? [])].sort((a, b) => a - b), [aktiverShot]);
  const markeHier = useMemo(() => zeitmarken.find((m) => Math.abs(m.ab_s - imClip) < 0.35) ?? null, [zeitmarken, imClip]);

  /* Was gilt hier gerade? Eine gesetzte Marke schlaegt den Plan; ohne Marke zeigt der Plan, was die
   * Automatik entschieden hat. */
  const gueltig = useMemo(() => {
    const davor = [...zeitmarken].filter((m) => m.ab_s <= imClip + 1e-6).sort((a, b) => a.ab_s - b.ab_s).pop();
    return {
      x: davor?.x ?? aktiverShot?.quelle_x ?? null,
      zoom: davor?.zoom ?? aktiverShot?.zoom ?? 1.0,
      geteilt: (davor?.layout ?? (aktiverShot?.layout === "geteilt" ? "geteilt" : "einzel")) === "geteilt",
    };
  }, [zeitmarken, imClip, aktiverShot]);

  /* Jede Aenderung schreibt eine VOLLSTAENDIGE Marke. Sonst haengt das Ergebnis davon ab, in
   * welcher Reihenfolge jemand die Knoepfe gedrueckt hat, und „ab hier sieht es so aus" waere
   * nicht mehr wahr. */
  const setzen = (teil: Partial<Zeitmarke>) => {
    onMarke({
      ab_s: Math.round(imClip * 100) / 100,
      ...(gueltig.x != null ? { x: Math.round(gueltig.x) } : {}),
      zoom: gueltig.zoom,
      layout: gueltig.geteilt ? "geteilt" : "einzel",
      ...teil,
    });
  };

  const etwasGesetzt = gueltig.zoom > 1.0 || gueltig.geteilt || markeHier != null;
  const stuecke = useMemo(() => abschnitte(zeitmarken, dauerS), [zeitmarken, dauerS]);
  /* Fuer die Beschriftung reicht die Sitzordnung aus irgendeinem Abschnitt: sie aendert sich
   * innerhalb eines Clips selten, und es geht nur um links/Mitte/rechts. */
  const auswahlAllerShots = useMemo(
    () => [...new Set(shots.flatMap((sh) => sh.auswahl ?? []))].sort((a, b) => a - b),
    [shots],
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Eine Ueberschrift, die sagt wofuer die Leiste da ist. Ohne sie steht hier ein Streifen
        * Bilder und darunter Knoepfe, und niemand weiss, was zusammengehoert. */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Zeitleiste</h2>
        <p className="text-sm text-text-2">Was wann zu sehen ist</p>
      </div>
      <div
        ref={spurRef}
        onPointerDown={greifen}
        role="slider"
        tabIndex={0}
        aria-label="Stelle im Clip"
        aria-valuemin={0}
        aria-valuemax={Math.round(dauerS)}
        aria-valuenow={Math.round(imClip)}
        aria-valuetext={sekunden(imClip)}
        onKeyDown={(e) => {
          const schritt = e.shiftKey ? 1 : 0.2;
          if (e.key === "ArrowLeft") onSeek(Math.max(clipStart, zeit - schritt));
          else if (e.key === "ArrowRight") onSeek(Math.min(clipStart + dauerS, zeit + schritt));
          else return;
          e.preventDefault();
        }}
        className="relative w-full cursor-pointer touch-none select-none overflow-hidden rounded-inner border border-line bg-black/50 focus:border-white/50 focus:outline-none"
        style={{ height: HOEHE }}
      >
        {filmstripSrc && filmstripMeta ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={filmstripSrc} alt="" draggable={false} className="pointer-events-none h-full w-full object-fill" />
        ) : selbstGezeichnet.length > 0 ? (
          <div className="pointer-events-none flex h-full w-full">
            {selbstGezeichnet.map((bild, i) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={i}
                src={bild}
                alt=""
                draggable={false}
                className="h-full flex-1 object-cover"
                style={{ minWidth: 0 }}
              />
            ))}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-3">
            {videoSrc ? "Einzelbilder werden geholt" : "Einzelbilder gibt es, sobald das Video da ist"}
          </div>
        )}

        {/* Kameraschnitte */}
        {shots.slice(1).map((s) => (
          <div
            key={s.start}
            className="pointer-events-none absolute top-0 h-full w-px bg-white/45"
            style={{ left: `${((s.start - clipStart) / Math.max(dauerS, 1e-6)) * 100}%` }}
          />
        ))}

        {/* Gesetzte Marken, mit dem Zeichen dessen, was dort passiert */}
        {zeitmarken.map((m) => (
          <div
            key={m.ab_s}
            title={`Von Hand gesetzt bei ${sekunden(m.ab_s)}`}
            className="pointer-events-none absolute top-0 flex h-full flex-col items-center"
            style={{ left: `${(m.ab_s / Math.max(dauerS, 1e-6)) * 100}%` }}
          >
            <span className="h-full w-[3px] bg-attention" />
            <span className="absolute -top-[1px] left-1/2 -translate-x-1/2 rounded-b-[4px] bg-attention px-1 text-[10px] font-semibold leading-[13px] text-black">
              {m.layout === "geteilt" ? "II" : (m.zoom ?? 1) > 1.4 ? "++" : (m.zoom ?? 1) > 1 ? "+" : "•"}
            </span>
          </div>
        ))}

        <div
          className="pointer-events-none absolute top-0 h-full w-[2px] bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.6)]"
          style={{ left: `${anteil * 100}%` }}
        >
          <div className="absolute -left-[7px] -top-1 h-4 w-4 rounded-full border-2 border-black/60 bg-white" />
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-text-2">
        <span className="tabular-nums">{sekunden(imClip)}</span>
        <span className="tabular-nums">{sekunden(dauerS)}</span>
      </div>

      {/* Die Abschnitte: was gilt wo. Ein duenner Strich auf dem Streifen sagt niemandem, dass er
        * dort etwas gesetzt hat; eine beschriftete Flaeche schon. Breite nach Dauer, damit sich die
        * Leiste mit dem Streifen darueber deckt. */}
      <div className="flex w-full gap-[2px]" aria-label="Abschnitte">
        {stuecke.map((a) => {
          const hier = imClip >= a.vonS && imClip < a.bisS;
          return (
            <button
              key={a.vonS}
              type="button"
              onClick={() => onSeek(clipStart + a.vonS + 0.05)}
              title={`Ab ${sekunden(a.vonS)}`}
              style={{ width: `${((a.bisS - a.vonS) / Math.max(dauerS, 1e-6)) * 100}%` }}
              className={cn(
                "transition-soft min-w-0 overflow-hidden rounded-[6px] border px-2 py-1.5 text-left",
                hier ? "border-white/60 bg-white/10" : "border-line hover:border-line-strong",
                a.marke ? "" : "border-dashed",
              )}
            >
              <span className="block truncate text-xs tabular-nums text-text-2">{sekunden(a.vonS)}</span>
              <span className={cn("block truncate text-xs", hier ? "text-text" : "text-text-3")}>
                {beschreibung(a.marke, auswahlAllerShots)}
              </span>
            </button>
          );
        })}
      </div>

      {/* Was an dieser Stelle gilt, und was man daran aendern kann. Alles in einem Kasten, damit der
        * Zusammenhang zur Zeitleiste sichtbar bleibt: hier steht der Schieber, hier wird es gesetzt. */}
      {canEdit && (
        <div className="flex flex-col gap-4 rounded-inner border border-line bg-black/20 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-text">Ab {sekunden(imClip)} gilt</p>
            <p className="text-sm text-text-3">Schieb oben an eine Stelle</p>
          </div>

          {auswahl.length > 1 && (
            <Reihe titel="Wer ist im Bild">
              {auswahl.map((x) => (
                <Knopf
                  key={x}
                  aktiv={gueltig.x != null && Math.abs(gueltig.x - x) < 1e-6}
                  onClick={() => setzen({ x: Math.round(x) })}
                >
                  <Lage x={x} alle={auswahl} breite={quelleBreite} />
                  {personName(x, auswahl)}
                </Knopf>
              ))}
            </Reihe>
          )}

          <Reihe titel="Wie nah">
            {NAEHE.map((n) => (
              <Knopf key={n.id} aktiv={Math.abs(gueltig.zoom - n.id) < 0.05} onClick={() => setzen({ zoom: n.id })}>
                {n.name}
              </Knopf>
            ))}
          </Reihe>

          {auswahl.length > 1 && (
            <Reihe titel="Bild">
              <Knopf aktiv={!gueltig.geteilt} onClick={() => setzen({ layout: "einzel" })}>
                Einer
              </Knopf>
              <Knopf aktiv={gueltig.geteilt} onClick={() => setzen({ layout: "geteilt" })}>
                Beide übereinander
              </Knopf>
            </Reihe>
          )}

          <p className="text-sm text-text-2">
            {markeHier ? "Von hier an von Hand gesetzt." : etwasGesetzt ? "Gilt von einer früheren Stelle." : "Die Automatik entscheidet."}
          </p>
          {markeHier && (
            <button
              type="button"
              onClick={() => onMarkeWeg(markeHier.ab_s)}
              className="transition-soft self-start text-sm text-text-2 underline underline-offset-4 hover:text-text"
            >
              Wieder automatisch entscheiden lassen
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Reihe({ titel, children }: { titel: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs uppercase tracking-wide text-text-3">{titel}</p>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

function Knopf({ aktiv, onClick, children }: { aktiv: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={aktiv}
      className={cn(
        "transition-soft flex items-center gap-2 rounded-inner border px-3 py-2 text-sm",
        aktiv ? "border-white/60 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong",
      )}
    >
      {children}
    </button>
  );
}

/* Ein kleines Bild der Sitzordnung: Punkte von links nach rechts, der gemeinte gefüllt.
 * Sagt mehr als „Position 2" und braucht keine Erklärung. */
function Lage({ x, alle, breite }: { x: number; alle: number[]; breite: number | null }) {
  const b = breite && breite > 0 ? breite : Math.max(...alle, 1) * 1.2;
  return (
    <span aria-hidden="true" className="relative inline-block h-3 w-10 rounded-full bg-white/10">
      {alle.map((v) => (
        <span
          key={v}
          className={cn(
            "absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full",
            Math.abs(v - x) < 1e-6 ? "bg-text" : "bg-white/35",
          )}
          style={{ left: `${Math.max(10, Math.min(90, (v / b) * 100))}%` }}
        />
      ))}
    </span>
  );
}

/* Was in diesem Abschnitt gilt, in einem kurzen Satz. „x=2582, zoom=1.3" hilft niemandem. */
export function beschreibung(marke: Zeitmarke | null, auswahl: number[]): string {
  if (!marke) return "Automatisch";
  const teile: string[] = [];
  if (marke.layout === "geteilt") teile.push("Beide");
  else if (marke.x != null && auswahl.length > 1) teile.push(personName(marke.x, auswahl));
  const n = NAEHE.find((x) => Math.abs(x.id - (marke.zoom ?? 1)) < 0.05);
  if (n && n.id > 1) teile.push(n.name.toLowerCase());
  return teile.length ? teile.join(", ") : "Von Hand";
}
