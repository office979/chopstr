"use client";

import { useActionState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { resendVerificationAction, updateProfileAction } from "./actions";

interface Props {
  displayName: string;
  email: string;
  emailVerified: boolean;
  locale: string;
  demo: boolean;
}

export function ProfileForm({ displayName, email, emailVerified, locale, demo }: Props) {
  const [state, action, pending] = useActionState(updateProfileAction, initialFormState);
  const [resendState, resend, resending] = useActionState(resendVerificationAction, initialFormState);
  return (
    <div className="flex flex-col gap-5">
      <form action={action} noValidate>
        <GlassCard padding="lg" className="flex flex-col gap-5">
          <h2 className="text-lg font-medium">Konto</h2>
          <Field label="Anzeigename" htmlFor="display_name" required error={state.errors.display_name}>
            <Input id="display_name" name="display_name" defaultValue={displayName} autoComplete="name" required disabled={demo} />
          </Field>
          <Field
            label="E-Mail"
            htmlFor="email"
            required
            error={state.errors.email}
            hint={emailVerified ? "Bestätigt. Eine Änderung muss neu bestätigt werden." : "Noch nicht bestätigt."}
          >
            <div className="flex items-center gap-3">
              <Input id="email" name="email" type="email" defaultValue={email} autoComplete="email" required disabled={demo} />
              <Badge tone={emailVerified ? "ok" : "attention"} className="shrink-0">
                {emailVerified ? "bestätigt" : "offen"}
              </Badge>
            </div>
          </Field>
          <Field label="Sprache" htmlFor="locale" error={state.errors.locale} hint="Steuert Datums- und Zahlenformat in der App.">
            <Select id="locale" name="locale" defaultValue={locale} disabled={demo}>
              <option value="de-AT">Deutsch (Österreich)</option>
              <option value="de-DE">Deutsch (Deutschland)</option>
              <option value="de-CH">Deutsch (Schweiz)</option>
            </Select>
          </Field>
          <FormNotice state={state} />
          <div>
            <Button type="submit" disabled={pending || demo}>
              {pending ? "Wird gespeichert" : "Speichern"}
            </Button>
          </div>
        </GlassCard>
      </form>
      {!emailVerified && (
        <form action={resend}>
          <GlassCard padding="lg" className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">E-Mail bestätigen</h2>
            <p className="text-sm text-text-2">Ohne Bestätigung funktionieren Magic-Link und Passwort-Reset nur eingeschränkt.</p>
            <FormNotice state={resendState} />
            <div>
              <Button type="submit" variant="ghost" disabled={resending || demo}>
                {resending ? "Wird gesendet" : "Bestätigung erneut senden"}
              </Button>
            </div>
          </GlassCard>
        </form>
      )}
    </div>
  );
}
