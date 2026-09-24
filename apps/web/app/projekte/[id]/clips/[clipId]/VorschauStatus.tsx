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
  /* Untertitel, die über den sicheren Bereich hinausragen würden. Gebaut wird trotzdem, aber
   * nicht stillschweigend: ein Video, das gleich wieder nachgebessert werden muss, soll nicht
   * als „auf dem neuesten Stand" aus der Maschine kommen. */
  offeneUntertitel: number;
  /* Wird nach einem angestoßenen Lauf gerufen, damit die Seite den neuen Stand holt. */
  onNeuGebaut: () => void;
  /* Kurzform für direkt unter der Vorschau: eine Zeile und ein Knopf. Die ausführliche Fassung
   * mit allen Sätzen steht im Bereich „Fertigstellen". Zwei Fassungen derselben Karte, weil die
   * lange Fassung unter dem Video ein Drittel des Platzes einnahm, der dem Video gehört. */
  kompakt?: boolean;
  /* Führt in den Bereich, in dem die ausführliche Fassung steht. Nur in der Kurzform. */
  onMehr?: () => void;
}

/* Was das gebaute Video gerade zeigt, und der Weg zu einem aktuellen.
 *
 * Vorher stand an einer Stelle „Fertig" und an einer anderen „Im Bild sind noch die alten
 * Untertitel", und einen Knopf, das zu ändern, gab es nicht. Hier stehen die drei Zustände
 * getrennt: gespeichert aber alt, wird gerade erstellt, aktuell und bereit.
 */
export function VorschauStatus({
  sourceId,
  clipId,
  canEdit,
  offeneAenderungen,
  offeneUntertitel,
  onNeuGebaut,
  kompakt = false,
  onMehr,
  ...stand
}: Props) {
  const [laeuft, setLaeuft] = useState(false);
  const [nachfrage, setNachfrage] = useState(false);
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
    setNachfrage(false);
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

  const satz = fehler ?? standSatz(zustand, ab);
  const tonFarbe =
    zustand === "aktuell" ? "text-text" : zustand === "fehler" || fehler ? "text-attention" : "text-text-2";

  /* Die Kurzform: Punkt, ein Satz, ein Knopf. Mehr passt unter ein Video nicht, ohne dass das
   * Video kleiner wird. */
  if (kompakt) {
    return (
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-2 rounded-inner border px-3 py-2",
          zustand === "veraltet" || zustand === "fehler" || fehler ? "border-attention/50 bg-attention/10" : "border-line",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Punkt zustand={fehler ? "fehler" : zustand} />
          <span className="truncate text-sm text-text">{ÜBERSCHRIFT[fehler ? "fehler" : zustand]}</span>
        </span>
        {canEdit && zustand !== "aktuell" && zustand !== "laeuft" && (
          <Button
            size="sm"
            variant={zustand === "veraltet" || zustand === "fehler" ? "primary" : "ghost"}
            onClick={() => (onMehr ? onMehr() : void neuBauen())}
            disabled={offeneAenderungen}
          >
            {zustand === "keine" ? "Video clippen" : "Neu clippen"}
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
            <p className="text-sm text-text-2">Speichere erst deine Änderungen, sonst wird der alte Stand geclippt.</p>
          )}
          {zustand === "laeuft" && (
            <p className="text-sm text-text-2">Du kannst weiterarbeiten, das läuft im Hintergrund.</p>
          )}
          {zustand === "aktuell" && offeneUntertitel === 0 && (
            <p className="text-sm text-text-2">Der Download in der Clip-Übersicht enthält genau diese Fassung.</p>
          )}
          {/* Ein Hinweis, der nach dem Bauen bleibt: sonst stünde „auf dem neuesten Stand" über
              einem Video, in dem ein Wort über den Rand ragt. */}
          {offeneUntertitel > 0 && zustand !== "laeuft" && (
            <p className="text-sm text-attention">
              {offeneUntertitel === 1
                ? "Ein Untertitel ragt über den sicheren Bereich hinaus."
                : `${offeneUntertitel} Untertitel ragen über den sicheren Bereich hinaus.`}{" "}
              Bei den Untertiteln steht ein Knopf, der das auflöst.
            </p>
          )}
          {nachfrage && (
            <p className="text-sm text-text-2">
              Clippen dauert ein paar Minuten. Willst du das vorher noch anpassen?
            </p>
          )}
        </div>
        {canEdit && zustand !== "aktuell" && (
          <div className="flex flex-wrap items-center gap-2">
            {nachfrage && (
              <Button variant="ghost" onClick={() => setNachfrage(false)}>
                Erst anpassen
              </Button>
            )}
            <Button
              variant={zustand === "veraltet" || zustand === "fehler" ? "primary" : "ghost"}
              onClick={() => {
                if (offeneUntertitel > 0 && !nachfrage) {
                  setNachfrage(true);
                  return;
                }
                void neuBauen();
              }}
              disabled={zustand === "laeuft" || offeneAenderungen}
            >
              {nachfrage
                ? "Trotzdem clippen"
                : zustand === "laeuft"
                  ? "Wird geclippt"
                  : zustand === "fehler"
                    ? "Nochmal versuchen"
                    : zustand === "keine"
                      ? "Video clippen"
                      : "Video mit deinen Änderungen neu clippen"}
            </Button>
          </div>
        )}
      </div>
    </GlassCard>
  );
}

/* Die drei Zustände, die auseinandergehalten werden müssen, in den Worten der Sache:
 *   keine     es gibt noch keine Datei
 *   veraltet  es gibt eine, aber sie kennt deine Änderungen nicht
 *   aktuell   die Datei entspricht genau dem, was eingestellt ist - nur dann gibt es sie zum
 *             Herunterladen */
const ÜBERSCHRIFT: Record<string, string> = {
  keine: "Noch nicht geclippt",
  laeuft: "Video wird geclippt",
  veraltet: "Video ist nicht auf dem neuesten Stand",
  aktuell: "Video ist auf dem neuesten Stand",
  fehler: "Das Clippen hat nicht geklappt",
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
