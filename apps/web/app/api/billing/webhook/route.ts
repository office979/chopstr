import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { isHandledStripeEvent, mapStripeEvent, verifyStripeSignature } from "@/lib/billing/stripe";

export const dynamic = "force-dynamic";

/* POST: Stripe-Webhook ohne Sitzung (proxy.ts lässt den Pfad durch). Signaturprüfung über STRIPE_WEBHOOK_SECRET,
 * Ereignisse checkout.session.completed, customer.subscription.updated|deleted, invoice.paid|payment_failed
 * → subscriptions; billing_events idempotent über provider_event_id (Duplikat → 200 { duplicate: true }). */
export async function POST(request: NextRequest) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!secret) return Response.json({ error: "STRIPE_WEBHOOK_SECRET ist nicht gesetzt" }, { status: 503 });
  const body = await request.text();
  if (!verifyStripeSignature(body, request.headers.get("stripe-signature"), secret)) {
    return Response.json({ error: "Signatur ungültig" }, { status: 400 });
  }
  let event: { id?: unknown; type?: unknown; data?: unknown; livemode?: unknown };
  try {
    event = JSON.parse(body) as typeof event;
  } catch {
    return Response.json({ error: "Ungültiges JSON" }, { status: 400 });
  }
  const eventId = typeof event.id === "string" ? event.id : null;
  const type = event.type;
  if (!eventId || typeof type !== "string") return Response.json({ error: "Ereignis ohne id oder type" }, { status: 400 });
  if (!isHandledStripeEvent(type)) return Response.json({ ok: true, ignored: true, type });

  const repo = getRepo();
  const mapping = mapStripeEvent(type, event.data);
  const workspaceId = mapping.workspace_id ?? (await repo.findWorkspaceIdByProvider({ customer_id: mapping.customer_id, subscription_id: mapping.subscription_id }));

  const fresh = await repo.recordBillingEvent({
    provider: "stripe",
    provider_event_id: eventId,
    type,
    payload: { livemode: event.livemode ?? null, workspace_id: workspaceId, customer: mapping.customer_id, subscription: mapping.subscription_id, patch: mapping.patch as Record<string, unknown> },
    workspace_id: workspaceId,
  });
  if (!fresh) return Response.json({ ok: true, duplicate: true, event_id: eventId });
  if (!workspaceId) {
    console.warn(`[billing] Webhook ${type} ${eventId}: kein Workspace zu Kunde ${mapping.customer_id ?? "?"} / Abo ${mapping.subscription_id ?? "?"}`);
    return Response.json({ ok: true, unmatched: true, event_id: eventId });
  }
  const subscription = await repo.updateSubscriptionForWorkspace(workspaceId, mapping.patch);
  await repo.auditAs(
    { workspace_id: workspaceId, actor_id: null },
    { actor_type: "system", action: "billing.webhook", entity: "subscriptions", entity_id: subscription?.id ?? null, payload: { type, event_id: eventId, patch: mapping.patch as Record<string, unknown> } },
  );
  return Response.json({ ok: true, event_id: eventId, workspace_id: workspaceId, status: subscription?.status ?? null });
}
