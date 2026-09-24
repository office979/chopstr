"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { setWeeklyReportAction } from "./actions";

/* Die Montagsmail: wer sie bekommt, wann, und ob sie überhaupt hinausgeht.
 *
 * Hier stand vorher „Aktiv." - unabhängig davon, ob der Versand eingerichtet ist. Ohne SMTP
 * landet die Nachricht in der Serverkonsole und erreicht niemanden; „aktiv" wäre dann eine
 * Zusage, die das Produkt nicht einlöst. Wer sich darauf verlässt, wartet Montag für Montag auf
 * eine Mail, die nie kommt.
 *
 * Deshalb stehen jetzt drei Dinge da, die vorher fehlten: an wen, in welcher Zeitzone, und ob der
 * Weg nach draussen offen ist.
 */
export function ReportSettings({
  enabled,
  canManage,
  versandMoeglich,
  empfaenger,
}: {
  enabled: boolean;
  canManage: boolean;
  /* Ist ein Mailversand eingerichtet? Ohne ihn gibt es keine Mail, nur einen Eintrag im Log. */
  versandMoeglich: boolean;
  empfaenger: string[];
}) {
  const [state, action, pending] = useActionState(setWeeklyReportAction, initialFormState);
  const aktiv = enabled && versandMoeglich;

  return (
    <form action={action} className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          <span
            aria-hidden="true"
            className={`inline-block h-2 w-2 rounded-full ${aktiv ? "bg-brand" : "bg-white/35"}`}
          />
          Wochenbericht per E-Mail
          <span className="text-text-3">
            {aktiv ? "aktiv" : enabled ? "eingeschaltet, geht aber nicht hinaus" : "abbestellt"}
          </span>
        </p>
        <p className="mt-1 text-xs text-text-2">
          Montags um 07:00 Uhr, Zeitzone Europa/Wien.{" "}
          {empfaenger.length > 0 ? `An ${empfaenger.join(", ")}.` : "An Inhaber und Verwaltende des Teams."}
        </p>
        {enabled && !versandMoeglich && (
          <p className="mt-1.5 text-xs text-attention">
            Für dieses Team ist noch kein Mailversand eingerichtet. Der Bericht entsteht trotzdem und
            steht hier auf der Seite, er wird nur nicht verschickt.
          </p>
        )}
        <p className="mt-1 text-xs text-text-3">Jeder Bericht bleibt hier gespeichert, auch ohne E-Mail.</p>
        <FormNotice state={state} className="mt-2" />
      </div>
      {canManage && (
        <>
          <input type="hidden" name="enabled" value={enabled ? "false" : "true"} />
          <Button type="submit" size="sm" variant="ghost" disabled={pending}>
            {pending ? "Wird gespeichert" : enabled ? "E-Mail abbestellen" : "E-Mail einschalten"}
          </Button>
        </>
      )}
    </form>
  );
}
