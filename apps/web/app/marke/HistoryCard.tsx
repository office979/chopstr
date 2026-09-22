"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import type { HistoryEntry } from "@/lib/brand/history";
import { formatDateTime } from "@/lib/format";

interface Props {
  profileId: string;
  entries: HistoryEntry[];
  canRestore: boolean;
}

interface ApiResponse {
  error?: string;
  message?: string;
}

/* Historie des Markenprofils: Zeitpunkt, Akteur, geänderte Felder, Wiederherstellen (schreibt wieder einen Snapshot) */
export function HistoryCard({ profileId, entries, canRestore }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState<number | null>(null);
  const [confirmVersion, setConfirmVersion] = useState<number | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const restore = async (version: number) => {
    setBusy(version);
    setMessage(null);
    try {
      const res = await fetch(`/api/brand/${profileId}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version }) });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok) throw new Error(data.error ?? "Wiederherstellen fehlgeschlagen");
      setMessage({ tone: "ok", text: data.message ?? "Wiederhergestellt." });
      setConfirmVersion(null);
      router.refresh();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Wiederherstellen fehlgeschlagen" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <GlassCard padding="lg" className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-medium">Historie</h2>
        <p className="mt-1 text-sm text-text-2">Vor jeder Änderung wird der vorherige Stand gesichert. Wiederherstellen legt selbst wieder einen Eintrag an.</p>
      </div>
      {message && (
        <p role="status" aria-live="polite" className={cn("text-sm", message.tone === "ok" ? "text-text" : "text-attention")}>
          {message.text}
        </p>
      )}
      {entries.length === 0 ? (
        <p className="text-sm text-text-2">Noch keine Änderungen gesichert.</p>
      ) : (
        <ol className="divide-y divide-line">
          {entries.map((e) => (
            <li key={e.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className="h-6 px-2.5 font-mono text-[11px]">Stand {e.version}</Badge>
                  <span className="text-sm text-text">{formatDateTime(e.changed_at)}</span>
                  <span className="text-sm text-text-2">{e.changed_by_label ?? "System"}</span>
                  <span className="font-mono text-xs text-text-3">Profil v{e.snapshot_version}</span>
                </div>
                <p className="mt-1 text-xs text-text-2">
                  {e.changed_fields.length === 0 ? "Danach geändert: nichts (identisch)" : `Danach geändert: ${e.changed_fields.join(", ")}`}
                </p>
              </div>
              {canRestore && (
                <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmVersion(e.version)} disabled={busy != null}>
                  Wiederherstellen
                </Button>
              )}
            </li>
          ))}
        </ol>
      )}
      <Modal
        open={confirmVersion != null}
        onClose={() => busy == null && setConfirmVersion(null)}
        title={`Stand ${confirmVersion ?? ""} wiederherstellen`}
        description="Der aktuelle Stand wird vorher als neuer Eintrag in der Historie gesichert. Asset-Dateien bleiben erhalten."
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmVersion(null)} disabled={busy != null}>
            Abbrechen
          </Button>
          <Button onClick={() => confirmVersion != null && void restore(confirmVersion)} disabled={busy != null}>
            {busy != null ? "Wird wiederhergestellt" : "Wiederherstellen"}
          </Button>
        </div>
      </Modal>
    </GlassCard>
  );
}
