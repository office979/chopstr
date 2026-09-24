"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { hatUngespeichert, VERLASSEN_FRAGE } from "@/lib/brand/ungespeichert";
import { duplicateBrandProfileAction } from "./actions";

/* Ein Link auf eine andere Marke, der vorher fragt.
 *
 * Bis hierher war das ein gewöhnlicher Link: wer eine Farbe geändert hatte und auf den nächsten
 * Kunden klickte, verlor die Änderung ohne Meldung. Der Browser fragt bei einem Wechsel innerhalb
 * der Seite nicht - das muss die Seite selbst tun. */
export function MarkeLink({
  href,
  className,
  ariaCurrent,
  children,
}: {
  href: string;
  className?: string;
  ariaCurrent?: boolean;
  children: ReactNode;
}) {
  const router = useRouter();
  const [frage, setFrage] = useState<string | null>(null);

  return (
    <>
      <Link
        href={href}
        aria-current={ariaCurrent ? "true" : undefined}
        className={className}
        onClick={(e) => {
          if (!hatUngespeichert()) return;
          e.preventDefault();
          setFrage(href);
        }}
      >
        {children}
      </Link>
      <Modal open={frage != null} onClose={() => setFrage(null)} title="Änderungen gehen verloren" description={VERLASSEN_FRAGE}>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setFrage(null)}>
            Hierbleiben
          </Button>
          <Button
            onClick={() => {
              const ziel = frage;
              setFrage(null);
              if (ziel) router.push(ziel);
            }}
          >
            Trotzdem wechseln
          </Button>
        </div>
      </Modal>
    </>
  );
}

/* Eine Marke für einen ähnlichen Kunden kopieren. Ohne Dateien: die gehören der anderen Marke,
 * und zwei Kunden auf dieselbe Datei zeigen zu lassen wäre genau die Vermischung, die eine
 * Agentur nicht gebrauchen kann. */
export function MarkeKopieren({ id }: { id: string }) {
  const router = useRouter();
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<string | null>(null);

  return (
    <>
      <button
        type="button"
        disabled={laeuft}
        onClick={async () => {
          setLaeuft(true);
          const r = await duplicateBrandProfileAction(id);
          setLaeuft(false);
          setMeldung(r.message);
          if (r.ok && r.id) router.push(`/marke?p=${r.id}`);
        }}
        className="transition-soft shrink-0 rounded-pill border border-line px-3 py-1 text-xs text-text-2 hover:border-line-strong hover:text-text disabled:opacity-50"
      >
        {laeuft ? "Wird kopiert" : "Kopieren"}
      </button>
      {meldung && (
        <p className="w-full text-sm text-text-2" role="status" aria-live="polite">
          {meldung}
        </p>
      )}
    </>
  );
}
