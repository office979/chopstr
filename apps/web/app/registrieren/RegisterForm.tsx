"use client";

import { useActionState } from "react";
import { Field, Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { registerAction } from "./actions";

export function RegisterForm({ demo }: { demo: boolean }) {
  const [state, action, pending] = useActionState(registerAction, initialFormState);
  return (
    <form action={action} className="flex flex-col gap-5" noValidate>
      <Field label="Dein Name" htmlFor="display_name" required error={state.errors.display_name}>
        <Input id="display_name" name="display_name" autoComplete="name" placeholder="Vor- und Nachname" required disabled={demo} />
      </Field>
      <Field label="E-Mail" htmlFor="email" required error={state.errors.email}>
        <Input id="email" name="email" type="email" autoComplete="email" placeholder="du@agentur.at" required disabled={demo} />
      </Field>
      <Field label="Passwort" htmlFor="password" required error={state.errors.password} hint="Mindestens 10 Zeichen, Buchstaben und eine Ziffer.">
        <Input id="password" name="password" type="password" autoComplete="new-password" required disabled={demo} />
      </Field>
      <Field label="Firma oder Agentur" htmlFor="company" required error={state.errors.company} hint="Wird der Name deines Teams.">
        <Input id="company" name="company" autoComplete="organization" placeholder="z. B. PLACEMedia" required disabled={demo} />
      </Field>
      <FormNotice state={state} />
      <p className="text-sm text-text-2">
        Du startest im Tarif Starter mit 14 Tagen Test (4 Stunden Quellmaterial pro Monat). Kein Zahlungsmittel nötig.
      </p>
      <div>
        <Button type="submit" disabled={pending || demo}>
          {pending ? "Wird angelegt" : "Konto anlegen"}
        </Button>
      </div>
    </form>
  );
}
