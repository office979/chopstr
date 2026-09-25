"use client";

import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { standSatz, vorschauStand, type StandEingabe } from "@/lib/clips/vorschau-stand";

interface Props extends StandEingabe {
  sourceId: string;
  clipId: string;
  canEdit: boolean;
  /* Untertitel, die über den sicheren Bereich hinausragen würden. Geclippt wird trotzdem, aber
   * nicht stillschweigend: ein Video, das gleich wieder nachgebessert werden muss, soll nicht
   * kommentarlos aus der Maschine kommen. */
  offeneUntertitel: number;
  /* Wird nach einem angestoßenen Lauf gerufen, damit die Seite den neuen Stand holt. */
  onNeuGebaut: () => void;
  /* Kurzform für direkt unter der Vorschau: eine Zeile und höchstens ein Knopf. Die ausführliche
   * Fassung steht im Bereich „Fertigstellen". Zwei Fassungen derselben Karte, weil die lange
   * Fassung unter dem Video ein Drittel des Platzes einnahm, der dem Video gehört. */
  kompakt?: boolean;
  /* Führt in den Bereich, in dem die ausführliche Fassung steht. Nur in der Kurzform. */
  onMehr?: () => void;
}

/* Gibt es ein geclipptes Video, und wie steht es darum?
 *
 * Hier stand einmal „Video ist nicht auf dem neuesten Stand" samt Knopf „Video mit deinen
 * Änderungen neu clippen". Beides ist weg. Speichern clippt sofort neu und überschreibt das Alte,
 * also kann es den Zwischenzustand gar nicht mehr geben - und ein Knopf, der etwas anbietet, was
 * das Speichern schon erledigt hat, ist eine Einladung zur Verwirrung.
 *
 * Geblieben sind vier Zustände und genau zwei Knöpfe: der erste Lauf („Video clippen") und der
 * zweite Versuch nach einem Fehlschlag („Nochmal versuchen").
 */
export function VorschauStatus({
  sourceId,
  clipId,
  canEdit,
  offeneUntertitel,
  onNeuGebaut,
  kompakt = false,
  onMehr,
  ...stand
}: Props) {
  const [laeuft, setLaeuft] = useState(false);
  const [fortschritt, setFortschritt] = useState<number | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  const zustand = laeuft ? "laeuft" : vorschauStand(stand);

  /* Solange geclippt wird, kommt der Fortschritt über denselben Ereignisstrom, den auch die
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

  const clippen = async () => {
    setFehler(null);
    setLaeuft(true);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/render`, { method: "POST" });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error ?? "Das Clippen konnte nicht gestartet werden");
    } catch (err) {
      setLaeuft(false);
      setFehler(err instanceof Error ? err.message : "Das Clippen konnte nicht gestartet werden");
    }
  };

  /* Ein Knopf nur dort, wo es ohne ihn nicht weitergeht: es gibt noch gar kein Video, oder der
   * letzte Lauf ist gescheitert. Am fertigen Video gibt es nichts anzustoßen - dafür ist
   * „Speichern" da, und das clippt von selbst neu. */
  const knopf = canEdit && (zustand === "keine" || zustand === "fehler");
  const satz = fehler ?? standSatz(zustand);
  const tonFarbe = zustand === "aktuell" ? "text-text" : zustand === "fehler" || fehler ? "text-attention" : "text-text-2";

  /* Die Kurzform: Punkt, ein Satz, höchstens ein Knopf. Mehr passt unter ein Video nicht, ohne
   * dass das Video kleiner wird. */
  if (kompakt) {
    return (
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-2 rounded-inner border px-3 py-2",
          zustand === "fehler" || fehler ? "border-attention/50 bg-attention/10" : "border-line",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Punkt zustand={fehler ? "fehler" : zustand} />
          <span className="truncate text-sm text-text">{ÜBERSCHRIFT[fehler ? "fehler" : zustand]}</span>
        </span>
        {knopf && (
          <Button
            size="sm"
            variant={zustand === "fehler" ? "primary" : "ghost"}
            onClick={() => (onMehr ? onMehr() : void clippen())}
          >
            {zustand === "keine" ? "Video clippen" : "Nochmal versuchen"}
          </Button>
        )}
        {zustand === "laeuft" && (
          <span className="text-sm tabular-nums text-text-2">
            {fortschritt != null ? `${Math.round(fortschritt * 100)} Prozent` : "läuft"}
          </span>
        )}
      </div>
    );
  }

  return (
    <GlassCard padding="md">
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
          {zustand === "laeuft" && <p className="text-sm text-text-2">Du kannst weiterarbeiten, das läuft im Hintergrund.</p>}
          {zustand === "aktuell" && offeneUntertitel === 0 && (
            <p className="text-sm text-text-2">Der Download in der Clip-Übersicht enthält genau diese Fassung.</p>
          )}
          {/* Ein Hinweis, der nach dem Clippen bleibt: sonst stünde „fertig" über einem Video, in
              dem ein Wort über den Rand ragt. */}
          {offeneUntertitel > 0 && zustand !== "laeuft" && (
            <p className="text-sm text-attention">
              {offeneUntertitel === 1
                ? "Ein Untertitel ragt über den sicheren Bereich hinaus."
                : `${offeneUntertitel} Untertitel ragen über den sicheren Bereich hinaus.`}{" "}
              Bei den Untertiteln steht ein Knopf, der das auflöst.
            </p>
          )}
        </div>
        {knopf && (
          <Button variant={zustand === "fehler" ? "primary" : "ghost"} onClick={() => void clippen()}>
            {zustand === "keine" ? "Video clippen" : "Nochmal versuchen"}
          </Button>
        )}
      </div>
    </GlassCard>
  );
}

/* Die vier Zustände, die auseinandergehalten werden müssen:
 *   keine    es gibt noch keine Datei
 *   laeuft   sie entsteht gerade
 *   aktuell  sie ist da und zeigt genau das, was eingestellt ist
 *   fehler   der Lauf ist gescheitert */
const ÜBERSCHRIFT: Record<string, string> = {
  keine: "Noch nicht geclippt",
  laeuft: "Video wird geclippt",
  aktuell: "Video ist fertig",
  fehler: "Das Clippen hat nicht geklappt",
};

/* Ein farbiger Punkt. Vier Zustände, die man auseinanderhalten muss, lassen sich schneller sehen
 * als lesen; der Text daneben bleibt trotzdem die Aussage. */
function Punkt({ zustand }: { zustand: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block h-2.5 w-2.5 shrink-0 rounded-full",
        zustand === "aktuell" && "bg-brand",
        zustand === "laeuft" && "animate-pulse bg-white/70",
        zustand === "keine" && "bg-white/35",
        zustand === "fehler" && "bg-danger",
      )}
    />
  );
}
