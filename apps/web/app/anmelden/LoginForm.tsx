"use client";

import Link from "next/link";
import { useActionState } from "react";
import { Field, Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { loginAction } from "./actions";

export function LoginForm({ next, demo }: { next: string; demo: boolean }) {
  const [state, action, pending] = useActionState(loginAction, initialFormState);
  return (
    <form action={action} className="flex flex-col gap-5" noValidate>
      <input type="hidden" name="next" value={next} />
      <Field label="E-Mail" htmlFor="email" required error={state.errors.email}>
        <Input id="email" name="email" type="email" autoComplete="email" placeholder="du@agentur.at" required disabled={demo} />
      </Field>
      <Field label="Passwort" htmlFor="password" error={state.errors.password}>
        <Input id="password" name="password" type="password" autoComplete="current-password" disabled={demo} />
      </Field>
      <FormNotice state={state} />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button type="submit" name="intent" value="password" disabled={pending || demo}>
          {pending ? "Wird geprüft" : "Anmelden"}
        </Button>
        <Button type="submit" name="intent" value="magic" variant="ghost" disabled={pending || demo}>
          Magic-Link senden
        </Button>
      </div>
      <p className="text-sm text-text-2">
        <Link href="/passwort" className="text-text hover:underline">
          Passwort vergessen
        </Link>
      </p>
    </form>
  );
}
