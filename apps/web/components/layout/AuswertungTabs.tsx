import Link from "next/link";
import { cn } from "@/components/ui/cn";
import { canExt } from "@/lib/auth/permissions-publishing";
import type { Role } from "@/lib/repo/types";

/* Die drei Seiten der Auswertung als Reiter. In der Seitenleiste steht seit dem Aufräumen nur
 * noch ein Punkt „Auswertung"; ohne diese Reiter wären Serien und Tests nicht mehr zu finden.
 * Gezeigt wird nur, was die Rolle darf, wie vorher in der Seitenleiste. */
export function AuswertungTabs({ aktiv, role }: { aktiv: "berichte" | "serien" | "experimente"; role: Role | null | undefined }) {
  const tabs: { id: typeof aktiv; href: string; label: string }[] = [{ id: "berichte", href: "/berichte", label: "Berichte" }];
  if (canExt(role, "series.manage")) tabs.push({ id: "serien", href: "/serien", label: "Serien" });
  if (canExt(role, "experiments.manage")) tabs.push({ id: "experimente", href: "/experimente", label: "Tests" });
  if (tabs.length < 2) return null;
  return (
    <nav aria-label="Auswertung" className="mb-5 flex w-fit gap-1 rounded-pill border border-line p-1">
      {tabs.map((t) => (
        <Link
          key={t.id}
          href={t.href}
          aria-current={t.id === aktiv ? "page" : undefined}
          className={cn(
            "transition-soft rounded-pill px-4 py-1.5 text-sm",
            t.id === aktiv ? "bg-white/10 text-text" : "text-text-2 hover:text-text",
          )}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
