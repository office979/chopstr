"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Mark } from "@/components/brand/Mark";
import { Wordmark } from "@/components/brand/Wordmark";
import { ROLE_LABELS, type Role } from "@/lib/auth/permissions";
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
  /* „Marken" und nicht „Aussehen": die Seite verwaltet Kundenprofile, die Adresse heisst
   * /marke, der Pfad auf den Clipseiten sagt „Marke", und drei Namen für eine Sache zwingen zum
   * Raten. */
  if (user?.canBrand) main.push({ href: "/marke", label: "Branding", icon: <IconBrand />, match: (p) => p.startsWith("/marke") });
  /* „Freigaben": hier stehen die verschickten Links.
   *
   * Der Link zu einer Freigabe steht beim Verschicken im Fenster - und wer ihn dort nicht kopiert
   * oder später verliert, hatte bisher keinen Weg zurück. Es gab keine Stelle, an der ein
   * verschickter Link noch einmal auftaucht. Diese ist es. */
  if (canExt(user?.role, "guest_approval.request")) {
    main.push({ href: "/freigaben", label: "Freigaben", icon: <IconFreigabe />, match: (p) => p.startsWith("/freigaben") });
  }

  const publishing: NavItem[] = [];
  if (canExt(user?.role, "series.manage")) publishing.push({ href: "/serien", label: "Serien", icon: <IconStack />, match: (p) => p.startsWith("/serien") });
  if (canExt(user?.role, "experiments.manage")) publishing.push({ href: "/experimente", label: "Tests", icon: <IconFlask />, match: (p) => p.startsWith("/experimente") });
  if (user) publishing.push({ href: "/berichte", label: "Berichte", icon: <IconChart />, match: (p) => p.startsWith("/berichte") });

  /* „Für Entwickler" stand als gleichrangiger Punkt in der Hauptnavigation. Für einen Creator ist
   * das eine Tür, hinter der nichts für ihn liegt, und sie nimmt so viel Platz ein wie „Meine
   * Videos". Die Seite bleibt erreichbar, aber dort, wo alles Technische liegt: unter den
   * Einstellungen. */
  const tools: NavItem[] = [];

  const settingsActive = pathname.startsWith("/einstellungen");

  /* Zwei Fassungen derselben Leiste.
   *
   * „kompakt" ist die schmale Schiene für mittlere Fenster: nur Zeichen, kein Text. Vorher
   * verschwand die Leiste dort ganz und wurde zur Schublade hinter einem Menüknopf - der Weg zu
   * „Meine Videos" ging damit von einem Klick auf zwei, und wo man gerade ist, war gar nicht mehr
   * zu sehen. Die Zeichen allein sagen das weiter, und sie kosten 64 statt 264 Bildpunkte.
   *
   * Ohne Text braucht jeder Punkt seinen Namen woanders: title für die Maus, aria-label für
   * Vorleseprogramme. Ein Zeichen ohne Namen ist ein Rätsel. */
  const panel = (kompakt: boolean) => (
    <div className={cn("flex h-full flex-col gap-6 py-6", kompakt ? "items-center px-2" : "px-4")}>
      <Link
        href="/"
        aria-label="chopstr Startseite"
        title={kompakt ? "chopstr Startseite" : undefined}
        className={cn("flex items-center", kompakt ? "justify-center" : "px-2")}
      >
        {kompakt ? <Mark size={28} color="currentColor" className="text-white" /> : <Wordmark width={112} />}
      </Link>

      {user?.canUpload && (
        <Link
          href="/upload"
          aria-label="Neues Video"
          title={kompakt ? "Neues Video" : undefined}
          className={cn(
            "transition-soft flex items-center justify-center gap-2 rounded-inner border border-brand/60 bg-brand/35 text-sm font-medium text-white hover:bg-brand/50",
            kompakt ? "h-11 w-11" : "h-11",
          )}
        >
          <IconPlus />
          {!kompakt && "Neues Video"}
        </Link>
      )}

      <nav
        aria-label="Hauptnavigation"
        className={cn("flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto", kompakt && "w-full items-center")}
      >
        <NavGroup items={main} pathname={pathname} kompakt={kompakt} />
        {/* „Auswertung“ statt „Publishing“: so heißt die Gruppe im Bedienkonzept (Abschnitt 4) und
            sie enthält genau das, was dort steht — Serien, Tests, Berichte. */}
        {publishing.length > 0 && <NavGroup title="Auswertung" items={publishing} pathname={pathname} kompakt={kompakt} />}
        {tools.length > 0 && <NavGroup title="Werkzeuge" items={tools} pathname={pathname} kompakt={kompakt} />}

      </nav>

      <div className={cn("flex flex-col gap-1 border-t border-line pt-4", kompakt && "w-full items-center")}>
        {user && (
          <NavLink
            item={{ href: "/einstellungen", label: "Einstellungen", icon: <IconSettings />, match: () => settingsActive }}
            active={settingsActive}
            kompakt={kompakt}
          />
        )}
        {user ? (
          <ProfileMenu user={user} pathname={pathname} kompakt={kompakt} />
        ) : (
          <NavLink
            item={{ href: "/anmelden", label: "Anmelden", icon: <IconUser />, match: () => false }}
            active={false}
            kompakt={kompakt}
          />
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Breites Fenster: die ganze Leiste mit Text. */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[264px] border-r border-line bg-[#05050c]/80 backdrop-blur-xl lg:block print:hidden">
        {panel(false)}
      </aside>

      {/* Mittleres Fenster: dieselbe Leiste als schmale Schiene, nur Zeichen. Sie verschwindet
          nicht mehr - wo man ist, bleibt sichtbar, und jeder Bereich bleibt einen Klick entfernt. */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[64px] border-r border-line bg-[#05050c]/80 backdrop-blur-xl sm:block lg:hidden print:hidden">
        {panel(true)}
      </aside>

      {/* Handy: dafür ist auch eine Schiene zu breit. Kopfzeile mit Menüknopf. */}
      <div className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-line bg-[#05050c]/85 px-4 backdrop-blur-xl sm:hidden print:hidden">
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
        <div className="fixed inset-0 z-50 sm:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button type="button" aria-label="Menü schließen" className="absolute inset-0 bg-black/70" onClick={() => setDrawerAt(null)} />
          <aside className="absolute inset-y-0 left-0 w-[280px] max-w-[85vw] border-r border-line bg-[#05050c]">{panel(false)}</aside>
        </div>
      )}
    </>
  );
}

function NavGroup({
  title,
  items,
  pathname,
  kompakt = false,
}: {
  title?: string;
  items: NavItem[];
  pathname: string;
  kompakt?: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-1", kompakt && "w-full items-center")}>
      {/* Die Überschrift der Gruppe fällt in der Schiene weg: „Auswertung" auf 64 Bildpunkten
          wäre ein abgeschnittenes Wort. Ein feiner Strich trennt stattdessen. */}
      {title &&
        (kompakt ? (
          <span aria-hidden="true" className="my-1 h-px w-6 bg-line" />
        ) : (
          <p className="mb-1 px-3 text-[11px] font-medium uppercase tracking-[0.08em] text-text-3">{title}</p>
        ))}
      <ul className={cn("flex flex-col gap-1", kompakt && "w-full items-center")}>
        {items.map((item) => (
          <li key={item.href}>
            <NavLink item={item} active={item.match(pathname)} kompakt={kompakt} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function NavLink({ item, active, kompakt = false }: { item: NavItem; active: boolean; kompakt?: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      /* Ohne Text braucht der Punkt seinen Namen woanders: der Titel für die Maus, das Label für
         Vorleseprogramme. Ein Zeichen ohne Namen ist ein Rätsel. */
      aria-label={kompakt ? item.label : undefined}
      title={kompakt ? item.label : undefined}
      className={cn(
        "transition-soft relative flex h-11 items-center rounded-inner text-sm font-medium",
        kompakt ? "w-11 justify-center" : "gap-3 px-3",
        active ? "bg-brand/15 text-text ring-1 ring-inset ring-brand/35" : "text-text-2 hover:bg-white/5 hover:text-text",
      )}
    >
      {active && !kompakt && <span aria-hidden="true" className="absolute inset-y-2.5 left-0 w-[3px] rounded-r-full bg-brand" />}
      <span className={cn("flex h-5 w-5 items-center justify-center", active ? "text-[#6f78ff]" : "text-text-3")}>{item.icon}</span>
      {!kompakt && item.label}
    </Link>
  );
}

function ProfileMenu({ user, pathname, kompakt = false }: { user: NavUser; pathname: string; kompakt?: boolean }) {
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
        <div
          role="menu"
          className={cn(
            "absolute bottom-[calc(100%+8px)] rounded-inner border border-line bg-raised p-1.5 text-sm",
            /* In der Schiene hätte das Menü 48 Bildpunkte Breite. Es bekommt eine eigene und
               klappt nach rechts auf, statt sich an der Leiste auszurichten. */
            kompakt ? "left-0 w-[220px]" : "left-0 right-0",
          )}
        >
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
        aria-label={kompakt ? `${user.name}, Konto und Team` : undefined}
        title={kompakt ? `${user.name}${user.workspaceName ? ` · ${user.workspaceName}` : ""}` : undefined}
        onClick={() => setOpenAt(open ? null : pathname)}
        className={cn(
          "transition-soft flex items-center rounded-inner text-left",
          kompakt ? "h-11 w-11 justify-center" : "w-full gap-3 p-2",
          active ? "bg-white/10" : "hover:bg-white/5",
        )}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand/40 text-xs font-semibold text-white">{initials || "?"}</span>
        {!kompakt && (
          <>
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
          </>
        )}
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
/* Die Farbtupfer sind gefüllt und klein statt gestrichelt und gross.
 *
 * Vorher waren es Kreise mit Radius 1,5 bei Strichstärke 1,75: der Strich war breiter als der
 * Radius, jeder Tupfer also ein dicker Ring von fast 5 Einheiten Durchmesser - bei vier Einheiten
 * Abstand berührten sie sich. Das Zeichen wirkte fett und verschmiert. Gefüllte Punkte tragen
 * dieselbe Bedeutung und lassen dem Zeichen Luft. */
const IconBrand = () => (
  <Svg>
    <circle cx="13.4" cy="6.6" r="1.05" fill="currentColor" stroke="none" />
    <circle cx="17.3" cy="10.6" r="1.05" fill="currentColor" stroke="none" />
    <circle cx="8.6" cy="7.4" r="1.05" fill="currentColor" stroke="none" />
    <circle cx="6.7" cy="12.4" r="1.05" fill="currentColor" stroke="none" />
    <path d="M12 2a10 10 0 0 0 0 20c.9 0 1.6-.7 1.6-1.6 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H16a6 6 0 0 0 6-6C22 6 17.5 2 12 2Z" />
  </Svg>
);
/* Eine Person mit einem Haken: jemanden um eine Zusage bitten. */
const IconFreigabe = () => (
  <Svg>
    <path d="M15 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1" />
    <circle cx="8.5" cy="7" r="3.5" />
    <path d="m16 11.5 2 2 4-4" />
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
