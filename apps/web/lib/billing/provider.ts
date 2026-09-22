import "server-only";
import type { Session } from "@/lib/session";
import type { Plan, Repo, Subscription } from "@/lib/repo/types";
import { priceForPlan } from "@/lib/billing/stripe";

/* Provider-Abstraktion für die Abrechnung (PHASE4.md, Abschnitt 5).
 *
 *   manual: Planwechsel schreibt subscriptions.plan_code direkt, die Rechnung kommt per E-Mail.
 *   stripe: Checkout-Session (Erstabo oder Planwechsel), Customer-Portal, Kündigung zum Periodenende
 *           über das SDK; Webhooks aktualisieren subscriptions (app/api/billing/webhook).
 *   mollie: Interface vorgesehen, kein Code in Phase 4.
 *
 * Auswahl über BILLING_PROVIDER (Default manual). Stripe ohne STRIPE_SECRET_KEY fällt auf manual zurück. */

export type ProviderKind = "manual" | "stripe";

export interface PlanChangeResult {
  /* Browser dahin umleiten (Stripe Checkout) */
  redirect_url?: string;
  subscription?: Subscription;
  message: string;
}

export interface BillingProvider {
  readonly kind: ProviderKind;
  changePlan(args: { repo: Repo; session: Session; subscription: Subscription | null; plan: Plan; origin: string }): Promise<PlanChangeResult>;
  setCancelAtPeriodEnd(args: { repo: Repo; subscription: Subscription; cancel: boolean }): Promise<Subscription>;
  /* Link zum Kundenportal (Rechnungen, Zahlungsmittel); null wenn es keines gibt */
  portalUrl(args: { subscription: Subscription | null; origin: string }): Promise<string | null>;
}

export function billingProviderKind(): ProviderKind {
  const raw = (process.env.BILLING_PROVIDER ?? "manual").toLowerCase();
  if (raw === "stripe" && process.env.STRIPE_SECRET_KEY) return "stripe";
  return "manual";
}

const manualProvider: BillingProvider = {
  kind: "manual",

  async changePlan({ repo, session, subscription, plan }) {
    const wasTrial = !subscription || subscription.status === "trialing";
    const periodEnd = new Date();
    periodEnd.setUTCMonth(periodEnd.getUTCMonth() + 1);
    const updated = await repo.updateSubscription({
      plan_code: plan.code,
      provider: "manual",
      status: wasTrial ? "active" : subscription.status,
      cancel_at_period_end: false,
      current_period_start: wasTrial ? new Date().toISOString() : subscription.current_period_start,
      current_period_end: wasTrial ? periodEnd.toISOString() : subscription.current_period_end,
      trial_ends_at: wasTrial ? null : subscription.trial_ends_at,
      billing_email: subscription?.billing_email ?? session.email,
    });
    return { subscription: updated, message: `Tarif ${plan.name} ist aktiv. Die Rechnung über ${plan.monthly_eur.toLocaleString("de-AT")} € pro Monat kommt per E-Mail.` };
  },

  async setCancelAtPeriodEnd({ repo, cancel }) {
    return repo.updateSubscription({ cancel_at_period_end: cancel });
  },

  async portalUrl() {
    return null;
  },
};

async function stripeSdk() {
  const { default: Stripe } = await import("stripe");
  return new Stripe(process.env.STRIPE_SECRET_KEY as string);
}

const stripeProvider: BillingProvider = {
  kind: "stripe",

  async changePlan({ repo, session, subscription, plan, origin }) {
    const price = priceForPlan(plan.code);
    if (!price) throw new Error(`Für den Tarif ${plan.name} ist kein Stripe-Preis hinterlegt (STRIPE_PRICE_${plan.code.toUpperCase()}).`);
    const stripe = await stripeSdk();

    /* Bestehendes Stripe-Abo: Preis direkt tauschen, anteilig verrechnet; Webhook schreibt den Rest */
    if (subscription?.provider === "stripe" && subscription.provider_subscription_id && subscription.status !== "canceled") {
      const current = await stripe.subscriptions.retrieve(subscription.provider_subscription_id);
      const item = current.items.data[0];
      await stripe.subscriptions.update(subscription.provider_subscription_id, {
        items: [{ id: item.id, price }],
        proration_behavior: "create_prorations",
        cancel_at_period_end: false,
        metadata: { workspace_id: session.workspaceId, plan_code: plan.code },
      });
      const updated = await repo.updateSubscription({ plan_code: plan.code, cancel_at_period_end: false });
      return { subscription: updated, message: `Tarif ${plan.name} bei Stripe umgestellt. Die Bestätigung kommt per Webhook.` };
    }

    const checkout = await stripe.checkout.sessions.create({
      mode: "subscription",
      customer: subscription?.provider_customer_id ?? undefined,
      customer_email: subscription?.provider_customer_id ? undefined : (subscription?.billing_email ?? session.email),
      client_reference_id: session.workspaceId,
      line_items: [{ price, quantity: 1 }],
      success_url: `${origin}/einstellungen/abrechnung?checkout=erfolg`,
      cancel_url: `${origin}/einstellungen/abrechnung?checkout=abbruch`,
      metadata: { workspace_id: session.workspaceId, plan_code: plan.code },
      subscription_data: { metadata: { workspace_id: session.workspaceId, plan_code: plan.code } },
      locale: "de",
      tax_id_collection: { enabled: true },
    });
    if (!checkout.url) throw new Error("Stripe hat keine Checkout-URL geliefert.");
    return { redirect_url: checkout.url, message: "Weiter zu Stripe." };
  },

  async setCancelAtPeriodEnd({ repo, subscription, cancel }) {
    if (subscription.provider_subscription_id) {
      const stripe = await stripeSdk();
      await stripe.subscriptions.update(subscription.provider_subscription_id, { cancel_at_period_end: cancel });
    }
    return repo.updateSubscription({ cancel_at_period_end: cancel });
  },

  async portalUrl({ subscription, origin }) {
    if (!subscription?.provider_customer_id) return null;
    const stripe = await stripeSdk();
    const portal = await stripe.billingPortal.sessions.create({
      customer: subscription.provider_customer_id,
      return_url: `${origin}/einstellungen/abrechnung`,
    });
    return portal.url;
  },
};

export function getBillingProvider(): BillingProvider {
  return billingProviderKind() === "stripe" ? stripeProvider : manualProvider;
}
