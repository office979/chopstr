import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { appBaseUrl } from "@/lib/auth/url";
import { getBillingProvider } from "@/lib/billing/provider";

export const dynamic = "force-dynamic";

/* POST { plan_code }: Stripe-Checkout-Session für Erstabo oder Planwechsel. Im manual-Modus 409 mit Hinweis. */
export async function POST(request: NextRequest) {
  const auth = await requireApiRole("billing.manage");
  if (auth instanceof Response) return auth;
  const provider = getBillingProvider();
  if (provider.kind !== "stripe") {
    return Response.json({ error: "Kein Zahlungsanbieter konfiguriert. Der Tarif wird manuell umgestellt, die Rechnung kommt per E-Mail.", code: "manual", href: "/api/billing/plan" }, { status: 409 });
  }
  let body: { plan_code?: unknown };
  try {
    body = (await request.json()) as { plan_code?: unknown };
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const repo = getRepo();
  const plan = (await repo.listPlans()).find((p) => p.code === body.plan_code);
  if (!plan) return Response.json({ error: "Unbekannter Tarif" }, { status: 400 });
  const subscription = await repo.getSubscription();
  try {
    const result = await provider.changePlan({ repo, session: auth, subscription, plan, origin: await appBaseUrl() });
    await repo.audit({
      action: result.redirect_url ? "billing.checkout_started" : "billing.plan_changed",
      entity: "subscriptions",
      entity_id: subscription?.id ?? null,
      payload: { provider: "stripe", from: subscription?.plan_code ?? null, to: plan.code },
    });
    return Response.json({ ok: true, ...result });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Checkout fehlgeschlagen" }, { status: 502 });
  }
}
