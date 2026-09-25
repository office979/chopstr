"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/components/ui/cn";
import { formatDateTime } from "@/lib/format";
import { fristAbgelaufen } from "@/lib/guest/approval";
import type { FreigabeZeile } from "@/lib/repo/types";

/* Die verschickten Freigaben, eine je Zeile.
 *
 * Aufgebaut wie die Clip-Liste: eine Karte je Eintrag, links was es ist, rechts was man damit tun
 * kann. Das Wichtigste ist der Link - er ist der Grund, warum es diese Seite gibt. */
export function FreigabenListe({ freigaben, basis }: { freigaben: FreigabeZeile[]; basis: string }) {
  const [kopiert, setKopiert] = useState<string | null>(null);

  const kopieren = async (id: string, link: string) => {
    try {
      await navigator.clipboard.writeText(link);
      setKopiert(id);
      window.setTimeout(() => setKopiert((v) => (v === id ? null : v)), 2000);
    } catch {
      /* Verweigert der Browser die Zwischenablage, bleibt der Link im Feld stehen und lässt sich
       * von Hand markieren - deshalb ein Eingabefeld und kein reiner Text. */
      setKopiert(null);
    }
  };

  return (
    <ul className="flex flex-col gap-3">
      {freigaben.map((f) => {
        const link = `${basis}/freigabe/${f.token}`;
        const abgelaufen = fristAbgelaufen(f.expires_at);
        return (
          <li key={f.id}>
            <GlassCard padding="md" className="flex flex-col gap-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[15px] font-medium text-text">{f.name}</p>
                  <p className="mt-0.5 text-sm text-text-2">
                    {f.clips} {f.clips === 1 ? "Clip" : "Clips"}
                    {f.videos.length > 0 && ` · ${f.videos.join(", ")}`}
                    {f.marken.length > 0 && ` · ${f.marken.join(", ")}`}
                  </p>
                  <p className="mt-0.5 text-xs text-text-3">
                    Verschickt {formatDateTime(f.created_at)}
                    {f.guest_email ? ` an ${f.guest_email}` : " · ohne E-Mail, Link von Hand weitergegeben"}
                  </p>
                </div>

                {/* Wie weit die Antworten sind. Nur was vorkommt: fünf Nullen nebeneinander sagen
                    nichts und kosten trotzdem eine Zeile. */}
                <div className="flex flex-wrap items-center gap-2 text-[12px]">
                  {f.freigegeben > 0 && <Zahl ton="gut">{f.freigegeben} freigegeben</Zahl>}
                  {f.abgelehnt > 0 && <Zahl ton="fehler">{f.abgelehnt} abgelehnt</Zahl>}
                  {f.fehlerhaft > 0 && <Zahl ton="achtung">{f.fehlerhaft} fehlerhaft</Zahl>}
                  {f.offen > 0 && <Zahl ton="ruhig">{f.offen} offen</Zahl>}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  readOnly
                  value={link}
                  onFocus={(e) => e.currentTarget.select()}
                  aria-label={`Link zu ${f.name}`}
                  className="min-w-0 flex-1 rounded-inner border border-line bg-black/40 px-3 py-2 text-sm text-text"
                />
                <Button size="sm" variant="ghost" onClick={() => void kopieren(f.id, link)}>
                  {kopiert === f.id ? "Kopiert" : "Link kopieren"}
                </Button>
                <a
                  href={link}
                  target="_blank"
                  rel="noreferrer"
                  className="transition-soft inline-flex h-9 items-center rounded-pill border border-line px-4 text-sm text-text-2 hover:border-line-strong hover:text-text"
                >
                  Ansehen
                </a>
              </div>

              {abgelaufen && (
                <p className="text-sm text-attention">
                  Dieser Link ist abgelaufen. Für eine neue Antwort braucht es eine neue Freigabe.
                </p>
              )}
            </GlassCard>
          </li>
        );
      })}
    </ul>
  );
}

function Zahl({ ton, children }: { ton: "gut" | "achtung" | "fehler" | "ruhig"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-pill border px-2.5 font-medium",
        ton === "gut" && "border-gut/60 bg-gut/15 text-text",
        ton === "achtung" && "border-attention/60 bg-attention/15 text-text",
        ton === "fehler" && "border-danger/60 bg-danger/15 text-text",
        ton === "ruhig" && "border-line text-text-2",
      )}
    >
      {children}
    </span>
  );
}
