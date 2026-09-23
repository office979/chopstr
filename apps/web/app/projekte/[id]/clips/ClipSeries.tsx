"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import type { ClipExtras, Series } from "@/lib/repo/types-publishing";
import type { VariationResult } from "@/lib/series/variation";

export interface ClipSeriesProps {
  clipId: string;
  extras: ClipExtras;
  series: Series[];
  onExtras?: (extras: ClipExtras) => void;
}

interface ApiError {
  error?: string;
}

/* Serie zuordnen je Clip. Früher Teil von ClipPublishing; das Posten ist weg, die Zuordnung bleibt. */
export function ClipSeries({ clipId, extras, series, onExtras }: ClipSeriesProps) {
  const [seriesId, setSeriesId] = useState(extras.series_id ?? "");
  const [warning, setWarning] = useState<VariationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; href?: string } | null>(null);
  const selectId = useId();

  const assign = async (targetId: string, force: boolean) => {
    setBusy(true);
    setMessage(null);
    try {
      if (!targetId) {
        if (!extras.series_id) return;
        const res = await fetch(`/api/series/${extras.series_id}/assign`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clip_id: clipId, remove: true }),
        });
        const data = (await res.json()) as ApiError & { extras?: ClipExtras };
        if (!res.ok || !data.extras) throw new Error(data.error ?? "Zuordnung konnte nicht gelöst werden");
        onExtras?.(data.extras);
        setMessage({ tone: "ok", text: "Serien-Zuordnung gelöst." });
        return;
      }
      const res = await fetch(`/api/series/${targetId}/assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_id: clipId, confirm: force }),
      });
      const data = (await res.json()) as ApiError & { ok?: boolean; warning?: VariationResult; extras?: ClipExtras; series?: Series };
      if (!res.ok) throw new Error(data.error ?? "Zuordnung fehlgeschlagen");
      if (!data.ok && data.warning) {
        setWarning(data.warning);
        return;
      }
      if (data.extras) onExtras?.(data.extras);
      setWarning(null);
      setMessage({ tone: "ok", text: `Serie „${data.series?.name ?? ""}“ zugeordnet.`, href: `/serien/${targetId}` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Zuordnung fehlgeschlagen" });
      setSeriesId(extras.series_id ?? "");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <Modal open={warning != null} onClose={() => setWarning(null)} title="Zu ähnlich, Variante ziehen" description={warning?.message ?? undefined}>
        <ul className="mb-4 flex flex-col gap-1 text-sm text-text-2">
          {warning?.hits.map((h) => (
            <li key={h.clip_id}>
              Clip {h.clip_id.slice(0, 8)}: {h.matches.length} gleiche Merkmale
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => {
              setWarning(null);
              setSeriesId(extras.series_id ?? "");
            }}
          >
            Nicht zuordnen
          </Button>
          <Button onClick={() => assign(seriesId, true)} disabled={busy}>
            Trotzdem zuordnen
          </Button>
        </div>
      </Modal>

      <label htmlFor={selectId} className="text-xs text-text-2">
        Serie zuordnen
      </label>
      <Select
        id={selectId}
        value={seriesId}
        onChange={(e) => {
          setSeriesId(e.target.value);
          void assign(e.target.value, false);
        }}
        disabled={busy || series.length === 0}
        className="py-2 text-sm"
      >
        <option value="">{series.length === 0 ? "Noch keine Serie angelegt" : "Keine Serie"}</option>
        {series.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </Select>
      {extras.series_id && (
        <Link href={`/serien/${extras.series_id}`} className="self-start text-[11px] text-text-3 underline-offset-4 hover:text-text hover:underline">
          Slot {extras.series_index ?? "?"} · Kalender öffnen
        </Link>
      )}
      {message && (
        <p role="status" aria-live="polite" className={cn("text-xs", message.tone === "ok" ? "text-text" : "text-attention")}>
          {message.text}
          {message.href && (
            <>
              {" "}
              <Link href={message.href} className="underline-offset-4 hover:underline">
                Öffnen
              </Link>
            </>
          )}
        </p>
      )}
    </div>
  );
}
