import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import type { BrandProfile } from "@/lib/repo/types";

const COUNTRY_LABELS: Record<string, string> = { DE: "Deutschland", AT: "Österreich", CH: "Schweiz" };

/* Übersicht aller Branding-Profile eines Workspace. Ein Klick wechselt das bearbeitete Profil
 * (Zustand steckt in der Adresse, damit ein Neuladen nicht zurückspringt). Bewusst schlicht
 * gehalten: mehr als eine Handvoll Profile sind hier nicht zu erwarten. */
export function BrandList({ profiles, activeId, isNew }: { profiles: BrandProfile[]; activeId: string | null; isNew: boolean }) {
  return (
    <GlassCard padding="md" className="mb-5 flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">Dein Aussehen</h2>
          <p className="mt-0.5 text-sm text-text-2">
            Jedes Video nutzt eines davon. Es steuert Anrede, Farben, Schrift und Untertitel-Stil.
          </p>
        </div>
        <Link
          href="/marke?p=neu"
          className={cn(
            "transition-soft inline-flex h-9 items-center rounded-pill px-4 text-sm font-medium",
            isNew ? "bg-text text-black" : "border border-line-strong text-text hover:border-white/40 hover:bg-white/5",
          )}
        >
          Neues Aussehen
        </Link>
      </div>

      {profiles.length === 0 ? (
        <p className="text-sm text-text-2">Noch keins angelegt. Leg dein erstes an, dann kannst du Videos hochladen.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {profiles.map((p) => {
            const active = !isNew && p.id === activeId;
            return (
              <li key={p.id}>
                <Link
                  href={`/marke?p=${p.id}`}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "transition-soft flex flex-wrap items-center gap-x-4 gap-y-1 rounded-inner border px-4 py-3",
                    active ? "border-white/40 bg-white/10" : "border-line hover:border-line-strong hover:bg-white/5",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate font-medium text-text">{p.name}</span>
                  <span className="text-sm text-text-2">{COUNTRY_LABELS[p.country] ?? p.country}</span>
                  <span className="text-sm text-text-2">Anrede {p.address}</span>
                  <Badge>{PLATFORM_LABELS[p.default_platform]}</Badge>
                  <span className="font-mono text-xs text-text-3">v{p.version}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </GlassCard>
  );
}
