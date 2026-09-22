import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { appBaseUrl } from "@/lib/auth/url";
import { getBillingProvider } from "@/lib/billing/provider";

export const dynamic = "force-dynamic";

/* GET: Umleitung ins Stripe-Kundenportal (Rechnungen, Zahlungsmittel). Ohne Portal zurück zur Abrechnung. */
export async function GET() {
  const auth = await requireApiRole("billing.manage");
  if (auth instanceof Response) return auth;
  const origin = await appBaseUrl();
  const subscription = await getRepo().getSubscription();
  try {
    const url = await getBillingProvider().portalUrl({ subscription, origin });
    if (!url) return Response.redirect(`${origin}/einstellungen/abrechnung?portal=keins`, 303);
    return Response.redirect(url, 303);
  } catch (error) {
    console.warn("[billing] Portal-Link fehlgeschlagen:", error instanceof Error ? error.message : error);
    return Response.redirect(`${origin}/einstellungen/abrechnung?portal=fehler`, 303);
  }
}
