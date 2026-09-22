"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { requireRole } from "@/lib/session";
import { isForbiddenError } from "@/lib/auth/permissions";
import { field, type FormState } from "@/lib/auth/form";
import { generateWebhookSecret, normalizeEvents, webhookUrlProblem } from "@/lib/api/webhooks";
import { emitOutbox } from "@/lib/outbox";
import { WEBHOOK_PING_EVENT } from "@/lib/repo/types-api";

/* Server Actions der Webhook-Verwaltung (api.manage). Das Secret steht nur einmal in `secret` der Antwort. */

export interface WebhookFormState extends FormState {
  secret?: string;
  secretUrl?: string;
}

function denied(error: unknown): FormState | null {
  if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
  return null;
}

export async function createWebhookAction(_prev: WebhookFormState, formData: FormData): Promise<WebhookFormState> {
  try {
    await requireRole("api.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const url = field(formData, "url", 2048);
  const { events, unknown } = normalizeEvents(formData.getAll("events"));
  const errors: Record<string, string> = {};
  const problem = webhookUrlProblem(url);
  if (problem) errors.url = problem;
  if (events.length === 0 || unknown.length) errors.events = "Mindestens ein Ereignis aus der Liste wählen.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const secret = generateWebhookSecret();
  const endpoint = await getApiRepo().createWebhookEndpoint({ url, events, secret, active: true });
  await getRepo().audit({ action: "webhook.created", entity: "webhook_endpoints", entity_id: endpoint.id, payload: { url, events } });
  revalidatePath("/einstellungen/webhooks");
  return { ok: true, message: "Webhook angelegt. Kopiere das Secret jetzt, es wird nur einmal angezeigt.", errors: {}, secret, secretUrl: url };
}

export async function toggleWebhookAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requireRole("api.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const id = field(formData, "id", 40);
  const active = field(formData, "active", 5) === "true";
  const endpoint = await getApiRepo().updateWebhookEndpoint(id, { active });
  if (!endpoint) return { ok: false, message: "Webhook nicht gefunden.", errors: {} };
  await getRepo().audit({ action: active ? "webhook.activated" : "webhook.deactivated", entity: "webhook_endpoints", entity_id: endpoint.id, payload: { url: endpoint.url } });
  revalidatePath("/einstellungen/webhooks");
  return { ok: true, message: active ? "Webhook aktiv." : "Webhook pausiert.", errors: {} };
}

export async function deleteWebhookAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requireRole("api.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const id = field(formData, "id", 40);
  const apiRepo = getApiRepo();
  const endpoint = await apiRepo.getWebhookEndpoint(id);
  if (!endpoint) return { ok: false, message: "Webhook nicht gefunden.", errors: {} };
  await apiRepo.deleteWebhookEndpoint(id);
  await getRepo().audit({ action: "webhook.deleted", entity: "webhook_endpoints", entity_id: endpoint.id, payload: { url: endpoint.url } });
  revalidatePath("/einstellungen/webhooks");
  return { ok: true, message: "Webhook gelöscht.", errors: {} };
}

/* Ping: Outbox-Ereignis webhook.ping (sofort als verarbeitet markiert) plus eine Zustellung direkt an diesen
 * Endpunkt, damit der Test unabhängig von den abonnierten Ereignissen ankommt. Zustellung macht der Worker. */
export async function pingWebhookAction(_prev: FormState, formData: FormData): Promise<FormState> {
  let session;
  try {
    session = await requireRole("api.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const id = field(formData, "id", 40);
  const apiRepo = getApiRepo();
  const endpoint = await apiRepo.getWebhookEndpoint(id);
  if (!endpoint) return { ok: false, message: "Webhook nicht gefunden.", errors: {} };
  const payload = { endpoint_id: endpoint.id, workspace_id: session.workspaceId, workspace_name: session.workspaceName, message: "Testzustellung aus chopstr", sent_at: new Date().toISOString() };
  const event = await emitOutbox(session.workspaceId, WEBHOOK_PING_EVENT, "webhook_endpoint", endpoint.id, payload, { processed: true });
  const delivery = await apiRepo.createWebhookDelivery({ endpoint_id: endpoint.id, outbox_id: event?.id ?? null, event: WEBHOOK_PING_EVENT, payload });
  await getRepo().audit({ action: "webhook.ping", entity: "webhook_endpoints", entity_id: endpoint.id, payload: { delivery_id: delivery.id, outbox_id: event?.id ?? null } });
  revalidatePath("/einstellungen/webhooks");
  return {
    ok: true,
    message: endpoint.active ? "Ping eingeplant. Der Worker stellt in den nächsten 30 Sekunden zu; Status unten in der Liste." : "Ping eingeplant, aber der Webhook ist pausiert: Die Zustellung wird als fehlgeschlagen markiert.",
    errors: {},
  };
}
