"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { formatDateTime } from "@/lib/format";
import type { ExperimentStatus } from "@/lib/repo/types-publishing";

interface Props {
  experimentId: string;
  status: ExperimentStatus;
  winner: "A" | "B" | null;
  decidedAt: string | null;
  confidence: number | null;
  ready: boolean;
  reasons: string[];
  metricLabel: string;
}

/* Entscheidung: Konfidenz P(A > B), Gewinner setzen. Vor Erfüllung der Bedingungen deaktiviert mit Begründung. */
export function ExperimentDecision({ experimentId, status, winner, decidedAt, confidence, ready, reasons, metricLabel }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState<"A" | "B" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (w: "A" | "B") => {
    if (!window.confirm(`Variante ${w} als Gewinner setzen? Das Experiment wird damit abgeschlossen.`)) return;
    setBusy(w);
    setError(null);
    try {
      const res = await fetch(`/api/experiments/${experimentId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ winner: w }) });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error ?? "Entscheidung fehlgeschlagen");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Entscheidung fehlgeschlagen");
    } finally {
      setBusy(null);
    }
  };

  const pct = confidence != null ? Math.round(confidence * 100) : null;
  const suggested: "A" | "B" | null = pct == null ? null : pct >= 50 ? "A" : "B";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        {/* „Konfidenz als Posterior P(A > B) über Beta-Verteilungen (2.000 Ziehungen, fester
            Seed)" beschreibt die Rechnung genau - und richtet sich an niemanden, der hier
            entscheidet. Gerechnet wird weiter dasselbe; es steht nur anders da.

            Ohne genug Zahlen steht ausdrücklich, dass es keine Aussage gibt. Eine Prozentzahl an
            zwei Clips mit je vierzig Aufrufen wäre eine Behauptung, die die Daten nicht tragen. */}
        <div>
          <h2 className="text-lg font-medium">Entscheidung</h2>
          <p className="mt-1 text-sm text-text-2">
            {pct == null
              ? "Sobald beide Fassungen gepostet sind und genug Zahlen vorliegen, steht hier, welche besser ankommt."
              : `Gerechnet aus ${metricLabel.toLowerCase()} beider Fassungen. Je näher an 100 Prozent, desto sicherer ist der Vorsprung.`}
          </p>
        </div>
        <p className="text-right text-2xl tabular-nums">
          {pct == null ? (
            <span className="text-base text-text-3">Noch keine belastbare Aussage</span>
          ) : (
            <span>
              {pct} %{" "}
              <span className="text-base text-text-2">sicher für Fassung {pct >= 50 ? "A" : "B"}</span>
            </span>
          )}
        </p>
      </div>
      {pct != null && (
        <div className="h-2 w-full overflow-hidden rounded-pill bg-white/10" role="img" aria-label={`Sicherheit für Fassung A: ${pct} Prozent`}>
          <div className="h-full rounded-pill bg-text" style={{ width: `${pct}%` }} />
        </div>
      )}
      {status === "decided" ? (
        <p className="text-sm text-text">
          Entschieden für Fassung {winner ?? "?"} am {formatDateTime(decidedAt)}.
        </p>
      ) : (
        <>
          {!ready && (
            <div className="rounded-inner border border-attention/40 bg-attention/10 px-4 py-3 text-sm text-text">
              <p className="font-medium">Noch keine belastbare Aussage</p>
              <ul className="mt-1.5 flex flex-col gap-1 text-text-2" aria-label="Was noch fehlt">
                {reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {(["A", "B"] as const).map((w) => (
              <Button
                key={w}
                variant={suggested === w && ready ? "primary" : "ghost"}
                onClick={() => decide(w)}
                disabled={!ready || busy != null}
                title={ready ? undefined : reasons[0]}
                className={cn(!ready && "opacity-50")}
              >
                {busy === w ? "Wird gesetzt" : `Fassung ${w} gewinnt`}
              </Button>
            ))}
          </div>
          {error && (
            <p role="alert" className="text-sm text-attention">
              {error}
            </p>
          )}
        </>
      )}
    </div>
  );
}
