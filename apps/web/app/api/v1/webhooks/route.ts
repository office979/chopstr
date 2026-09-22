import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, badRequest } from "@/lib/api/errors";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { serializeWebhook } from "@/lib/api/serializers";
import { generateWebhookSecret, normalizeEvents, webhookUrlProblem } from "@/lib/api/webhooks";

export const dynamic = "force-dynamic";

export const GET = apiRoute("admin", async () => {
  const endpoints = await getApiRepo().listWebhookEndpoints();
  return apiJson({ webhooks: endpoints.map(serializeWebhook) });
});

/* Secret nur in dieser Antwort */
export const POST = apiRoute("admin", async (request: NextRequest, { auth }) => {
  const body = await readJsonBody<{ url: string; events: string[]; active?: boolean }>(request, requestSchema("CreateWebhook"), resolveRef);
  const problem = webhookUrlProblem(body.url.trim());
  if (problem) throw badRequest(problem, "url_not_allowed");
  const { events, unknown } = normalizeEvents(body.events);
  if (unknown.length) throw badRequest(`Unbekannte Ereignisse: ${unknown.join(", ")}.`, "validation_failed");
  if (!events.length) throw badRequest("Mindestens ein Ereignis wählen.", "validation_failed");
  const secret = generateWebhookSecret();
  const endpoint = await getApiRepo().createWebhookEndpoint({ url: body.url.trim(), events, secret, active: body.active ?? true });
  await getRepo().audit({ action: "webhook.created", entity: "webhook_endpoints", entity_id: endpoint.id, payload: { url: endpoint.url, events, via: "api", api_key_id: auth.key.id } });
  return apiJson({ webhook: serializeWebhook(endpoint), secret }, 201);
});
