import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, notFound } from "@/lib/api/errors";

export const dynamic = "force-dynamic";

export const DELETE = apiRoute<{ id: string }>("admin", async (_request, { params, auth }) => {
  const apiRepo = getApiRepo();
  const endpoint = await apiRepo.getWebhookEndpoint(params.id);
  if (!endpoint) throw notFound("Webhook nicht gefunden.");
  await apiRepo.deleteWebhookEndpoint(endpoint.id);
  await getRepo().audit({ action: "webhook.deleted", entity: "webhook_endpoints", entity_id: endpoint.id, payload: { url: endpoint.url, via: "api", api_key_id: auth.key.id } });
  return apiJson({ ok: true });
});
