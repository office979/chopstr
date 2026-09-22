import Link from "next/link";
import { cn } from "@/components/ui/cn";

export type PublishingArea = "experimente" | "serien" | "berichte" | "verbindungen";

const ITEMS: { key: PublishingArea; href: string; label: string }[] = [
  { key: "serien", href: "/serien", label: "Serien" },
  { key: "experimente", href: "/experimente", label: "Experimente" },
  { key: "berichte", href: "/berichte", label: "Berichte" },
  { key: "verbindungen", href: "/einstellungen/verbindungen", label: "Verbindungen" },
];

/* Kleine Sekundärnavigation der Publishing-Seiten (Phase 5b); die Hauptnavigation bleibt unverändert. */
export function PublishingNav({ current, showConnections = true }: { current: PublishingArea; showConnections?: boolean }) {
  return (
    <nav aria-label="Publishing" className="mb-6 flex flex-wrap gap-1">
      {ITEMS.filter((i) => showConnections || i.key !== "verbindungen").map((i) => (
        <Link
          key={i.key}
          href={i.href}
          aria-current={i.key === current ? "page" : undefined}
          className={cn(
            "transition-soft rounded-pill border px-4 py-2 text-sm font-medium",
            i.key === current ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong hover:text-text",
          )}
        >
          {i.label}
        </Link>
      ))}
    </nav>
  );
}
