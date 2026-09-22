"use client";

import { useActionState, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Checkbox } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { formatDateTime } from "@/lib/format";
import { WEBHOOK_EVENTS, WEBHOOK_EVENT_LABELS, type WebhookDelivery, type WebhookEndpoint } from "@/lib/repo/types-api";
import { createWebhookAction, deleteWebhookAction, pingWebhookAction, toggleWebhookAction, type WebhookFormState } from "./actions";

interface Props {
  endpoints: WebhookEndpoint[];
  deliveries: WebhookDelivery[];
  demo: boolean;
}

const initialCreateState: WebhookFormState = { ok: false, message: "", errors: {} };

const STATUS_LABEL: Record<WebhookDelivery["status"], string> = { pending: "Ausstehend", delivered: "Zugestellt", failed: "Fehlgeschlagen" };

export function WebhooksPanel({ endpoints, deliveries, demo }: Props) {
  const [state, create, creating] = useActionState(createWebhookAction, initialCreateState);
  return (
    <div className="flex flex-col gap-5">
      {state.secret && <SecretCard secret={state.secret} url={state.secretUrl ?? ""} />}

      <form action={create} noValidate>
        <GlassCard padding="lg" className="flex flex-col gap-5">
          <div>
            <h2 className="text-lg font-medium">Neuen Webhook anlegen</h2>
            <p className="mt-1 text-sm text-text-2">
              Nur https, kein privater Host. Jede Zustellung trägt <code className="font-mono text-xs">X-Chopstr-Signature: t=…,v1=…</code> (HMAC-SHA256 über <code className="font-mono text-xs">t.body</code>). Bis zu fünf Wiederholungen mit Backoff.
            </p>
          </div>
          <Field label="URL" htmlFor="url" required error={state.errors.url}>
            <Input id="url" name="url" type="url" placeholder="https://example.com/hooks/chopstr" inputMode="url" />
          </Field>
          <fieldset className="flex flex-col gap-3">
            <legend className="text-sm font-medium text-text">Ereignisse</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {WEBHOOK_EVENTS.map((event) => (
                <label key={event} className="flex cursor-pointer items-start gap-3 rounded-inner border border-line p-3 hover:border-line-strong">
                  <Checkbox name="events" value={event} defaultChecked={event === "source.ready" || event === "clip.rendered"} />
                  <span className="flex flex-col">
                    <span className="font-mono text-xs text-text">{event}</span>
                    <span className="text-sm text-text-2">{WEBHOOK_EVENT_LABELS[event]}</span>
                  </span>
                </label>
              ))}
            </div>
            {state.errors.events && (
              <p className="text-sm text-attention" role="alert">
                {state.errors.events}
              </p>
            )}
          </fieldset>
          {!state.secret && <FormNotice state={state} />}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-text-2">Payloads enthalten IDs, Titel, Status und URLs, nie Transkripte oder Hook-Texte.</p>
            <Button type="submit" disabled={creating}>
              {creating ? "Wird angelegt" : "Webhook anlegen"}
            </Button>
          </div>
        </GlassCard>
      </form>

      <GlassCard padding="lg" className="flex flex-col gap-4">
        <h2 className="text-lg font-medium">Endpunkte</h2>
        {endpoints.length === 0 ? (
          <p className="text-sm text-text-2">Noch kein Webhook. Leg oben einen an.</p>
        ) : (
          <ul className="divide-y divide-line">
            {endpoints.map((e) => (
              <EndpointRow key={e.id} endpoint={e} />
            ))}
          </ul>
        )}
      </GlassCard>

      <GlassCard padding="lg" className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-medium">Zustellungen</h2>
          <p className="mt-1 text-sm text-text-2">{demo ? "Im Demo-Modus stellt kein Worker zu; Einträge bleiben ausstehend." : "Die letzten 100 Zustellungen aller Endpunkte. Der Worker wiederholt fehlgeschlagene Versuche nach 1, 5, 30, 120 und 720 Minuten."}</p>
        </div>
        {deliveries.length === 0 ? (
          <p className="text-sm text-text-2">Noch keine Zustellungen.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-text-2">
                  <th className="py-2 pr-4 font-medium">Zeit</th>
                  <th className="py-2 pr-4 font-medium">Ereignis</th>
                  <th className="py-2 pr-4 font-medium">Endpunkt</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Versuche</th>
                  <th className="py-2 pr-4 font-medium">Antwort</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {deliveries.map((d) => {
                  const endpoint = endpoints.find((e) => e.id === d.endpoint_id);
                  return (
                    <tr key={d.id}>
                      <td className="py-2 pr-4 font-mono text-xs text-text-2">{formatDateTime(d.created_at)}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-text">{d.event}</td>
                      <td className="max-w-[260px] truncate py-2 pr-4 text-text-2" title={endpoint?.url}>
                        {endpoint ? hostOf(endpoint.url) : "gelöscht"}
                      </td>
                      <td className="py-2 pr-4">
                        <Badge tone={d.status === "delivered" ? "ok" : d.status === "failed" ? "attention" : "ai"}>{STATUS_LABEL[d.status]}</Badge>
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs text-text">{d.attempt}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-text-2">
                        {d.response_code ?? "–"}
                        {d.error ? <span className="ml-2 text-attention">{d.error.slice(0, 80)}</span> : null}
                        {d.status === "pending" && d.attempt > 0 ? <span className="ml-2">nächster Versuch {formatDateTime(d.next_attempt_at)}</span> : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

function hostOf(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

function SecretCard({ secret, url }: { secret: string; url: string }) {
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
        <h2 className="text-lg font-medium">Webhook für {hostOf(url)} angelegt</h2>
        <Badge tone="attention">Secret nur einmal sichtbar</Badge>
      </div>
      <p className="text-sm text-text-2">Mit diesem Secret prüft dein Empfänger die Signatur. Nach dem Verlassen der Seite lässt es sich nicht mehr anzeigen; dann Webhook löschen und neu anlegen.</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <code className="flex-1 select-all break-all rounded-inner border border-line bg-black/50 px-4 py-3 font-mono text-sm text-text">{secret}</code>
        <Button variant="ghost" size="sm" onClick={copy}>
          {copied ? "Kopiert" : "Kopieren"}
        </Button>
      </div>
    </GlassCard>
  );
}

function EndpointRow({ endpoint }: { endpoint: WebhookEndpoint }) {
  const [toggleState, toggle, toggling] = useActionState(toggleWebhookAction, initialFormState);
  const [pingState, ping, pinging] = useActionState(pingWebhookAction, initialFormState);
  const [deleteState, remove, deleting] = useActionState(deleteWebhookAction, initialFormState);
  const [confirmDelete, setConfirmDelete] = useState(false);
  return (
    <li className="flex flex-col gap-3 py-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 font-medium text-text">
            <span className="break-all">{endpoint.url}</span>
            <Badge tone={endpoint.active ? "ok" : "attention"}>{endpoint.active ? "aktiv" : "pausiert"}</Badge>
          </p>
          <p className="mt-1 flex flex-wrap gap-1">
            {endpoint.events.map((e) => (
              <code key={e} className="rounded-pill border border-line px-2 py-0.5 font-mono text-[11px] text-text-2">
                {e}
              </code>
            ))}
          </p>
          <p className="mt-1 text-xs text-text-2">Angelegt {formatDateTime(endpoint.created_at)}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <form action={ping}>
            <input type="hidden" name="id" value={endpoint.id} />
            <Button type="submit" variant="ghost" size="sm" disabled={pinging}>
              {pinging ? "Wird gesendet" : "Ping"}
            </Button>
          </form>
          <form action={toggle}>
            <input type="hidden" name="id" value={endpoint.id} />
            <input type="hidden" name="active" value={endpoint.active ? "false" : "true"} />
            <Button type="submit" variant="ghost" size="sm" disabled={toggling}>
              {endpoint.active ? "Pausieren" : "Aktivieren"}
            </Button>
          </form>
          {confirmDelete ? (
            <form action={remove} className="flex items-center gap-2">
              <input type="hidden" name="id" value={endpoint.id} />
              <Button type="submit" variant="danger" size="sm" disabled={deleting}>
                {deleting ? "Wird gelöscht" : "Wirklich löschen"}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                Abbrechen
              </Button>
            </form>
          ) : (
            <Button type="button" variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              Löschen
            </Button>
          )}
        </div>
      </div>
      <FormNotice state={pingState.message ? pingState : toggleState.message ? toggleState : deleteState} />
    </li>
  );
}
