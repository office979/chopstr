"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";

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

/* „Löschen“ mit Bestätigungsdialog: der Titel muss exakt eingegeben werden. Löschung läuft über deletion_jobs
 * und den Worker; die Quelle verschwindet sofort aus den Listen. */
export function DeleteSourceButton({ sourceId, title, size = "sm", redirectTo }: Props) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const router = useRouter();
  const id = useId();
  const matches = confirm.trim() === title.trim();

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_title: confirm }),
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
        title="Projekt löschen"
        description="Original, Proxy, Transkript, Kandidaten und alle Clips werden aus dem Objektspeicher und der Datenbank entfernt. Der Löschnachweis bleibt im Audit-Log."
      >
        {done ? (
          <p role="status" className="text-sm text-text">
            {done}
          </p>
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (matches) void run();
            }}
            noValidate
          >
            <Field label={`Zur Bestätigung den Titel eingeben: ${title}`} htmlFor={id} required>
              <Input id={id} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" placeholder={title} />
            </Field>
            {error && (
              <p role="alert" className="text-sm text-attention">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
                Abbrechen
              </Button>
              <Button type="submit" variant="danger" disabled={!matches || busy} className="border border-danger/50">
                {busy ? "Wird gelöscht" : "Endgültig löschen"}
              </Button>
            </div>
          </form>
        )}
      </Modal>
    </>
  );
}
