"use client";

import { useActionState } from "react";
import { Field, Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { requestResetAction } from "./actions";

export function RequestResetForm({ demo }: { demo: boolean }) {
  const [state, action, pending] = useActionState(requestResetAction, initialFormState);
  return (
    <form action={action} className="flex flex-col gap-5" noValidate>
      <Field label="E-Mail" htmlFor="email" required error={state.errors.email}>
        <Input id="email" name="email" type="email" autoComplete="email" required disabled={demo} />
      </Field>
      <FormNotice state={state} />
      <div>
        <Button type="submit" disabled={pending || demo}>
          {pending ? "Wird gesendet" : "Link senden"}
        </Button>
      </div>
    </form>
  );
}
