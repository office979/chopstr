"use client";

import { useId, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Select } from "@/components/ui/Field";
import { EFFEKT_ARTEN, EFFEKT_LABEL, EFFEKT_SATZ, MIN_DAUER_S, hinzufuegen, type Effekt, type EffektArt } from "@/lib/clips/effekte";

/* Effekte anlegen. Mehr nicht.
 *
 * Hier stand vorher eine Liste mit Reglern: jeder Effekt mit Dauer, Beschreibung und einem Knopf
 * zum Entfernen. Das war die Zeitleiste ein zweites Mal, nur ohne Zeitachse - und die Zeitleiste
 * kann es besser, weil man dort SIEHT, wo der Effekt liegt.
 *
 * Also bleibt hier die eine Sache, die in der Zeitleiste nicht geht: einen neuen anlegen.
 * Verschieben, länger machen und entfernen passiert dort, wo der Effekt liegt.
 */
export function EffektListe({
  effekte,
  zeitImClip,
  clipDauer,
  canEdit,
  onAendern,
}: {
  effekte: Effekt[];
  /* Wo der Abspielkopf steht, in Sekunden im fertigen Clip. Dort entsteht der neue Effekt. */
  zeitImClip: number;
  clipDauer: number;
  canEdit: boolean;
  onAendern: (naechste: Effekt[]) => void;
}) {
  const id = useId();
  const [wahl, setWahl] = useState<"" | EffektArt>("");
  const passtNoch = clipDauer - zeitImClip >= MIN_DAUER_S;

  return (
    <GlassCard padding="md" className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-base font-semibold">Zoom Effekte</h3>
        <p className="mt-0.5 text-sm text-text-2">
          {canEdit
            ? passtNoch
              ? "Der Effekt beginnt da, wo der Abspielkopf steht. Danach in der Zeitleiste ziehen."
              : "So kurz vor dem Ende passt kein Effekt mehr."
            : "Du kannst hier nichts ändern."}
        </p>
      </div>

      {canEdit && (
        <div className="w-[230px] shrink-0">
          <label htmlFor={id} className="sr-only">
            Zoom Effekte
          </label>
          <Select
            id={id}
            value={wahl}
            disabled={!passtNoch}
            onChange={(e) => {
              const art = e.target.value as EffektArt;
              setWahl("");
              if (!art) return;
              onAendern(hinzufuegen(effekte, art, Math.round(zeitImClip * 100) / 100, clipDauer));
            }}
          >
            {/* Die Auswahl fällt sofort auf sich selbst zurück: sie ist ein Menü von Handlungen,
                kein Zustand. Was gewählt wurde, steht danach in der Zeitleiste. */}
            <option value="">Effekt hinzufügen</option>
            {EFFEKT_ARTEN.map((a) => (
              <option key={a} value={a} title={EFFEKT_SATZ[a]}>
                {EFFEKT_LABEL[a]} hinzufügen
              </option>
            ))}
          </Select>
        </div>
      )}
    </GlassCard>
  );
}
