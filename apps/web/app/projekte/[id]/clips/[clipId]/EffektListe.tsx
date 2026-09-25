"use client";

import { GlassCard } from "@/components/ui/GlassCard";
import { Select } from "@/components/ui/Field";
import { cn } from "@/components/ui/cn";
import {
  EFFEKT_ARTEN,
  EFFEKT_LABEL,
  EFFEKT_SATZ,
  MAX_DAUER_S,
  MIN_DAUER_S,
  dauerAendern,
  entfernen,
  hinzufuegen,
  type Effekt,
  type EffektArt,
} from "@/lib/clips/effekte";

/* Die Effekte eines Clips.
 *
 * Bewusst eine Liste und nicht ein einzelner Schalter: es werden mehr Effekte dazukommen, und
 * dann steht hier jeder für sich mit seiner eigenen Auswahl. Ein Schalter, der heute „Zoom" heisst
 * und morgen fünf Dinge tut, wäre in beiden Zuständen falsch.
 *
 * Was hier fehlt und absichtlich fehlt: eine Vorschau des Zooms im Player. Die Vorschau zeigt die
 * gebaute Datei, und dort ist der Effekt drin, sobald neu geclippt wurde. Eine zweite, gerechnete
 * Vorschau daneben wäre eine zweite Wahrheit - und genau die Sorte Widerspruch, die dieses Produkt
 * sonst überall ausräumt.
 */
export function EffektListe({
  effekte,
  zeitImClip,
  clipDauer,
  canEdit,
  onAendern,
}: {
  effekte: Effekt[];
  /* Wo der Abspielkopf gerade steht, in Sekunden im fertigen Clip. Dort entsteht ein neuer Effekt. */
  zeitImClip: number;
  clipDauer: number;
  canEdit: boolean;
  onAendern: (naechste: Effekt[]) => void;
}) {
  const passtNoch = clipDauer - zeitImClip >= MIN_DAUER_S;

  return (
    <GlassCard padding="md" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold">Effekte</h3>
        <span className="text-sm text-text-3">Bewegung, die etwas betont</span>
      </div>

      <p className="text-sm text-text-2">
        chopstr setzt sie beim Clippen selbst, dort wo eine Zahl oder eine Ankündigung fällt. Passt
        einer nicht, zieh ihn in der Zeitleiste an eine andere Stelle, mach ihn länger oder nimm ihn
        weg.
      </p>

      {effekte.length === 0 ? (
        <p className="text-sm text-text-3">
          Für diesen Clip sind keine Effekte gesetzt. Beim nächsten Clippen bleibt es dabei.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {effekte.map((e, i) => (
            <li
              key={`${e.art}-${e.ab_s}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-inner border border-line px-3 py-2"
            >
              <div className="w-[150px]">
                <Select
                  aria-label={`Art des Effekts bei ${e.ab_s.toFixed(1)} Sekunden`}
                  value={e.art}
                  disabled={!canEdit}
                  onChange={(ev) => {
                    const art = ev.target.value as EffektArt;
                    onAendern(effekte.map((x, k) => (k === i ? { ...x, art } : x)));
                  }}
                >
                  {EFFEKT_ARTEN.map((a) => (
                    <option key={a} value={a}>
                      {EFFEKT_LABEL[a]}
                    </option>
                  ))}
                </Select>
              </div>

              <span className="font-mono text-xs tabular-nums text-text-2">
                ab {e.ab_s.toFixed(1)} s
              </span>

              <label className="flex items-center gap-2 text-xs text-text-2">
                <span>Dauer</span>
                <input
                  type="range"
                  min={MIN_DAUER_S}
                  max={MAX_DAUER_S}
                  step={0.1}
                  value={e.dauer_s}
                  disabled={!canEdit}
                  aria-label={`Dauer des Effekts bei ${e.ab_s.toFixed(1)} Sekunden`}
                  onChange={(ev) => onAendern(dauerAendern(effekte, i, Number(ev.target.value), clipDauer))}
                  className="w-[120px] accent-white"
                />
                <span className="font-mono tabular-nums text-text">{e.dauer_s.toFixed(1)} s</span>
              </label>

              <span className="min-w-0 flex-1 truncate text-xs text-text-3">{EFFEKT_SATZ[e.art]}</span>

              {canEdit && (
                <button
                  type="button"
                  onClick={() => onAendern(entfernen(effekte, i))}
                  aria-label={`${EFFEKT_LABEL[e.art]} bei ${e.ab_s.toFixed(1)} Sekunden entfernen`}
                  className="transition-soft shrink-0 rounded-pill border border-line px-3 py-1 text-xs text-text-2 hover:border-danger/50 hover:text-danger"
                >
                  Entfernen
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <div className="flex flex-wrap items-center gap-2">
          {EFFEKT_ARTEN.map((a) => (
            <button
              key={a}
              type="button"
              disabled={!passtNoch}
              onClick={() => onAendern(hinzufuegen(effekte, a, Math.round(zeitImClip * 100) / 100, clipDauer))}
              title={EFFEKT_SATZ[a]}
              className={cn(
                "transition-soft rounded-pill border px-3 py-1.5 text-sm",
                passtNoch
                  ? "border-line text-text-2 hover:border-line-strong hover:text-text"
                  : "cursor-not-allowed border-line text-text-3",
              )}
            >
              {EFFEKT_LABEL[a]} hier einsetzen
            </button>
          ))}
          <span className="text-xs text-text-3">
            {passtNoch
              ? "Der Effekt beginnt da, wo der Abspielkopf steht."
              : "So kurz vor dem Ende passt kein Effekt mehr."}
          </span>
        </div>
      )}
    </GlassCard>
  );
}
