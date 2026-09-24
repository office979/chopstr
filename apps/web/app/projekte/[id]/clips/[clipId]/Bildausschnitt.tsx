"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "@/components/ui/cn";
import type { RenderShot, Zeitmarke } from "@/lib/repo/types";
import { timecode } from "./timeline/Lineal";

interface Props {
  /* Die Stelle, an der der Abspielkopf steht, in QUELLZEIT. Dieselbe Zeitrechnung wie in der
   * Timeline und wie im Renderer: eine Marke zeigt auf eine Stelle im Video. */
  zeit: number;
  shots: RenderShot[];
  zeitmarken: Zeitmarke[];
  onMarke: (marke: Zeitmarke) => void;
  onMarkeWeg: (abS: number) => void;
  /* Nur die Vorschau nachführen, ohne zu speichern und ohne einen Schritt im Verlauf. Gebraucht
   * beim Ziehen am Regler: sonst entstünde auf dem Weg von 1,0 nach 1,6 ein Dutzend
   * Speichervorgänge, und „Rückgängig" führte zwölfmal zurück durch dieselbe Bewegung.
   *
   * Null heisst: Entwurf verwerfen, es gilt wieder der gespeicherte Stand. */
  onVorschau?: (marke: Zeitmarke | null) => void;
  quelleBreite: number | null;
  canEdit: boolean;
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

/* Wie nah, frei einstellbar.
 *
 * Hier standen drei feste Stufen, mit dem Argument, dazwischen gebe es nichts zu sehen. Das
 * stimmt bei einer Rednerin am Pult, aber nicht bei einer Person, die sich bewegt: wie nah man
 * herangehen kann, ohne den Kopf anzuschneiden, haengt am Bild und nicht an drei Zahlen. Wer den
 * Ausschnitt setzt, sieht das Ergebnis links in der Vorschau und entscheidet nach dem Bild.
 *
 * Die Grenzen spiegeln tracking.ZOOM_MIN / ZOOM_MAX. Unter 1,0 gaebe es keine Bildpunkte mehr,
 * ueber 1,8 wird auch aus einer 4K-Quelle Matsch. */
export const NAEHE_MIN = 1.0;
export const NAEHE_MAX = 1.8;
export const NAEHE_SCHRITT = 0.05;

/* Die Zahl in Worten, die jemand ohne Kamerawissen versteht. „1,35×" sagt nichts; „35 Prozent
 * naeher" schon. */
export function naeheName(zoom: number): string {
  const prozent = Math.round((zoom - 1) * 100);
  if (prozent <= 0) return "Normal";
  return `${prozent} Prozent näher`;
}

/* Dieselbe Angabe kurz, für die Beschriftung eines Timeline-Abschnitts. Dort ist Platz für ein
 * paar Zeichen, nicht für einen Satz. */
export function naeheKurz(zoom: number): string {
  const prozent = Math.round((zoom - 1) * 100);
  return prozent <= 0 ? "normal" : `${prozent} % näher`;
}

/* Was an der Stelle des Abspielkopfs für den Bildausschnitt gilt, und was man daran ändert.
 *
 * Die Zeitspur steht in der Timeline unter der Seite. Hier stehen nur die Entscheidungen: wer im
 * Bild ist, wie nah, und ob beide zugleich. Eine Änderung schreibt eine Marke an der Stelle des
 * Abspielkopfs; in der Timeline ist sie danach als eigener Abschnitt zu sehen. */
export function Bildausschnitt({ zeit, shots, zeitmarken, onMarke, onMarkeWeg, onVorschau, quelleBreite, canEdit }: Props) {
  const naeheId = useId();
  /* Der Regler, solange gezogen wird. Null heisst: es gilt, was gespeichert ist.
   *
   * ``von`` ist der Wert beim ERSTEN Ziehen, also der gespeicherte. Gebraucht wird er beim
   * Loslassen: der laufende Vergleichswert taugt dafür nicht, weil die Vorschau ihn mitzieht.
   * Genau daran ist eine erste Fassung gescheitert - beim Loslassen stimmten Regler und Vorschau
   * überein, der Vergleich hielt das für „nichts geändert", und gespeichert wurde nie. */
  const [entwurf, setEntwurf] = useState<{ von: number; wert: number } | null>(null);
  const aktiverShot = useMemo(() => shots.find((s) => zeit >= s.start && zeit < s.end) ?? null, [shots, zeit]);
  const auswahl = useMemo(() => [...(aktiverShot?.auswahl ?? [])].sort((a, b) => a - b), [aktiverShot]);
  const markeHier = useMemo(() => zeitmarken.find((m) => Math.abs(m.ab_s - zeit) < 0.35) ?? null, [zeitmarken, zeit]);

  /* Was gilt hier gerade? Eine gesetzte Marke schlaegt den Plan; ohne Marke zeigt der Plan, was die
   * Automatik entschieden hat. */
  /* Die laufende Pause, nach der gespeichert wird. */
  const uhr = useRef<number | null>(null);

  const gueltig = useMemo(() => {
    const davor = [...zeitmarken].filter((m) => m.ab_s <= zeit + 1e-6).sort((a, b) => a.ab_s - b.ab_s).pop();
    return {
      x: davor?.x ?? aktiverShot?.quelle_x ?? null,
      zoom: davor?.zoom ?? aktiverShot?.zoom ?? 1.0,
      geteilt: (davor?.layout ?? (aktiverShot?.layout === "geteilt" ? "geteilt" : "einzel")) === "geteilt",
      vonHand: davor != null,
    };
  }, [zeitmarken, zeit, aktiverShot]);

  /* Jede Aenderung schreibt eine VOLLSTAENDIGE Marke. Sonst haengt das Ergebnis davon ab, in
   * welcher Reihenfolge jemand die Knoepfe gedrueckt hat, und „ab hier sieht es so aus" waere
   * nicht mehr wahr. */
  const vollstaendigeMarke = (): Zeitmarke => ({
    ab_s: Math.round(zeit * 100) / 100,
    ...(gueltig.x != null ? { x: Math.round(gueltig.x) } : {}),
    zoom: gueltig.zoom,
    layout: gueltig.geteilt ? "geteilt" : "einzel",
  });

  const setzen = (teil: Partial<Zeitmarke>) => {
    setEntwurf(null);
    onMarke({ ...vollstaendigeMarke(), ...teil });
  };

  /* Was der Regler gerade zeigt: beim Ziehen der Entwurf, sonst der gespeicherte Stand. */
  const gezeigteNaehe = entwurf?.wert ?? gueltig.zoom;

  /* Gespeichert wird nach einer kurzen Pause, nicht bei einem bestimmten Ereignis.
   *
   * Zwei Versuche davor sind gescheitert, und beide Male aus demselben Grund: es gibt kein
   * Ereignis, das bei ALLEN Bedienarten genau einmal am Ende feuert. ``pointerup`` verpasst
   * Tastatur und Finger. Das native ``change`` feuert bei der Maus einmal am Ende, bei jedem
   * Pfeiltastendruck aber sofort - sechs Tastendrücke wurden zu sechs Speichervorgängen und zu
   * sechs Schritten im Rückgängig-Verlauf, mit einem Wettlauf zwischen Anzeige und Antwort.
   *
   * Eine Pause von 400 ms kennt diesen Unterschied nicht: sie beendet jede Geste gleich, ob
   * gezogen, getippt oder gewischt wurde. */
  const ziehen = (wert: number) => {
    setEntwurf((e) => ({ von: e?.von ?? gueltig.zoom, wert }));
    onVorschau?.({ ...vollstaendigeMarke(), zoom: wert });
    if (uhr.current) window.clearTimeout(uhr.current);
    uhr.current = window.setTimeout(() => uebernehmenRef.current(), 400);
  };

  const uebernehmen = () => {
    if (uhr.current) {
      window.clearTimeout(uhr.current);
      uhr.current = null;
    }
    if (entwurf == null) return;
    const { von, wert } = entwurf;
    setEntwurf(null);
    if (Math.abs(wert - von) < 1e-6) {
      /* Hin und wieder zurückgezogen: dann ist nichts zu speichern. Die Vorschau muss aber
       * aufgeräumt werden - sie trägt sonst eine von Hand gesetzte Marke, die es nirgends gibt,
       * und die Seite behauptete „von Hand gesetzt" für etwas, das nach dem Neuladen weg ist. */
      onVorschau?.(null);
      return;
    }
    onMarke({ ...vollstaendigeMarke(), zoom: wert });
  };

  /* Die Pause ruft immer die neueste Fassung auf, nicht die aus dem Moment des Setzens. */
  const uebernehmenRef = useRef(uebernehmen);
  useEffect(() => {
    uebernehmenRef.current = uebernehmen;
  });

  /* Wer die Seite verlässt, während die Pause läuft, hätte sonst eine Änderung verloren. */
  useEffect(
    () => () => {
      if (uhr.current) window.clearTimeout(uhr.current);
    },
    [],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Bildausschnitt</h2>
        <p className="text-sm text-text-2">Wer wie nah im Bild ist</p>
      </div>

      <div className="flex flex-col gap-4 rounded-inner border border-line bg-black/20 p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-medium text-text">Ab {timecode(zeit)} gilt</p>
          <p className="text-sm text-text-3">Stelle in der Timeline wählen</p>
        </div>

        {!canEdit && <p className="text-sm text-text-2">Du kannst hier nur ansehen.</p>}

        {canEdit && (
          <>
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

            {/* Ein Regler statt drei Knoepfen. Waehrend des Ziehens wird nur die Vorschau
                nachgefuehrt; gespeichert wird beim Loslassen. Sonst entstuenden auf dem Weg von
                1,0 nach 1,6 ein Dutzend Speichervorgaenge und ebenso viele Schritte im
                Rueckgaengig-Verlauf. */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-3">
                <label htmlFor={naeheId} className="text-xs uppercase tracking-wide text-text-3">
                  Wie nah
                </label>
                <span className="text-sm tabular-nums text-text">{naeheName(gezeigteNaehe)}</span>
              </div>
              <input
                id={naeheId}
                type="range"
                min={NAEHE_MIN}
                max={NAEHE_MAX}
                step={NAEHE_SCHRITT}
                value={gezeigteNaehe}
                disabled={!canEdit}
                onChange={(e) => ziehen(Number(e.target.value))}
                onBlur={() => uebernehmen()}
                className="w-full accent-white disabled:opacity-60"
              />
              {gezeigteNaehe > NAEHE_MIN && canEdit && (
                <button
                  type="button"
                  onClick={() => {
                    setEntwurf(null);
                    setzen({ zoom: NAEHE_MIN });
                  }}
                  className="self-start text-xs text-text-3 underline underline-offset-4 hover:text-text"
                >
                  Zurück auf Normal
                </button>
              )}
            </div>

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
              {markeHier
                ? "Von hier an von Hand gesetzt."
                : gueltig.vonHand
                  ? "Gilt von einer früheren Stelle."
                  : "Die Automatik entscheidet."}
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
          </>
        )}
      </div>
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
  const zoom = marke.zoom ?? 1;
  if (zoom > 1.001) teile.push(naeheKurz(zoom));
  return teile.length ? teile.join(", ") : "Von Hand";
}
