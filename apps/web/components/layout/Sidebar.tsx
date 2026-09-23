"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Wordmark } from "@/components/brand/Wordmark";
import { ROLE_LABELS, can, type Role } from "@/lib/auth/permissions";
import { canExt } from "@/lib/auth/permissions-publishing";
import { cn } from "@/components/ui/cn";

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
  icon: ReactNode;
  match: (p: string) => boolean;
}

/* Seitenleiste wie in jeder App: Logo oben, Bereiche in der Mitte, Einstellungen und Profil unten.
 * Unter lg wird sie zur Schublade mit schmaler Kopfzeile. Punkte erscheinen nur, wenn die Rolle sie nutzen darf. */
export function Sidebar({ user }: { user: NavUser | null }) {
  const pathname = usePathname() ?? "/";
  /* Schublade und Profilmenü gelten nur für den Pfad, auf dem sie geöffnet wurden; ein Seitenwechsel schließt sie */
  const [drawerAt, setDrawerAt] = useState<string | null>(null);
  const drawerOpen = drawerAt === pathname;

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerAt(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  /* „Neues Video“ steht nur als großer Knopf oben, nicht zusätzlich in der Liste (war doppelt). */
  const main: NavItem[] = [
    { href: "/", label: "Meine Videos", icon: <IconGrid />, match: (p) => p === "/" || p.startsWith("/projekte") },
  ];
  if (user?.canBrand) main.push({ href: "/marke", label: "Aussehen", icon: <IconBrand />, match: (p) => p.startsWith("/marke") });

  const publishing: NavItem[] = [];
  if (canExt(user?.role, "series.manage")) publishing.push({ href: "/serien", label: "Serien", icon: <IconStack />, match: (p) => p.startsWith("/serien") });
  if (canExt(user?.role, "experiments.manage")) publishing.push({ href: "/experimente", label: "Tests", icon: <IconFlask />, match: (p) => p.startsWith("/experimente") });
  if (user) publishing.push({ href: "/berichte", label: "Berichte", icon: <IconChart />, match: (p) => p.startsWith("/berichte") });

  const tools: NavItem[] = [];
  if (can(user?.role, "api.manage")) tools.push({ href: "/entwickler", label: "Für Entwickler", icon: <IconCode />, match: (p) => p.startsWith("/entwickler") });

  const settingsActive = pathname.startsWith("/einstellungen");

  const panel = (
    <div className="flex h-full flex-col gap-6 px-4 py-6">
      <Link href="/" aria-label="chopstr Startseite" className="flex items-center px-2">
        <Wordmark width={112} />
      </Link>

      {user?.canUpload && (
        <Link
          href="/upload"
          className="transition-soft flex h-11 items-center justify-center gap-2 rounded-inner border border-brand/60 bg-brand/35 text-sm font-medium text-white hover:bg-brand/50"
        >
          <IconPlus />
          Neues Video
        </Link>
      )}

      <nav aria-label="Hauptnavigation" className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto">
        <NavGroup items={main} pathname={pathname} />
        {/* „Auswertung“ statt „Publishing“: so heißt die Gruppe im Bedienkonzept (Abschnitt 4) und
            sie enthält genau das, was dort steht — Serien, Tests, Berichte. */}
        {publishing.length > 0 && <NavGroup title="Auswertung" items={publishing} pathname={pathname} />}
        {tools.length > 0 && <NavGroup title="Werkzeuge" items={tools} pathname={pathname} />}
      </nav>

      <div className="flex flex-col gap-1 border-t border-line pt-4">
        {user && (
          <NavLink
            item={{ href: "/einstellungen", label: "Einstellungen", icon: <IconSettings />, match: () => settingsActive }}
            active={settingsActive}
          />
        )}
        {user ? (
          <ProfileMenu user={user} pathname={pathname} />
        ) : (
          <NavLink item={{ href: "/anmelden", label: "Anmelden", icon: <IconUser />, match: () => false }} active={false} />
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop: feste Leiste links */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[264px] border-r border-line bg-[#05050c]/80 backdrop-blur-xl lg:block print:hidden">
        {panel}
      </aside>

      {/* Mobil: Kopfzeile mit Menüknopf */}
      <div className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-line bg-[#05050c]/85 px-4 backdrop-blur-xl lg:hidden print:hidden">
        <Link href="/" aria-label="chopstr Startseite">
          <Wordmark width={92} />
        </Link>
        <button
          type="button"
          aria-label="Menü öffnen"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerAt(pathname)}
          className="transition-soft flex h-10 w-10 items-center justify-center rounded-inner text-text-2 hover:bg-white/5 hover:text-text"
        >
          <IconMenu />
        </button>
      </div>
      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button type="button" aria-label="Menü schließen" className="absolute inset-0 bg-black/70" onClick={() => setDrawerAt(null)} />
          <aside className="absolute inset-y-0 left-0 w-[280px] max-w-[85vw] border-r border-line bg-[#05050c]">{panel}</aside>
        </div>
      )}
    </>
  );
}

function NavGroup({ title, items, pathname }: { title?: string; items: NavItem[]; pathname: string }) {
  return (
    <div className="flex flex-col gap-1">
      {title && <p className="mb-1 px-3 text-[11px] font-medium uppercase tracking-[0.08em] text-text-3">{title}</p>}
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.href}>
            <NavLink item={item} active={item.match(pathname)} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "transition-soft relative flex h-11 items-center gap-3 rounded-inner px-3 text-sm font-medium",
        active ? "bg-brand/15 text-text ring-1 ring-inset ring-brand/35" : "text-text-2 hover:bg-white/5 hover:text-text",
      )}
    >
      {active && <span aria-hidden="true" className="absolute inset-y-2.5 left-0 w-[3px] rounded-r-full bg-brand" />}
      <span className={cn("flex h-5 w-5 items-center justify-center", active ? "text-[#6f78ff]" : "text-text-3")}>{item.icon}</span>
      {item.label}
    </Link>
  );
}

function ProfileMenu({ user, pathname }: { user: NavUser; pathname: string }) {
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === pathname;
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenAt(null);
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpenAt(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const initials = user.name.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
  const active = open || pathname.startsWith("/profil") || pathname.startsWith("/workspaces");

  return (
    <div ref={ref} className="relative">
      {open && (
        <div role="menu" className="absolute bottom-[calc(100%+8px)] left-0 right-0 rounded-inner border border-line bg-raised p-1.5 text-sm">
          <MenuLink href="/profil">Profil</MenuLink>
          <MenuLink href="/workspaces">Team wechseln</MenuLink>
          {user.canBilling && <MenuLink href="/einstellungen/abrechnung">Abrechnung</MenuLink>}
          {user.canAudit && <MenuLink href="/einstellungen/audit">Audit-Log</MenuLink>}
          <MenuLink href="/rechtliches/avv">Rechtliches</MenuLink>
          <div className="my-1 h-px bg-line" />
          {user.demo ? (
            <p className="px-3 py-2 text-xs text-text-3">Demo-Modus: keine Abmeldung</p>
          ) : (
            <form method="post" action="/abmelden">
              <button type="submit" role="menuitem" className="transition-soft block w-full rounded-[12px] px-3 py-2 text-left text-danger hover:bg-danger/10">
                Abmelden
              </button>
            </form>
          )}
        </div>
      )}
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpenAt(open ? null : pathname)}
        className={cn(
          "transition-soft flex w-full items-center gap-3 rounded-inner p-2 text-left",
          active ? "bg-white/10" : "hover:bg-white/5",
        )}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand/40 text-xs font-semibold text-white">{initials || "?"}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-text">{user.name}</span>
          <span className="block truncate text-xs text-text-3">
            {user.workspaceName ?? user.email}
            {user.role ? ` · ${ROLE_LABELS[user.role]}` : ""}
          </span>
        </span>
        <span className="text-text-3">
          <IconChevrons />
        </span>
      </button>
    </div>
  );
}

function MenuLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} role="menuitem" className="transition-soft block rounded-[12px] px-3 py-2 text-text-2 hover:bg-white/5 hover:text-text">
      {children}
    </Link>
  );
}

/* Icons: 20 px, 1,75 px Strich, currentColor */
function Svg({ children }: { children: ReactNode }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}
const IconGrid = () => (
  <Svg>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </Svg>
);
const IconBrand = () => (
  <Svg>
    <circle cx="13.5" cy="6.5" r="1.5" />
    <circle cx="17.5" cy="10.5" r="1.5" />
    <circle cx="8.5" cy="7.5" r="1.5" />
    <circle cx="6.5" cy="12.5" r="1.5" />
    <path d="M12 2a10 10 0 0 0 0 20c.9 0 1.6-.7 1.6-1.6 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H16a6 6 0 0 0 6-6C22 6 17.5 2 12 2Z" />
  </Svg>
);
const IconStack = () => (
  <Svg>
    <path d="m12 2 10 5-10 5L2 7l10-5Z" />
    <path d="m2 17 10 5 10-5" />
    <path d="m2 12 10 5 10-5" />
  </Svg>
);
const IconFlask = () => (
  <Svg>
    <path d="M9 3h6" />
    <path d="M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3" />
    <path d="M7 15h10" />
  </Svg>
);
const IconChart = () => (
  <Svg>
    <path d="M3 3v18h18" />
    <path d="M8 16v-4" />
    <path d="M13 16V8" />
    <path d="M18 16v-7" />
  </Svg>
);
const IconCode = () => (
  <Svg>
    <path d="m16 18 6-6-6-6" />
    <path d="m8 6-6 6 6 6" />
  </Svg>
);
const IconSettings = () => (
  <Svg>
    <path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.8l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.8v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
);
const IconUser = () => (
  <Svg>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </Svg>
);
const IconPlus = () => (
  <Svg>
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </Svg>
);
const IconMenu = () => (
  <Svg>
    <path d="M4 7h16" />
    <path d="M4 12h16" />
    <path d="M4 17h16" />
  </Svg>
);
const IconChevrons = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m7 15 5 5 5-5" />
    <path d="m7 9 5-5 5 5" />
  </svg>
);
