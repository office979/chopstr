"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Mark } from "@/components/brand/Mark";
import { ROLE_LABELS, can, type Role } from "@/lib/auth/permissions";
import { cn } from "./cn";

export interface NavUser {
  name: string;
  email: string;
  workspaceName: string | null;
  role: Role | null;
  demo: boolean;
  canUpload: boolean;
  canBrand: boolean;
  canAudit: boolean;
  canBilling: boolean;
}

interface NavItem {
  href: string;
  label: string;
  short: string;
  match: (p: string) => boolean;
}

/* Schwebende Pill-Navigation aus Glas, mittig. Rechts die weiße Aktion und das Nutzer-Menü.
 * Upload und Markenprofil erscheinen nur für Rollen mit Schreibrecht (reviewer und client sehen sie nicht). */
export function PillNav({ user }: { user: NavUser | null }) {
  const pathname = usePathname() ?? "/";
  /* Menü ist offen, solange der Pfad gleich bleibt; ein Seitenwechsel schließt es ohne Effekt */
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === pathname;
  const setOpen = (next: boolean | ((v: boolean) => boolean)) => {
    const value = typeof next === "function" ? next(open) : next;
    setOpenAt(value ? pathname : null);
  };
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenAt(null);
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpenAt(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const items: NavItem[] = [
    { href: "/", label: "Meine Videos", short: "Videos", match: (p) => p === "/" || p.startsWith("/projekte") },
  ];
  if (user?.canUpload) items.push({ href: "/upload", label: "Neues Video", short: "Neu", match: (p) => p.startsWith("/upload") });
  if (user?.canBrand) items.push({ href: "/marke", label: "Aussehen", short: "Aussehen", match: (p) => p.startsWith("/marke") });
  /* Entwicklerseite (API, MCP): nur admin und owner (api.manage) */
  if (can(user?.role, "api.manage")) items.push({ href: "/entwickler", label: "Entwickler", short: "API", match: (p) => p.startsWith("/entwickler") });

  const initials = user ? user.name.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() : "";

  return (
    <header className="pointer-events-none fixed inset-x-0 top-4 z-40 flex justify-center px-4 sm:top-6">
      <nav
        aria-label="Hauptnavigation"
        className="glass pointer-events-auto flex w-full max-w-[760px] items-center gap-1 rounded-pill p-1.5 sm:w-auto"
      >
        <Link
          href="/"
          aria-label="chopstr Startseite"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full hover:bg-white/5"
        >
          <Mark size={22} />
        </Link>
        <ul className="flex min-w-0 flex-1 items-center justify-center gap-0.5">
          {items.map((item) => {
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
        {user?.canUpload && (
          <Link
            href="/upload"
            className="transition-soft flex h-9 shrink-0 items-center rounded-pill bg-text px-3 text-sm font-medium text-black hover:bg-white sm:px-4"
          >
            <span className="sm:hidden" aria-hidden="true">+</span>
            <span className="sr-only sm:not-sr-only">Neues Video</span>
          </Link>
        )}
        {user ? (
          <div ref={menuRef} className="relative shrink-0">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={open}
              aria-label={`Nutzermenü, ${user.name}`}
              onClick={() => setOpen((v) => !v)}
              className={cn(
                "transition-soft flex h-9 min-w-9 items-center justify-center gap-2 rounded-full px-2 text-xs font-medium text-text-2 hover:bg-white/5 hover:text-text",
                (open || pathname.startsWith("/einstellungen") || pathname.startsWith("/profil") || pathname.startsWith("/workspaces")) && "bg-white/10 text-text",
              )}
            >
              <span className="flex h-6 w-6 items-center justify-center rounded-full border border-line-strong font-mono text-[11px]">{initials || "?"}</span>
            </button>
            {open && (
              <div
                role="menu"
                className="absolute right-0 top-11 w-64 rounded-[22px] border border-line bg-raised p-2 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_30px_80px_rgba(0,0,0,0.7)]"
              >
                <div className="px-3 py-2">
                  <p className="truncate font-medium text-text">{user.name}</p>
                  <p className="truncate text-xs text-text-2">{user.email}</p>
                  {user.workspaceName && (
                    <p className="mt-1 truncate text-xs text-text-2">
                      {user.workspaceName}
                      {user.role ? ` · ${ROLE_LABELS[user.role]}` : ""}
                    </p>
                  )}
                  {user.demo && <p className="mt-1 text-xs text-ai-soft">Demo-Modus</p>}
                </div>
                <div className="my-1 h-px bg-line" />
                <MenuLink href="/workspaces">Workspace wechseln</MenuLink>
                <MenuLink href="/einstellungen">Einstellungen</MenuLink>
                {user.canBilling && <MenuLink href="/einstellungen/abrechnung">Abrechnung</MenuLink>}
                {user.canAudit && <MenuLink href="/einstellungen/audit">Audit-Log</MenuLink>}
                <MenuLink href="/profil">Profil</MenuLink>
                <div className="my-1 h-px bg-line" />
                {user.demo ? (
                  <p className="px-3 py-2 text-xs text-text-2">Ohne Datenbank gibt es keine Abmeldung.</p>
                ) : (
                  <form method="post" action="/abmelden">
                    <button
                      type="submit"
                      role="menuitem"
                      className="transition-soft block w-full rounded-inner px-3 py-2 text-left text-text-2 hover:bg-white/5 hover:text-text"
                    >
                      Abmelden
                    </button>
                  </form>
                )}
              </div>
            )}
          </div>
        ) : (
          <Link
            href="/anmelden"
            className="transition-soft flex h-9 shrink-0 items-center rounded-pill px-3 text-sm font-medium text-text-2 hover:bg-white/5 hover:text-text"
          >
            Anmelden
          </Link>
        )}
      </nav>
    </header>
  );
}

function MenuLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} role="menuitem" className="transition-soft block rounded-inner px-3 py-2 text-text-2 hover:bg-white/5 hover:text-text">
      {children}
    </Link>
  );
}
