"use client";

import { useEffect, useId, useRef, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "./cn";

/* false beim Server-Rendern, true im Browser. So steht fest, ob es ein document.body zum
 * Hineinportalen gibt, ohne setState in einem Effect. */
const subscribe = () => () => {};
const useIsBrowser = () =>
  useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}

/* Dialog aus Glas über abgedunkeltem Raum. Escape und Klick auf den Hintergrund schließen, der Fokus springt ins Feld.
 *
 * Der Dialog wird per Portal an document.body gehängt, nicht dort gerendert, wo er im JSX steht.
 * Grund: `.glass` setzt `backdrop-filter`, und ein Element mit backdrop-filter wird zum Containing
 * Block für `position: fixed` darunter. Ohne Portal klebt der Dialog also in der Glaskarte, aus der
 * heraus er geöffnet wurde, statt über der ganzen Seite zu liegen. */
export function Modal({ open, onClose, title, description, children, className }: ModalProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  /* Portale gibt es erst im Browser; beim Server-Rendern bleibt der Dialog aus. */
  const isBrowser = useIsBrowser();

  /* onClose wird an jeder Aufrufstelle als neue Pfeilfunktion übergeben und wechselt darum bei
   * jedem Rendern der umgebenden Komponente seine Identität. Stünde es in der Abhängigkeitsliste
   * des Effekts, liefe der Effekt nach jedem getippten Zeichen neu: das Aufräumen gibt den Fokus
   * an das Element zurück, aus dem der Dialog geöffnet wurde, der neue Lauf setzt ihn auf das
   * erste Bedienelement im Dialog. Der Cursor springt also aus dem Textfeld. Deshalb liegt der
   * Rückruf in einer Ref und der Effekt hängt nur am Öffnen und Schließen. */
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    /* Erst das Eingabefeld, sonst das erste Bedienelement. In der DOM-Reihenfolge stünde sonst
     * immer der Schließen-Knopf aus der Kopfzeile vorn. */
    const first = panel?.querySelector<HTMLElement>("input, textarea, select") ?? panel?.querySelector<HTMLElement>("button");
    first?.focus();
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!open || !isBrowser) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(
          "glass glass-strong max-h-[92dvh] w-full max-w-[560px] overflow-y-auto rounded-t-card p-6 sm:rounded-card sm:p-8",
          className,
        )}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 id={titleId} className="text-xl font-semibold tracking-[var(--tracking-display)]">
              {title}
            </h2>
            {description && <p className="mt-1 text-sm text-text-2">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Schließen"
            className="transition-soft flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line text-text-2 hover:border-line-strong hover:text-text"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
