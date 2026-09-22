"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui/Button";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState, type FormState } from "@/lib/auth/form";

interface ConfirmFormProps {
  action: (prev: FormState, formData: FormData) => Promise<FormState>;
  label: string;
  pendingLabel?: string;
  hidden: Record<string, string>;
  disabled?: boolean;
  variant?: "primary" | "ghost" | "danger";
}

/* Ein Button, der eine Server Action mit versteckten Feldern auslöst (Magic-Link, Verifizierung, Einladung) */
export function ConfirmForm({ action, label, pendingLabel, hidden, disabled, variant = "primary" }: ConfirmFormProps) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  return (
    <form action={formAction} className="flex flex-col gap-4">
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <FormNotice state={state} />
      <div>
        <Button type="submit" variant={variant} disabled={pending || disabled}>
          {pending ? pendingLabel ?? label : label}
        </Button>
      </div>
    </form>
  );
}
