"use client";

import { useActionState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import type { Workspace } from "@/lib/repo/types";
import { updateWorkspaceAction } from "./actions";

const REGIONS = [
  { value: "eu-central-1", label: "AWS Frankfurt (eu-central-1)" },
  { value: "eu-west-1", label: "AWS Irland (eu-west-1)" },
  { value: "eu-north-1", label: "AWS Stockholm (eu-north-1)" },
  { value: "hetzner-fsn1", label: "Hetzner Falkenstein (fsn1)" },
  { value: "hetzner-nbg1", label: "Hetzner Nürnberg (nbg1)" },
  { value: "hetzner-hel1", label: "Hetzner Helsinki (hel1)" },
];

export function GeneralForm({ workspace, planName, editable }: { workspace: Workspace; planName: string; editable: boolean }) {
  const [state, action, pending] = useActionState(updateWorkspaceAction, initialFormState);
  return (
    <form action={action} noValidate>
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">Allgemein</h2>
          <span className="flex items-center gap-2">
            <Badge>{workspace.tier === "sovereign" ? "Sovereign" : "Standard"}</Badge>
            <Badge tone="ok">{planName}</Badge>
          </span>
        </div>
        <Field label="Name" htmlFor="name" required error={state.errors.name}>
          <Input id="name" name="name" defaultValue={workspace.name} required disabled={!editable} />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Slug" htmlFor="slug" hint="Wird in URLs und Exporten verwendet, nicht änderbar.">
            <Input id="slug" name="slug" value={workspace.slug} readOnly disabled className="font-mono" />
          </Field>
          <Field label="Tarif" htmlFor="tier" hint="Wechsel über Abrechnung.">
            <Input id="tier" name="tier" value={workspace.tier === "sovereign" ? "Sovereign" : "Standard"} readOnly disabled />
          </Field>
        </div>
        <Field label="Datenregion" htmlFor="data_region" error={state.errors.data_region} hint="Objektspeicher und Verarbeitung bleiben in dieser Region.">
          <Select id="data_region" name="data_region" defaultValue={workspace.data_region} disabled={!editable}>
            {!REGIONS.some((r) => r.value === workspace.data_region) && <option value={workspace.data_region}>{workspace.data_region}</option>}
            {REGIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Aufbewahrung Quellmaterial (Tage)" htmlFor="retention_days" error={state.errors.retention_days} hint="Danach wird die Quelle automatisch gelöscht, der Nachweis bleibt im Audit-Log.">
            <Input id="retention_days" name="retention_days" type="number" min={1} max={3650} defaultValue={workspace.retention_days} disabled={!editable} />
          </Field>
          <Field label="Aufbewahrung Renders (Tage)" htmlFor="render_retention_days" error={state.errors.render_retention_days}>
            <Input id="render_retention_days" name="render_retention_days" type="number" min={1} max={3650} defaultValue={workspace.render_retention_days} disabled={!editable} />
          </Field>
        </div>
        <FormNotice state={state} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-text-2">{editable ? "Änderungen landen im Audit-Log." : "Nur Inhaber und Admins können diese Werte ändern."}</p>
          <Button type="submit" disabled={pending || !editable}>
            {pending ? "Wird gespeichert" : "Speichern"}
          </Button>
        </div>
      </GlassCard>
    </form>
  );
}
