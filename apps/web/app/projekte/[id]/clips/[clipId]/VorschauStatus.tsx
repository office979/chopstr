"use client";

import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { standSatz, vorschauStand, wasAbweicht, type StandEingabe } from "@/lib/clips/vorschau-stand";

interface Props extends StandEingabe {
  sourceId: string;
  clipId: string;
  canEdit: boolean;
  /* Es gibt noch nicht gespeicherte Änderungen. Dann ist Neu-Bauen sinnlos: gebaut würde der
   * gespeicherte Stand, und der Nutzer sähe seine Änderung wieder nicht. */
  offeneAenderungen: boolean;
  /* Wird nach einem angestoßenen Lauf gerufen, damit die Seite den neuen Stand holt. */
  onNeuGebaut: () => void;
}

/* Was das gebaute Video gerade zeigt, und der Weg zu einem aktuellen.
 *
 * Vorher stand an einer Stelle „Fertig" und an einer anderen „Im Bild sind noch die alten
 * Untertitel", und einen Knopf, das zu ändern, gab es nicht. Hier stehen die drei Zustände
 * getrennt: gespeichert aber alt, wird gerade erstellt, aktuell und bereit.
 */
export function VorschauStatus({ sourceId, clipId, canEdit, offeneAenderungen, onNeuGebaut, ...stand }: Props) {
  const [laeuft, setLaeuft] = useState(false);
  const [fortschritt, setFortschritt] = useState<number | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  const zustand = laeuft ? "laeuft" : vorschauStand(stand);
  const ab = wasAbweicht(stand);

  /* Solange gebaut wird, kommt der Fortschritt über denselben Ereignisstrom, den auch die
   * Clip-Übersicht liest. Ohne ihn stünde hier ein Text, der sich nie ändert. */
  useEffect(() => {
    if (zustand !== "laeuft") return undefined;
    const es = new EventSource(`/api/projects/${sourceId}/clips/events`);
    const lesen = (msg: MessageEvent) => {
      try {
        const d = JSON.parse(msg.data) as { payload?: { clip_id?: string }; progress?: number | null; status?: string };
        if (d.payload?.clip_id !== clipId) return;
        if (typeof d.progress === "number") setFortschritt(d.progress);
        if (d.status === "finished" || d.status === "failed") {
          setLaeuft(false);
          setFortschritt(null);
          onNeuGebaut();
        }
      } catch {
        /* Ein unlesbares Ereignis ist kein Grund, die Seite zu stören. */
      }
    };
    es.addEventListener("render", lesen);
    return () => es.close();
  }, [zustand, sourceId, clipId, onNeuGebaut]);

  const neuBauen = async () => {
    setFehler(null);
    setLaeuft(true);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/render`, { method: "POST" });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error ?? "Das Erstellen konnte nicht gestartet werden");
    } catch (err) {
      setLaeuft(false);
      setFehler(err instanceof Error ? err.message : "Das Erstellen konnte nicht gestartet werden");
    }
  };

  const satz = fehler ?? standSatz(zustand, ab);
  const tonFarbe =
    zustand === "aktuell" ? "text-text" : zustand === "fehler" || fehler ? "text-attention" : "text-text-2";

  return (
    <GlassCard padding="md" selected={zustand === "veraltet"}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <Punkt zustand={fehler ? "fehler" : zustand} />
            <p className="text-sm font-medium text-text">{ÜBERSCHRIFT[fehler ? "fehler" : zustand]}</p>
          </div>
          <p className={cn("text-sm", tonFarbe)} role="status" aria-live="polite">
            {satz}
            {zustand === "laeuft" && fortschritt != null && ` ${Math.round(fortschritt * 100)} Prozent.`}
          </p>
          {stand.status === "failed" && stand.renderFehler && !fehler && (
            <p className="text-sm text-text-2">{stand.renderFehler}</p>
          )}
          {offeneAenderungen && zustand !== "laeuft" && (
            <p className="text-sm text-text-2">Speichere erst deine Änderungen, sonst wird der alte Stand gebaut.</p>
          )}
        </div>
        {canEdit && zustand !== "aktuell" && (
          <Button
            variant={zustand === "veraltet" || zustand === "fehler" ? "primary" : "ghost"}
            onClick={() => void neuBauen()}
            disabled={zustand === "laeuft" || offeneAenderungen}
          >
            {zustand === "laeuft" ? "Wird erstellt" : zustand === "fehler" ? "Nochmal versuchen" : "Vorschau neu erstellen"}
          </Button>
        )}
      </div>
    </GlassCard>
  );
}

const ÜBERSCHRIFT: Record<string, string> = {
  keine: "Noch nicht gebaut",
  laeuft: "Vorschau wird aktualisiert",
  veraltet: "Änderung gespeichert",
  aktuell: "Aktuelle Vorschau bereit",
  fehler: "Das hat nicht geklappt",
};

/* Ein farbiger Punkt. Drei Zustände, die man auseinanderhalten muss, lassen sich schneller sehen
 * als lesen; der Text daneben bleibt trotzdem die Aussage. */
function Punkt({ zustand }: { zustand: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block h-2.5 w-2.5 shrink-0 rounded-full",
        zustand === "aktuell" && "bg-brand",
        zustand === "veraltet" && "bg-attention",
        zustand === "laeuft" && "animate-pulse bg-white/70",
        zustand === "keine" && "bg-white/35",
        zustand === "fehler" && "bg-danger",
      )}
    />
  );
}
