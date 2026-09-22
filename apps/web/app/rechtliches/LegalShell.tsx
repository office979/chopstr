import type { ReactNode } from "react";
import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import type { LegalDoc, LegalDocKey } from "@/lib/legal/docs";
import { PrintButton } from "./PrintButton";

const TABS: { key: LegalDocKey; href: string; label: string }[] = [
  { key: "avv", href: "/rechtliches/avv", label: "AVV" },
  { key: "toms", href: "/rechtliches/toms", label: "TOMs" },
  { key: "subprozessoren", href: "/rechtliches/subprozessoren", label: "Subprozessoren" },
];

interface Props {
  current: LegalDocKey;
  doc: LegalDoc | null;
  title: string;
  eyebrow?: string;
  aside?: ReactNode;
  children?: ReactNode;
}

/* Rahmen der Rechtsseiten: Reiter, Banner „Vorlage, juristisch zu prüfen“, Druckansicht (@media print in globals.css) */
export function LegalShell({ current, doc, title, eyebrow, aside, children }: Props) {
  return (
    <PageShell width="default" backgroundWord="Recht">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="text-sm text-text-2">{eyebrow ?? "Rechtliches"}</p>
          <h1 className="text-3xl font-semibold tracking-[var(--tracking-display)] sm:text-4xl">{title}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {doc && <Badge className="font-mono">Version {doc.version}</Badge>}
          <PrintButton />
        </div>
      </div>
      <nav aria-label="Rechtstexte" className="mb-6 flex flex-wrap gap-1 print:hidden">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.href}
            aria-current={t.key === current ? "page" : undefined}
            className={cn(
              "transition-soft rounded-pill border px-4 py-2 text-sm font-medium",
              t.key === current ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong hover:text-text",
            )}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      <div className={cn("grid gap-5", Boolean(aside) && "lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start")}>
        <GlassCard padding="lg" className="legal-print">
          <p role="note" className="mb-6 rounded-inner border border-attention/50 bg-attention/10 px-4 py-3 text-sm text-text">
            <span className="font-medium text-attention">Vorlage, juristisch zu prüfen.</span>
            {doc?.status && doc.status !== "Vorlage, juristisch zu prüfen" ? ` ${doc.status}.` : ""} Keine Rechtsberatung; vor dem ersten zahlenden Kunden durch eine Kanzlei
            prüfen lassen.
          </p>
          {doc ? (
            children
          ) : (
            <p className="text-text-2">
              Der Text ist auf diesem Server nicht vorhanden. Erwartet wird die Datei <code className="font-mono text-sm">docs/rechtliches/{current}-{process.env.DPA_VERSION ?? "2026-09"}.md</code> im Monorepo.
            </p>
          )}
          {doc && <p className="mt-8 border-t border-line pt-4 font-mono text-xs text-text-3">Quelle: {doc.file.replace(/^.*\/docs\//, "docs/")}</p>}
        </GlassCard>
        {aside && <div className="flex flex-col gap-5 print:hidden">{aside}</div>}
      </div>
    </PageShell>
  );
}
