"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Field, Input, Checkbox } from "@/components/ui/Field";

interface Props {
  version: string;
  defaultCompany: string;
  defaultRepresentative: string;
}

interface ApiResponse {
  error?: string;
  field?: string;
}

/* Annahme des AVV (owner, admin): Firma, Vertreter, Bestätigung → POST /api/dpa/accept */
export function DpaAcceptForm({ version, defaultCompany, defaultRepresentative }: Props) {
  const router = useRouter();
  const [company, setCompany] = useState(defaultCompany);
  const [representative, setRepresentative] = useState(defaultRepresentative);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; field?: string } | null>(null);
  const [done, setDone] = useState(false);
  const companyId = useId();
  const repId = useId();
  const checkId = useId();

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/dpa/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company, representative, accepted }),
      });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok) throw Object.assign(new Error(data.error ?? "Annahme fehlgeschlagen"), { field: data.field });
      setDone(true);
      router.refresh();
    } catch (err) {
      setError({ text: err instanceof Error ? err.message : "Annahme fehlgeschlagen", field: (err as { field?: string }).field });
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassCard padding="lg" className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-medium">AVV annehmen</h2>
        <p className="mt-1 text-sm text-text-2">Version {version}. Die Annahme wird mit Zeitpunkt, IP und deinem Konto im Audit-Log gespeichert.</p>
      </div>
      {done ? (
        <p role="status" className="text-sm text-text">
          Angenommen. Der Vertrag zeigt jetzt Firma, Vertreter und Zeitpunkt.
        </p>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          noValidate
        >
          <Field label="Firma (Verantwortlicher)" htmlFor={companyId} required error={error?.field === "company" ? error.text : undefined}>
            <Input id={companyId} value={company} onChange={(e) => setCompany(e.target.value)} autoComplete="organization" />
          </Field>
          <Field label="Vertreten durch" htmlFor={repId} required error={error?.field === "representative" ? error.text : undefined}>
            <Input id={repId} value={representative} onChange={(e) => setRepresentative(e.target.value)} autoComplete="name" placeholder="Vor- und Nachname, Funktion" />
          </Field>
          <label htmlFor={checkId} className="flex cursor-pointer items-start gap-3 text-sm text-text">
            <Checkbox id={checkId} checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>Ich bin berechtigt, diese Vereinbarung für die genannte Firma zu schließen, und nehme den AVV samt TOMs und Subprozessor-Liste an.</span>
          </label>
          {error && error.field !== "company" && error.field !== "representative" && (
            <p role="alert" className="text-sm text-attention">
              {error.text}
            </p>
          )}
          <div className="flex justify-end">
            <Button type="submit" disabled={busy || !accepted || company.trim().length < 2 || representative.trim().length < 2}>
              {busy ? "Wird gespeichert" : "AVV annehmen"}
            </Button>
          </div>
        </form>
      )}
    </GlassCard>
  );
}
