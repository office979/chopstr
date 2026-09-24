"use client";

import { useCallback, useMemo, useRef } from "react";
import { cn } from "@/components/ui/cn";
import type { FilmstripMeta, RenderShot, Zeitmarke } from "@/lib/repo/types";

interface Props {
  /* Einzelbilder des fertigen Clips als ein Bild. Fehlt es, bleibt die Leiste leer, aber bedienbar. */
  filmstripSrc: string | null;
  filmstripMeta: FilmstripMeta | null;
  /* Die Zeit des Clips in der Quelle: hier faengt er an, so lang ist er. */
  clipStart: number;
  dauerS: number;
  /* Wo der Player gerade steht, in Quellzeit. */
  zeit: number;
  onSeek: (quellzeit: number) => void;
  /* Was wann im Bild ist, aus dem Renderplan. Leer, solange nichts gerendert wurde. */
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  onMarke: (marke: Zeitmarke) => void;
  onMarkeWeg: (abS: number) => void;
  quelleBreite: number | null;
  canEdit: boolean;
}

const HOEHE = 72;

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

/* Die Zeitleiste: Einzelbilder des Clips, ein Schieber, und darunter wer wann im Bild ist.
 *
 * Bewusst EIN Bedienelement statt vieler: ziehen oder klicken bewegt den Schieber, und alles
 * andere richtet sich danach. Wer eine Stelle sucht, soll schieben und nicht erst lernen, welcher
 * Knopf was tut. */
export function Zeitleiste({
  filmstripSrc,
  filmstripMeta,
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

  const aktiverShot = useMemo(
    () => shots.find((s) => zeit >= s.start && zeit < s.end) ?? null,
    [shots, zeit],
  );
  const auswahl = useMemo(() => [...(aktiverShot?.auswahl ?? [])].sort((a, b) => a - b), [aktiverShot]);
  const markeHier = useMemo(
    () => zeitmarken.find((m) => Math.abs(m.ab_s - imClip) < 0.35) ?? null,
    [zeitmarken, imClip],
  );
  const gewaehlt = aktiverShot?.quelle_x ?? null;

  return (
    <div className="flex flex-col gap-3">
      {/* Die Spur: Einzelbilder, Schnittmarken, Schieber */}
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
          <img
            src={filmstripSrc}
            alt=""
            draggable={false}
            /* Auf die Spurbreite gezogen: die Einzelbilder werden schmaler, aber sie sollen die
             * Stelle zeigen, nicht das Bild ersetzen. Dafuer ist die Vorschau oben da. */
            className="pointer-events-none h-full w-full object-fill opacity-70"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-3">
            Einzelbilder gibt es, sobald der Clip gebaut ist
          </div>
        )}

        {/* Kameraschnitte als feine Striche */}
        {shots.slice(1).map((s) => (
          <div
            key={s.start}
            className="pointer-events-none absolute top-0 h-full w-px bg-white/45"
            style={{ left: `${((s.start - clipStart) / Math.max(dauerS, 1e-6)) * 100}%` }}
          />
        ))}

        {/* Gesetzte Marken */}
        {zeitmarken.map((m) => (
          <div
            key={m.ab_s}
            title={`Von Hand gesetzt bei ${sekunden(m.ab_s)}`}
            className="pointer-events-none absolute top-0 h-full w-[3px] bg-attention"
            style={{ left: `${(m.ab_s / Math.max(dauerS, 1e-6)) * 100}%` }}
          />
        ))}

        {/* Der Schieber */}
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

      {/* Wer soll zu sehen sein? Nur wenn es hier ueberhaupt etwas zu wählen gibt. */}
      {canEdit && auswahl.length > 1 && (
        <div className="flex flex-col gap-2 rounded-inner border border-line bg-black/20 p-3">
          <p className="text-sm font-medium text-text">Wer soll hier zu sehen sein?</p>
          <div className="flex flex-wrap gap-2">
            {auswahl.map((x) => {
              const aktiv = gewaehlt != null && Math.abs(gewaehlt - x) < 1e-6;
              return (
                <button
                  key={x}
                  type="button"
                  onClick={() => onMarke({ ab_s: Math.round(imClip * 100) / 100, x: Math.round(x) })}
                  className={cn(
                    "transition-soft flex items-center gap-2 rounded-inner border px-3 py-2 text-sm",
                    aktiv ? "border-white/60 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong",
                  )}
                >
                  <Lage x={x} alle={auswahl} breite={quelleBreite} />
                  {personName(x, auswahl)}
                </button>
              );
            })}
          </div>
          <p className="text-sm text-text-2">
            {markeHier
              ? "Ab hier von Hand gesetzt."
              : "Die Wahl gilt ab dieser Stelle, bis du sie wieder änderst."}
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
