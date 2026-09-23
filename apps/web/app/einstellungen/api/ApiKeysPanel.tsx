"use client";

import { useActionState, useState } from "react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select, Checkbox } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { formatDateTime } from "@/lib/format";
import { API_SCOPES, SCOPE_DESCRIPTIONS, SCOPE_LABELS, isApiKeyExpired, type ApiKey } from "@/lib/repo/types-api";
import { createApiKeyAction, revokeApiKeyAction, type ApiKeyFormState } from "./actions";

interface Props {
  keys: ApiKey[];
  demo: boolean;
}

const initialKeyState: ApiKeyFormState = { ok: false, message: "", errors: {} };

export function ApiKeysPanel({ keys, demo }: Props) {
  const [state, create, creating] = useActionState(createApiKeyAction, initialKeyState);
  const active = keys.filter((k) => !k.revoked_at);
  const revoked = keys.filter((k) => k.revoked_at);
  return (
    <div className="flex flex-col gap-5">
      {state.secret && <SecretCard secret={state.secret} name={state.secretName ?? ""} />}

      <form action={create} noValidate>
        <GlassCard padding="lg" className="flex flex-col gap-5">
          <div>
            <h2 className="text-lg font-medium">Neuen Schlüssel anlegen</h2>
            <p className="mt-1 text-sm text-text-2">
              Der Klartext erscheint nur einmal. Vergib nur die Scopes, die der Client braucht; für den MCP-Server reichen read und write.
            </p>
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Name" htmlFor="name" required error={state.errors.name} hint="z. B. Claude Desktop, Zapier, Redaktions-Skript">
              <Input id="name" name="name" placeholder="Claude Desktop" maxLength={80} />
            </Field>
            <Field label="Gültigkeit" htmlFor="expires" error={state.errors.expires}>
              <Select id="expires" name="expires" defaultValue="90">
                <option value="30">30 Tage</option>
                <option value="90">90 Tage</option>
                <option value="365">1 Jahr</option>
                <option value="never">Unbegrenzt</option>
              </Select>
            </Field>
          </div>
          <fieldset className="flex flex-col gap-3">
            <legend className="text-sm font-medium text-text">Scopes</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {API_SCOPES.map((scope) => (
                <label key={scope} className="flex cursor-pointer items-start gap-3 rounded-inner border border-line p-3 hover:border-line-strong">
                  <Checkbox name="scopes" value={scope} defaultChecked={scope === "read"} />
                  <span className="flex flex-col">
                    <span className="text-sm font-medium text-text">
                      {SCOPE_LABELS[scope]} <span className="font-mono text-xs text-text-3">{scope}</span>
                    </span>
                    <span className="text-sm text-text-2">{SCOPE_DESCRIPTIONS[scope]}</span>
                  </span>
                </label>
              ))}
            </div>
            {state.errors.scopes && (
              <p className="text-sm text-attention" role="alert">
                {state.errors.scopes}
              </p>
            )}
          </fieldset>
          {!state.secret && <FormNotice state={state} />}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-text-2">{demo ? "Demo: Schlüssel gelten nur, solange der Serverprozess läuft." : "Schlüssel gelten für dieses Team und laufen auf dein Konto."}</p>
            <Button type="submit" disabled={creating}>
              {creating ? "Wird angelegt" : "Schlüssel anlegen"}
            </Button>
          </div>
        </GlassCard>
      </form>

      <GlassCard padding="lg" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-medium">Aktive Schlüssel</h2>
          <Link href="/entwickler" className="text-sm text-text-2 underline-offset-4 hover:text-text hover:underline">
            Entwicklerseite mit Beispielen
          </Link>
        </div>
        {active.length === 0 ? (
          <p className="text-sm text-text-2">Noch kein Schlüssel. Leg oben einen an.</p>
        ) : (
          <ul className="divide-y divide-line">
            {active.map((k) => (
              <KeyRow key={k.id} apiKey={k} />
            ))}
          </ul>
        )}
      </GlassCard>

      {revoked.length > 0 && (
        <GlassCard padding="lg" className="flex flex-col gap-4">
          <h2 className="text-lg font-medium text-text-2">Widerrufene Schlüssel</h2>
          <ul className="divide-y divide-line">
            {revoked.map((k) => (
              <KeyRow key={k.id} apiKey={k} />
            ))}
          </ul>
        </GlassCard>
      )}
    </div>
  );
}

function SecretCard({ secret, name }: { secret: string; name: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <GlassCard padding="lg" selected className="flex flex-col gap-3" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-medium">Schlüssel „{name}“ angelegt</h2>
        <Badge tone="attention">Nur einmal sichtbar</Badge>
      </div>
      <p className="text-sm text-text-2">Kopiere den Schlüssel jetzt und lege ihn beim Client als CHOPSTR_API_KEY ab. Nach dem Verlassen der Seite lässt er sich nicht mehr anzeigen.</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <code className="flex-1 select-all break-all rounded-inner border border-line bg-black/50 px-4 py-3 font-mono text-sm text-text">{secret}</code>
        <Button variant="ghost" size="sm" onClick={copy}>
          {copied ? "Kopiert" : "Kopieren"}
        </Button>
      </div>
    </GlassCard>
  );
}

function KeyRow({ apiKey }: { apiKey: ApiKey }) {
  const [state, revoke, pending] = useActionState(revokeApiKeyAction, initialFormState);
  const expired = isApiKeyExpired(apiKey);
  const inactive = Boolean(apiKey.revoked_at) || expired;
  return (
    <li className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 font-medium text-text">
          <span className={inactive ? "text-text-2 line-through" : ""}>{apiKey.name}</span>
          <code className="font-mono text-xs text-text-2">chp_live_{apiKey.key_prefix}…</code>
          {apiKey.scopes.map((s) => (
            <Badge key={s} tone={s === "admin" ? "attention" : "neutral"}>
              {s}
            </Badge>
          ))}
          {apiKey.revoked_at && <Badge tone="danger">widerrufen</Badge>}
          {!apiKey.revoked_at && expired && <Badge tone="attention">abgelaufen</Badge>}
        </p>
        <p className="mt-1 text-xs text-text-2">
          Angelegt {formatDateTime(apiKey.created_at)}
          {apiKey.created_by_label ? ` von ${apiKey.created_by_label}` : ""} · Zuletzt genutzt {apiKey.last_used_at ? formatDateTime(apiKey.last_used_at) : "nie"} ·{" "}
          {apiKey.expires_at ? `Läuft ab ${formatDateTime(apiKey.expires_at)}` : "Unbegrenzt gültig"}
          {apiKey.revoked_at ? ` · Widerrufen ${formatDateTime(apiKey.revoked_at)}` : ""}
        </p>
        <FormNotice state={state} className="mt-1" />
      </div>
      {!apiKey.revoked_at && (
        <form action={revoke} className="shrink-0">
          <input type="hidden" name="id" value={apiKey.id} />
          <Button type="submit" variant="danger" size="sm" disabled={pending}>
            {pending ? "Wird widerrufen" : "Widerrufen"}
          </Button>
        </form>
      )}
    </li>
  );
}
