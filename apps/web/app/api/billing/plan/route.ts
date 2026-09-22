import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { appBaseUrl } from "@/lib/auth/url";
import { getBillingProvider } from "@/lib/billing/provider";

export const dynamic = "force-dynamic";

interface Body {
  plan_code?: unknown;
  cancel_at_period_end?: unknown;
}

/* POST { plan_code } → Planwechsel (manual: sofort, stripe: Umstellung oder Checkout-URL);
 * POST { cancel_at_period_end } → Kündigung zum Periodenende setzen oder zurücknehmen. Rolle billing.manage. */
export async function POST(request: NextRequest) {
  const auth = await requireApiRole("billing.manage");
  if (auth instanceof Response) return auth;
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const repo = getRepo();
  const provider = getBillingProvider();
  const subscription = await repo.getSubscription();

  if (typeof body.cancel_at_period_end === "boolean") {
    if (!subscription) return Response.json({ error: "Kein Abo vorhanden" }, { status: 409 });
    if (subscription.status === "canceled") return Response.json({ error: "Das Abo ist bereits gekündigt" }, { status: 409 });
    const updated = await provider.setCancelAtPeriodEnd({ repo, subscription, cancel: body.cancel_at_period_end });
    await repo.audit({
      action: body.cancel_at_period_end ? "billing.cancel_requested" : "billing.cancel_revoked",
      entity: "subscriptions",
      entity_id: updated.id,
      payload: { provider: provider.kind, period_end: updated.current_period_end },
    });
    return Response.json({ ok: true, subscription: updated, message: body.cancel_at_period_end ? "Gekündigt zum Ende der Periode." : "Kündigung zurückgenommen." });
  }

  const planCode = typeof body.plan_code === "string" ? body.plan_code : "";
  const plans = await repo.listPlans();
  const plan = plans.find((p) => p.code === planCode);
  if (!plan) return Response.json({ error: "Unbekannter Tarif" }, { status: 400 });
  if (subscription && subscription.plan_code === plan.code && subscription.status !== "trialing" && subscription.status !== "canceled" && !subscription.cancel_at_period_end) {
    return Response.json({ error: `Der Tarif ${plan.name} ist bereits aktiv.` }, { status: 409 });
  }
  try {
    const result = await provider.changePlan({ repo, session: auth, subscription, plan, origin: await appBaseUrl() });
    await repo.audit({
      action: result.redirect_url ? "billing.checkout_started" : "billing.plan_changed",
      entity: "subscriptions",
      entity_id: subscription?.id ?? result.subscription?.id ?? null,
      payload: { provider: provider.kind, from: subscription?.plan_code ?? null, to: plan.code, previous_status: subscription?.status ?? null },
    });
    return Response.json({ ok: true, provider: provider.kind, ...result });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Planwechsel fehlgeschlagen" }, { status: 502 });
  }
}
