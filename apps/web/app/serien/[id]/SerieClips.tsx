"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import { PLATFORM_LABELS, formatClipDuration } from "@/lib/clips/labels";
import { FEATURE_LABELS, type VariationResult } from "@/lib/series/variation";
import { REDAKTION_LABEL, type Pruefstand } from "@/lib/clips/pruefstand";
import { formatDateTime } from "@/lib/format";

export interface SerienClip {
  id: string;
  sourceId: string;
  projekt: string;
  plattform: string;
  dauerS: number | null;
  slot: number | null;
  geaendert: string;
  /* Derselbe Prüfstand wie in der Clip-Übersicht, damit dieselbe Sache überall gleich heisst. */
  stand: Pruefstand;
}

interface Props {
  serieId: string;
  serieName: string;
  zugeordnet: SerienClip[];
  /* Gebaute Clips, die noch nicht in dieser Serie sind. */
  zurWahl: SerienClip[];
  canEdit: boolean;
}

interface ApiError {
  error?: string;
}

/* Die Clips einer Serie: zuordnen, lösen, Zustand sehen.
 *
 * Vorher ging das Zuordnen nur über die Clip-Karte im Projekt. Wer eine Serie füllen wollte,
 * musste also wissen, in welchem Projekt der passende Clip liegt - genau andersherum, als man
 * denkt. Hier steht die Serie im Mittelpunkt und die Clips kommen dazu.
 */
export function SerieClips({ serieId, serieName, zugeordnet, zurWahl, canEdit }: Props) {
  const [clips, setClips] = useState(zugeordnet);
  const [wahl, setWahl] = useState(zurWahl);
  const [offen, setOffen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [meldung, setMeldung] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [warnung, setWarnung] = useState<{ clip: SerienClip; ergebnis: VariationResult } | null>(null);

  const zuordnen = useCallback(
    async (clip: SerienClip, trotzdem = false) => {
      setBusy(clip.id);
      setMeldung(null);
      try {
        const res = await fetch(`/api/series/${serieId}/assign`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clip_id: clip.id, confirm: trotzdem }),
        });
        const data = (await res.json()) as ApiError & { ok?: boolean; warning?: VariationResult };
        if (!res.ok) throw new Error(data.error ?? "Zuordnen hat nicht geklappt");
        if (!data.ok && data.warning) {
          setWarnung({ clip, ergebnis: data.warning });
          return;
        }
        setClips((prev) => [...prev, clip]);
        setWahl((prev) => prev.filter((c) => c.id !== clip.id));
        setWarnung(null);
        setMeldung({ tone: "ok", text: `Clip zu „${serieName}" hinzugefügt.` });
      } catch (err) {
        setMeldung({ tone: "error", text: err instanceof Error ? err.message : "Zuordnen hat nicht geklappt" });
      } finally {
        setBusy(null);
      }
    },
    [serieId, serieName],
  );

  const loesen = useCallback(
    async (clip: SerienClip) => {
      setBusy(clip.id);
      setMeldung(null);
      try {
        const res = await fetch(`/api/series/${serieId}/assign`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clip_id: clip.id, remove: true }),
        });
        const data = (await res.json()) as ApiError;
        if (!res.ok) throw new Error(data.error ?? "Lösen hat nicht geklappt");
        setClips((prev) => prev.filter((c) => c.id !== clip.id));
        setWahl((prev) => [clip, ...prev]);
        setMeldung({ tone: "ok", text: "Clip aus der Serie genommen. Der Clip selbst bleibt, wie er ist." });
      } catch (err) {
        setMeldung({ tone: "error", text: err instanceof Error ? err.message : "Lösen hat nicht geklappt" });
      } finally {
        setBusy(null);
      }
    },
    [serieId],
  );

  return (
    <GlassCard padding="lg" className="mt-5 flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">Clips dieser Serie</h2>
          <p className="mt-0.5 text-sm text-text-2">
            {clips.length === 0
              ? "Noch keiner zugeordnet."
              : `${clips.length} ${clips.length === 1 ? "Clip" : "Clips"}, sortiert nach Platz in der Serie.`}
          </p>
        </div>
        {canEdit && (
          <Button size="sm" onClick={() => setOffen(true)} disabled={wahl.length === 0}>
            {wahl.length === 0 ? "Keine freien Clips" : "Clip hinzufügen"}
          </Button>
        )}
      </div>

      {meldung && (
        <p
          role="status"
          aria-live="polite"
          className={cn(
            "rounded-inner border px-4 py-3 text-sm",
            meldung.tone === "ok" ? "border-line text-text" : "border-attention/50 bg-attention/10 text-text",
          )}
        >
          {meldung.text}
        </p>
      )}

      {clips.length === 0 ? (
        <p className="text-sm text-text-2">
          Füge Clips hinzu, die in dieses Format gehören. Ein Clip kann in genau einer Serie sein.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {clips.map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-inner border border-line px-4 py-3"
            >
              <div className="min-w-0">
                <Link href={`/projekte/${c.sourceId}/clips/${c.id}`} className="text-sm font-medium text-text hover:underline">
                  {c.projekt}
                </Link>
                <p className="mt-0.5 text-xs text-text-2">
                  Platz {c.slot ?? "offen"} · {PLATFORM_LABELS[c.plattform as keyof typeof PLATFORM_LABELS] ?? c.plattform} ·{" "}
                  {formatClipDuration(c.dauerS)} · zuletzt {formatDateTime(c.geaendert)}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {/* Derselbe Zustand wie in der Clip-Übersicht: Bearbeitungsstand und Freigabe in
                    einem Wort. Vorher stand hier der technische Renderstand. */}
                <span
                  className={cn(
                    "inline-flex h-6 items-center rounded-pill border px-2.5 text-[12px] font-medium",
                    c.stand.postbereit && "border-brand/60 bg-brand/15 text-text",
                    !c.stand.postbereit && c.stand.qualitaet === "fehler" && "border-danger/60 bg-danger/15 text-text",
                    !c.stand.postbereit && c.stand.qualitaet !== "fehler" && c.stand.datei === "fehlgeschlagen" && "border-attention/60 bg-attention/15 text-text",
                    !c.stand.postbereit && c.stand.qualitaet !== "fehler" && c.stand.datei !== "fehlgeschlagen" && "border-line text-text-2",
                  )}
                >
                  {c.stand.postbereit ? "Bereit zum Posten" : REDAKTION_LABEL[c.stand.redaktion]}
                </span>
                {canEdit && (
                  <Button size="sm" variant="ghost" disabled={busy === c.id} onClick={() => void loesen(c)}>
                    Aus der Serie nehmen
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <Modal
        open={offen}
        onClose={() => setOffen(false)}
        title="Clip zu dieser Serie hinzufügen"
        description="Nur fertig geclippte Clips. Gehört die Serie zu einer Marke, stehen auch nur deren Clips hier."
        className="max-w-[640px]"
      >
        <ul className="flex max-h-[60dvh] flex-col gap-2 overflow-y-auto">
          {wahl.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 rounded-inner border border-line px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm text-text">{c.projekt}</p>
                <p className="mt-0.5 text-xs text-text-2">
                  {PLATFORM_LABELS[c.plattform as keyof typeof PLATFORM_LABELS] ?? c.plattform} ·{" "}
                  {formatClipDuration(c.dauerS)} · {REDAKTION_LABEL[c.stand.redaktion]}
                </p>
              </div>
              <Button size="sm" variant="ghost" disabled={busy === c.id} onClick={() => void zuordnen(c)}>
                Hinzufügen
              </Button>
            </li>
          ))}
        </ul>
      </Modal>

      {/* Die Ähnlichkeitswarnung. Sie kommt aus einem echten Vergleich mit den letzten neun Clips
          der Serie und nennt, worin sie sich gleichen. Zwei Wege heraus: trotzdem nehmen oder
          einen anderen Clip aussuchen. */}
      <Modal
        open={warnung != null}
        onClose={() => setWarnung(null)}
        title="Dieser Clip ähnelt den letzten sehr"
        description="Eine Serie lebt von Abwechslung. Das hier ist ein Hinweis, keine Sperre."
      >
        <div className="flex flex-col gap-4">
          <p className="text-sm text-text-2">Gleich sind:</p>
          <ul className="flex flex-col gap-1.5">
            {warnung?.ergebnis.hits.map((h, i) => (
              <li key={i} className="text-sm text-text">
                {h.matches.map((f) => FEATURE_LABELS[f]).join(", ")}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setWarnung(null);
                setOffen(true);
              }}
            >
              Anderen Clip ansehen
            </Button>
            <Button onClick={() => warnung && void zuordnen(warnung.clip, true)} disabled={busy != null}>
              Trotzdem verwenden
            </Button>
          </div>
        </div>
      </Modal>
    </GlassCard>
  );
}
