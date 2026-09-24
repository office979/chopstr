"use client";

import { useMemo } from "react";
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

/* Drei Stufen statt eines Schiebereglers. „Wie nah?" hat keine sinnvolle Zwischenstufe: entweder
 * das Bild steht wie es ist, oder es geht spuerbar naeher heran. Ein Regler von 1,0 bis 1,8 laedt
 * dazu ein, 1,07 einzustellen, und das sieht niemand. */
export const NAEHE = [
  { id: 1.0, name: "Normal" },
  { id: 1.3, name: "Näher" },
  { id: 1.6, name: "Ganz nah" },
] as const;

/* Was an der Stelle des Abspielkopfs für den Bildausschnitt gilt, und was man daran ändert.
 *
 * Die Zeitspur steht in der Timeline unter der Seite. Hier stehen nur die Entscheidungen: wer im
 * Bild ist, wie nah, und ob beide zugleich. Eine Änderung schreibt eine Marke an der Stelle des
 * Abspielkopfs; in der Timeline ist sie danach als eigener Abschnitt zu sehen. */
export function Bildausschnitt({ zeit, shots, zeitmarken, onMarke, onMarkeWeg, quelleBreite, canEdit }: Props) {
  const aktiverShot = useMemo(() => shots.find((s) => zeit >= s.start && zeit < s.end) ?? null, [shots, zeit]);
  const auswahl = useMemo(() => [...(aktiverShot?.auswahl ?? [])].sort((a, b) => a - b), [aktiverShot]);
  const markeHier = useMemo(() => zeitmarken.find((m) => Math.abs(m.ab_s - zeit) < 0.35) ?? null, [zeitmarken, zeit]);

  /* Was gilt hier gerade? Eine gesetzte Marke schlaegt den Plan; ohne Marke zeigt der Plan, was die
   * Automatik entschieden hat. */
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
  const setzen = (teil: Partial<Zeitmarke>) => {
    onMarke({
      ab_s: Math.round(zeit * 100) / 100,
      ...(gueltig.x != null ? { x: Math.round(gueltig.x) } : {}),
      zoom: gueltig.zoom,
      layout: gueltig.geteilt ? "geteilt" : "einzel",
      ...teil,
    });
  };

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
  const n = NAEHE.find((x) => Math.abs(x.id - (marke.zoom ?? 1)) < 0.05);
  if (n && n.id > 1) teile.push(n.name.toLowerCase());
  return teile.length ? teile.join(", ") : "Von Hand";
}
