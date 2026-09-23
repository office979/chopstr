"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";

interface Props {
  sourceId: string;
  title: string;
  size?: "sm" | "md";
  /* nach Erfolg: Umleitung zur Projektliste (Projektseite) oder nur Neuladen (Liste) */
  redirectTo?: string;
}

interface ApiResponse {
  error?: string;
  started?: boolean;
  message?: string;
}

/* „Löschen“ mit kurzer Rückfrage: Frage, ein Satz, Löschen oder Abbrechen. Die Löschung läuft über
 * deletion_jobs und den Worker; das Video verschwindet sofort aus den Listen.
 *
 * Die Schnittstelle verlangt weiterhin den Titel als Bestätigung, damit ein Programm nicht aus
 * Versehen löscht. In der Oberfläche ist die Rückfrage der Dialog selbst, darum schickt der Knopf
 * den Titel direkt mit. Die öffentliche API macht es in app/api/v1/sources/[id] genauso. */
export function DeleteSourceButton({ sourceId, title, size = "sm", redirectTo }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const router = useRouter();

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_title: title }),
      });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok) throw new Error(data.error ?? "Löschen fehlgeschlagen");
      setDone(data.message ?? (data.started ? "Löschung läuft." : "Löschung eingeplant, Nachweis folgt."));
      window.setTimeout(() => {
        if (redirectTo) router.push(redirectTo);
        else router.refresh();
      }, 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Löschen fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button variant="danger" size={size} onClick={() => setOpen(true)}>
        Löschen
      </Button>
      <Modal
        open={open}
        onClose={() => !busy && setOpen(false)}
        title={`„${title}“ löschen?`}
        description="Das Video und alle Clips daraus verschwinden. Das kannst du nicht rückgängig machen."
      >
        {done ? (
          <p role="status" className="text-sm text-text">
            {done}
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {error && (
              <p role="alert" className="text-sm text-attention">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
                Abbrechen
              </Button>
              <Button type="button" variant="danger" onClick={() => void run()} disabled={busy} className="border border-danger/50">
                {busy ? "Wird gelöscht" : "Löschen"}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}
