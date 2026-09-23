"use client";

import { useActionState, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import type { Workspace } from "@/lib/repo/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { cancelWorkspaceDeletionAction, requestWorkspaceDeletionAction } from "./actions";

interface Props {
  workspace: Workspace;
  canDelete: boolean;
  demo: boolean;
}

/* Workspace-Löschung: nur der Inhaber, 30 Tage Karenz, Widerruf bis zum Stichtag */
export function WorkspaceDeletionCard({ workspace, canDelete, demo }: Props) {
  const [requestState, requestAction, requesting] = useActionState(requestWorkspaceDeletionAction, initialFormState);
  const [cancelState, cancelAction, canceling] = useActionState(cancelWorkspaceDeletionAction, initialFormState);
  const [confirm, setConfirm] = useState("");
  const scheduled = workspace.deletion_scheduled_for;

  return (
    <GlassCard padding="lg" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">Team löschen</h2>
          <p className="mt-1 max-w-xl text-sm text-text-2">
            Nach 30 Tagen Karenz werden alle Quellen, Clips, Transkripte, Mitgliedschaften und CI-Assets gelöscht. Der Löschnachweis bleibt im Audit-Log, die Rechnungsdaten
            bleiben für die gesetzliche Aufbewahrung.
          </p>
        </div>
        {scheduled && <Badge tone="attention">Eingeplant für {formatDate(scheduled)}</Badge>}
      </div>

      {scheduled ? (
        <form action={cancelAction} className="flex flex-col gap-3">
          <p className="text-sm text-text">
            Angefordert am {formatDateTime(workspace.deletion_requested_at)}. Ausführung am {formatDate(scheduled)} durch den Retention-Lauf.
          </p>
          <FormNotice state={cancelState} />
          {canDelete && (
            <div>
              <Button type="submit" variant="ghost" disabled={canceling}>
                {canceling ? "Wird zurückgenommen" : "Löschung zurücknehmen"}
              </Button>
            </div>
          )}
        </form>
      ) : canDelete ? (
        <form action={requestAction} className="flex flex-col gap-4" noValidate>
          <Field label={`Zur Bestätigung den Namen eingeben: ${workspace.name}`} htmlFor="confirm_name" required error={requestState.errors.confirm_name}>
            <Input id="confirm_name" name="confirm_name" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" placeholder={workspace.name} />
          </Field>
          <FormNotice state={requestState} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-text-2">{demo ? "Demo: nur im Speicher." : "Du bekommst eine E-Mail mit dem Stichtag."}</p>
            <Button type="submit" variant="danger" className="border border-danger/50" disabled={requesting || confirm.trim() !== workspace.name.trim()}>
              {requesting ? "Wird eingeplant" : "Löschung in 30 Tagen anfordern"}
            </Button>
          </div>
        </form>
      ) : (
        <p className="text-sm text-text-2">Nur der Inhaber kann das Team löschen.</p>
      )}
    </GlassCard>
  );
}
