import type { StripeConfigStatus } from "@/lib/billing/stripe";

/* Zeigt, warum Stripe nicht greift. Ohne diesen Hinweis fällt eine vergessene Variable nicht auf:
 * BILLING_PROVIDER=stripe ohne Schlüssel schaltet still auf Rechnung per E-Mail zurück, und ein
 * fehlender Preis wirft erst, wenn jemand den Tarif anklickt.
 *
 * Nichts davon sieht ein zahlender Kunde: Wer hier landet, verwaltet den Workspace, und der Hinweis
 * erscheint nur, wenn wirklich etwas fehlt oder Testschlüssel laufen. Einrichtung: docs/STRIPE.md */
export function StripeSetupNotice({ status }: { status: StripeConfigStatus }) {
  if (!status.requested && !status.secretKey) return null;

  const missing: string[] = [];
  if (!status.secretKey) missing.push("STRIPE_SECRET_KEY");
  if (!status.webhookSecret) missing.push("STRIPE_WEBHOOK_SECRET");
  for (const code of status.missingPrices) missing.push(`STRIPE_PRICE_${code.toUpperCase()}`);

  if (status.ready && !status.testMode) return null;

  return (
    <div className="mb-5 rounded-inner border border-attention/40 px-4 py-3 text-sm">
      {missing.length > 0 ? (
        <>
          <p className="text-text">
            <span className="text-attention">Stripe ist nicht vollständig eingerichtet.</span> Solange etwas fehlt, läuft
            die Abrechnung über Rechnung per E-Mail.
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-text-2">
            {missing.map((key) => (
              <li key={key}>{key}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-text">
          <span className="text-attention">Stripe läuft im Testmodus.</span> Zahlungen sind nicht echt. Für den
          Echtbetrieb die Live-Schlüssel setzen.
        </p>
      )}
      <p className="mt-2 text-xs text-text-3">Einrichtung Schritt für Schritt: docs/STRIPE.md im Repo.</p>
    </div>
  );
}
