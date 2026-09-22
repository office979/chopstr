"use client";

import { useActionState } from "react";
import { Field, Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { resetPasswordAction } from "../actions";

export function ResetForm({ token, demo }: { token: string; demo: boolean }) {
  const [state, action, pending] = useActionState(resetPasswordAction, initialFormState);
  return (
    <form action={action} className="flex flex-col gap-5" noValidate>
      <input type="hidden" name="token" value={token} />
      <Field label="Neues Passwort" htmlFor="password" required error={state.errors.password} hint="Mindestens 10 Zeichen, Buchstaben und eine Ziffer.">
        <Input id="password" name="password" type="password" autoComplete="new-password" required disabled={demo} />
      </Field>
      <Field label="Passwort wiederholen" htmlFor="password_confirm" required error={state.errors.password_confirm}>
        <Input id="password_confirm" name="password_confirm" type="password" autoComplete="new-password" required disabled={demo} />
      </Field>
      <FormNotice state={state} />
      <div>
        <Button type="submit" disabled={pending || demo}>
          {pending ? "Wird gespeichert" : "Passwort setzen und anmelden"}
        </Button>
      </div>
    </form>
  );
}
