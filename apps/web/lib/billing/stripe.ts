import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import type { SubscriptionPatch, SubscriptionStatus } from "@/lib/repo/types";

/* Stripe-Hilfen ohne SDK-Zwang: Signaturprüfung (Header `Stripe-Signature: t=…,v1=…`, HMAC-SHA256 über
 * `${t}.${body}`) und die Abbildung von Webhook-Ereignissen auf `subscriptions`-Änderungen. Das SDK selbst
 * (Paket `stripe`) wird nur für Checkout und Customer-Portal geladen (lib/billing/provider.ts). */

export const STRIPE_TOLERANCE_S = 300;

export function stripeSignature(body: string, secret: string, timestamp: number): string {
  return createHmac("sha256", secret).update(`${timestamp}.${body}`).digest("hex");
}

/* true, wenn eine v1-Signatur passt und der Zeitstempel innerhalb der Toleranz liegt */
export function verifyStripeSignature(body: string, header: string | null, secret: string, nowS = Math.floor(Date.now() / 1000)): boolean {
  if (!header) return false;
  const parts = header.split(",").map((p) => p.trim().split("="));
  const t = Number(parts.find(([k]) => k === "t")?.[1]);
  const signatures = parts.filter(([k]) => k === "v1").map(([, v]) => v ?? "");
  if (!Number.isFinite(t) || signatures.length === 0) return false;
  if (Math.abs(nowS - t) > STRIPE_TOLERANCE_S) return false;
  const expected = Buffer.from(stripeSignature(body, secret, t), "hex");
  return signatures.some((sig) => {
    const given = Buffer.from(sig, "hex");
    return given.length === expected.length && timingSafeEqual(given, expected);
  });
}

export const STRIPE_EVENT_TYPES = [
  "checkout.session.completed",
  "customer.subscription.updated",
  "customer.subscription.deleted",
  "invoice.paid",
  "invoice.payment_failed",
] as const;
export type StripeEventType = (typeof STRIPE_EVENT_TYPES)[number];

export function isHandledStripeEvent(type: unknown): type is StripeEventType {
  return typeof type === "string" && (STRIPE_EVENT_TYPES as readonly string[]).includes(type);
}

export const PLAN_CODES = ["starter", "pro", "agency", "sovereign"] as const;

/* STRIPE_PRICE_<PLAN> → Plan-Code */
export function planCodeForPrice(priceId: string | null | undefined): string | null {
  if (!priceId) return null;
  for (const code of PLAN_CODES) {
    if (process.env[`STRIPE_PRICE_${code.toUpperCase()}`] === priceId) return code;
  }
  return null;
}

export function priceForPlan(code: string): string | null {
  return process.env[`STRIPE_PRICE_${code.toUpperCase()}`] || null;
}

export interface StripeConfigStatus {
  /* BILLING_PROVIDER=stripe gesetzt, egal ob die Schlüssel stimmen */
  requested: boolean;
  secretKey: boolean;
  webhookSecret: boolean;
  /* Tarife ohne hinterlegten Preis: Checkout schlägt für sie fehl */
  missingPrices: string[];
  /* Testschlüssel erkannt (sk_test_): Zahlungen sind nicht echt */
  testMode: boolean;
  ready: boolean;
}

/* Was fehlt, damit Stripe wirklich funktioniert. Ohne diese Prüfung merkt man eine vergessene
 * Variable erst, wenn ein zahlender Kunde im Checkout hängt: BILLING_PROVIDER ohne Schlüssel fällt
 * still auf "manual" zurück, und ein fehlender Preis wirft erst beim Klick auf den Tarif. */
export function stripeConfigStatus(): StripeConfigStatus {
  const secret = process.env.STRIPE_SECRET_KEY ?? "";
  const requested = (process.env.BILLING_PROVIDER ?? "").toLowerCase() === "stripe";
  const missingPrices = PLAN_CODES.filter((code) => !priceForPlan(code));
  return {
    requested,
    secretKey: Boolean(secret),
    webhookSecret: Boolean(process.env.STRIPE_WEBHOOK_SECRET),
    missingPrices: [...missingPrices],
    testMode: secret.startsWith("sk_test_"),
    ready: requested && Boolean(secret) && Boolean(process.env.STRIPE_WEBHOOK_SECRET) && missingPrices.length === 0,
  };
}

type Obj = Record<string, unknown>;

function obj(v: unknown): Obj {
  return typeof v === "object" && v !== null ? (v as Obj) : {};
}

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

function unixIso(v: unknown): string | null {
  return typeof v === "number" && Number.isFinite(v) ? new Date(v * 1000).toISOString() : null;
}

/* ID aus einem Feld, das entweder ein String oder ein expandiertes Objekt mit id ist */
function refId(v: unknown): string | null {
  return str(v) ?? str(obj(v).id);
}

function mapStatus(v: unknown): SubscriptionStatus | undefined {
  switch (v) {
    case "trialing":
      return "trialing";
    case "active":
      return "active";
    case "past_due":
    case "unpaid":
    case "incomplete":
      return "past_due";
    case "canceled":
    case "incomplete_expired":
      return "canceled";
    case "paused":
      return "paused";
    default:
      return undefined;
  }
}

export interface StripeEventMapping {
  /* Workspace aus metadata/client_reference_id, sonst über Kunden- oder Abo-ID nachschlagen */
  workspace_id: string | null;
  customer_id: string | null;
  subscription_id: string | null;
  patch: SubscriptionPatch;
}

/* Abbildung eines Stripe-Ereignisses auf eine subscriptions-Änderung */
export function mapStripeEvent(type: StripeEventType, data: unknown): StripeEventMapping {
  const o = obj(obj(data).object);
  const metadata = obj(o.metadata);
  const patch: SubscriptionPatch = { provider: "stripe" };
  let workspaceId = str(metadata.workspace_id);
  let customerId = refId(o.customer);
  let subscriptionId: string | null = null;

  switch (type) {
    case "checkout.session.completed": {
      workspaceId = workspaceId ?? str(o.client_reference_id);
      subscriptionId = refId(o.subscription);
      const plan = str(metadata.plan_code);
      if (plan && (PLAN_CODES as readonly string[]).includes(plan)) patch.plan_code = plan;
      patch.provider_customer_id = customerId;
      patch.provider_subscription_id = subscriptionId;
      patch.status = "active";
      patch.cancel_at_period_end = false;
      const email = str(obj(o.customer_details).email) ?? str(o.customer_email);
      if (email) patch.billing_email = email;
      break;
    }
    case "customer.subscription.updated":
    case "customer.subscription.deleted": {
      subscriptionId = str(o.id);
      patch.provider_subscription_id = subscriptionId;
      patch.provider_customer_id = customerId;
      const status = type === "customer.subscription.deleted" ? "canceled" : mapStatus(o.status);
      if (status) patch.status = status;
      patch.cancel_at_period_end = Boolean(o.cancel_at_period_end);
      const items = obj(o.items).data;
      const first = Array.isArray(items) ? obj(items[0]) : {};
      const price = obj(first.price);
      const plan = planCodeForPrice(str(price.id)) ?? str(obj(price.metadata).plan_code) ?? str(metadata.plan_code);
      if (plan && (PLAN_CODES as readonly string[]).includes(plan)) patch.plan_code = plan;
      patch.current_period_start = unixIso(o.current_period_start) ?? unixIso(first.current_period_start);
      patch.current_period_end = unixIso(o.current_period_end) ?? unixIso(first.current_period_end);
      if (o.trial_end !== undefined) patch.trial_ends_at = unixIso(o.trial_end);
      break;
    }
    case "invoice.paid": {
      subscriptionId = refId(o.subscription) ?? refId(obj(obj(o.parent).subscription_details).subscription);
      patch.status = "active";
      const lines = obj(o.lines).data;
      const line = Array.isArray(lines) ? obj(lines[0]) : {};
      const period = obj(line.period);
      const start = unixIso(period.start);
      const end = unixIso(period.end);
      if (start) patch.current_period_start = start;
      if (end) patch.current_period_end = end;
      const email = str(o.customer_email);
      if (email) patch.billing_email = email;
      break;
    }
    case "invoice.payment_failed": {
      subscriptionId = refId(o.subscription) ?? refId(obj(obj(o.parent).subscription_details).subscription);
      patch.status = "past_due";
      break;
    }
  }
  customerId = customerId ?? null;
  return { workspace_id: workspaceId, customer_id: customerId, subscription_id: subscriptionId, patch };
}
