"use client";

import { useActionState } from "react";
import { Field, Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { registerViaInviteAction } from "./actions";

export function InviteRegisterForm({ token, email, demo }: { token: string; email: string; demo: boolean }) {
  const [state, action, pending] = useActionState(registerViaInviteAction, initialFormState);
  return (
    <form action={action} className="flex flex-col gap-5" noValidate>
      <input type="hidden" name="token" value={token} />
      <Field label="E-Mail" htmlFor="email" hint="Die Adresse stammt aus der Einladung.">
        <Input id="email" name="email" type="email" value={email} readOnly disabled />
      </Field>
      <Field label="Dein Name" htmlFor="display_name" required error={state.errors.display_name}>
        <Input id="display_name" name="display_name" autoComplete="name" required disabled={demo} />
      </Field>
      <Field label="Passwort" htmlFor="password" required error={state.errors.password} hint="Mindestens 10 Zeichen, Buchstaben und eine Ziffer.">
        <Input id="password" name="password" type="password" autoComplete="new-password" required disabled={demo} />
      </Field>
      <FormNotice state={state} />
      <div>
        <Button type="submit" disabled={pending || demo}>
          {pending ? "Wird angelegt" : "Konto anlegen und beitreten"}
        </Button>
      </div>
    </form>
  );
}
