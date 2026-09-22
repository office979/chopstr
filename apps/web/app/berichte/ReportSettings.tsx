"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { setWeeklyReportAction } from "./actions";

/* Opt-out des Wochenberichts (owner, admin) */
export function ReportSettings({ enabled, canManage }: { enabled: boolean; canManage: boolean }) {
  const [state, action, pending] = useActionState(setWeeklyReportAction, initialFormState);
  return (
    <form action={action} className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-sm font-medium">E-Mail jeden Montag 07:00 an Inhaber und Admins</p>
        <p className="text-xs text-text-2">{enabled ? "Aktiv. Der Bericht wird zusätzlich hier gespeichert." : "Abbestellt. Berichte werden weiterhin hier gespeichert."}</p>
        <FormNotice state={state} className="mt-2" />
      </div>
      {canManage && (
        <>
          <input type="hidden" name="enabled" value={enabled ? "false" : "true"} />
          <Button type="submit" size="sm" variant="ghost" disabled={pending}>
            {pending ? "Wird gespeichert" : enabled ? "E-Mail abbestellen" : "E-Mail aktivieren"}
          </Button>
        </>
      )}
    </form>
  );
}
