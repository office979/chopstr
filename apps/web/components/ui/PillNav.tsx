"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Mark } from "@/components/brand/Mark";
import { cn } from "./cn";

const ITEMS = [
  { href: "/", label: "Projekte", short: "Projekte", match: (p: string) => p === "/" || p.startsWith("/projekte") },
  { href: "/upload", label: "Upload", short: "Upload", match: (p: string) => p.startsWith("/upload") },
  { href: "/marke", label: "Markenprofil", short: "Marke", match: (p: string) => p.startsWith("/marke") },
];

/* Schwebende Pill-Navigation aus Glas, mittig. Rechts die weiße Aktion. */
export function PillNav() {
  const pathname = usePathname() ?? "/";
  return (
    <header className="pointer-events-none fixed inset-x-0 top-4 z-40 flex justify-center px-4 sm:top-6">
      <nav
        aria-label="Hauptnavigation"
        className="glass pointer-events-auto flex w-full max-w-[720px] items-center gap-1 rounded-pill p-1.5 sm:w-auto"
      >
        <Link
          href="/"
          aria-label="chopstr Startseite"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full hover:bg-white/5"
        >
          <Mark size={22} />
        </Link>
        <ul className="flex min-w-0 flex-1 items-center justify-center gap-0.5">
          {ITEMS.map((item) => {
            const active = item.match(pathname);
            return (
              <li key={item.href} className="min-w-0">
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "transition-soft block whitespace-nowrap rounded-pill px-2.5 py-2 text-[13px] font-medium sm:px-4 sm:text-sm",
                    active ? "bg-white/10 text-text" : "text-text-2 hover:bg-white/5 hover:text-text",
                  )}
                >
                  <span className="sm:hidden">{item.short}</span>
                  <span className="hidden sm:inline">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
        <Link
          href="/upload"
          className="transition-soft flex h-9 shrink-0 items-center rounded-pill bg-text px-3 text-sm font-medium text-black hover:bg-white sm:px-4"
        >
          <span className="sm:hidden" aria-hidden="true">+</span>
          <span className="sr-only sm:not-sr-only">Neues Projekt</span>
        </Link>
        <Link
          href="/einstellungen"
          aria-label="Workspace-Einstellungen"
          className={cn(
            "transition-soft hidden h-9 w-9 shrink-0 items-center justify-center rounded-full text-text-2 hover:bg-white/5 hover:text-text sm:flex",
            pathname.startsWith("/einstellungen") && "bg-white/10 text-text",
          )}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.4" />
            <path
              d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M3.6 12.4l1.1-1.1M11.3 4.7l1.1-1.1"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </Link>
      </nav>
    </header>
  );
}
