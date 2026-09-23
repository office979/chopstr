import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PLAN_CODES,
  STRIPE_EVENT_TYPES,
  STRIPE_TOLERANCE_S,
  isHandledStripeEvent,
  mapStripeEvent,
  planCodeForPrice,
  priceForPlan,
  stripeConfigStatus,
  stripeSignature,
  verifyStripeSignature,
} from "@/lib/billing/stripe";

const SECRET = "whsec_testgeheimnis";
const BODY = JSON.stringify({ id: "evt_1", type: "invoice.paid" });
const NOW = 1_735_689_600; // 2025-01-01T00:00:00Z

/* Baut einen echten Stripe-Signature-Header mit gültiger v1-Signatur */
function header(t: number, secret = SECRET, body = BODY): string {
  return `t=${t},v1=${stripeSignature(body, secret, t)}`;
}

describe("verifyStripeSignature", () => {
  it("akzeptiert eine gültige Signatur zum aktuellen Zeitstempel", () => {
    expect(verifyStripeSignature(BODY, header(NOW), SECRET, NOW)).toBe(true);
  });

  it("lehnt eine Signatur ab, die mit einem anderen Secret gebildet wurde", () => {
    const fremd = header(NOW, "whsec_falsch");
    expect(verifyStripeSignature(BODY, fremd, SECRET, NOW)).toBe(false);
  });

  it("lehnt ab, wenn der Body nachträglich verändert wurde", () => {
    const h = header(NOW);
    expect(verifyStripeSignature(`${BODY} `, h, SECRET, NOW)).toBe(false);
  });

  it("lehnt einen fehlenden oder leeren Header ab", () => {
    expect(verifyStripeSignature(BODY, null, SECRET, NOW)).toBe(false);
    expect(verifyStripeSignature(BODY, "", SECRET, NOW)).toBe(false);
  });

  it("akzeptiert genau an der Toleranzgrenze und lehnt eine Sekunde danach ab", () => {
    const alt = NOW - STRIPE_TOLERANCE_S;
    expect(verifyStripeSignature(BODY, header(alt), SECRET, NOW)).toBe(true);
    const zuAlt = NOW - STRIPE_TOLERANCE_S - 1;
    expect(verifyStripeSignature(BODY, header(zuAlt), SECRET, NOW)).toBe(false);
  });

  it("lehnt auch Zeitstempel aus der Zukunft außerhalb der Toleranz ab", () => {
    const zukunft = NOW + STRIPE_TOLERANCE_S;
    expect(verifyStripeSignature(BODY, header(zukunft), SECRET, NOW)).toBe(true);
    const zuWeit = NOW + STRIPE_TOLERANCE_S + 1;
    expect(verifyStripeSignature(BODY, header(zuWeit), SECRET, NOW)).toBe(false);
  });

  it("akzeptiert, wenn von mehreren v1-Signaturen eine stimmt (Secret-Rotation)", () => {
    const gut = stripeSignature(BODY, SECRET, NOW);
    const schlecht = stripeSignature(BODY, "whsec_altes_secret", NOW);
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=${schlecht},v1=${gut}`, SECRET, NOW)).toBe(true);
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=${gut},v1=${schlecht}`, SECRET, NOW)).toBe(true);
  });

  it("lehnt ab, wenn alle v1-Signaturen falsch sind", () => {
    const a = stripeSignature(BODY, "whsec_a", NOW);
    const b = stripeSignature(BODY, "whsec_b", NOW);
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=${a},v1=${b}`, SECRET, NOW)).toBe(false);
  });

  it("wirft nicht bei Signaturen mit falscher Länge, sondern lehnt ab", () => {
    // timingSafeEqual würde bei unterschiedlicher Länge werfen; der Längenvergleich davor verhindert das.
    expect(() => verifyStripeSignature(BODY, `t=${NOW},v1=abcd`, SECRET, NOW)).not.toThrow();
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=abcd`, SECRET, NOW)).toBe(false);
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=`, SECRET, NOW)).toBe(false);
    const zuLang = `${stripeSignature(BODY, SECRET, NOW)}00`;
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=${zuLang}`, SECRET, NOW)).toBe(false);
  });

  it("wirft nicht bei Nicht-Hex-Zeichen in der Signatur", () => {
    const nichtHex = "z".repeat(64);
    expect(() => verifyStripeSignature(BODY, `t=${NOW},v1=${nichtHex}`, SECRET, NOW)).not.toThrow();
    expect(verifyStripeSignature(BODY, `t=${NOW},v1=${nichtHex}`, SECRET, NOW)).toBe(false);
  });

  it("lehnt kaputte oder unvollständige Header ab", () => {
    expect(verifyStripeSignature(BODY, "unsinn", SECRET, NOW)).toBe(false);
    expect(verifyStripeSignature(BODY, `t=${NOW}`, SECRET, NOW)).toBe(false); // keine v1-Signatur
    expect(verifyStripeSignature(BODY, `v1=${stripeSignature(BODY, SECRET, NOW)}`, SECRET, NOW)).toBe(false); // kein t
    expect(verifyStripeSignature(BODY, `t=keinezahl,v1=${stripeSignature(BODY, SECRET, NOW)}`, SECRET, NOW)).toBe(false);
    expect(verifyStripeSignature(BODY, "t=,v1=", SECRET, NOW)).toBe(false);
    expect(verifyStripeSignature(BODY, ",,,", SECRET, NOW)).toBe(false);
  });

  it("verträgt Leerzeichen zwischen den Header-Teilen", () => {
    const sig = stripeSignature(BODY, SECRET, NOW);
    expect(verifyStripeSignature(BODY, `t=${NOW}, v1=${sig}`, SECRET, NOW)).toBe(true);
  });

  it("ignoriert unbekannte Schlüssel wie v0", () => {
    const sig = stripeSignature(BODY, SECRET, NOW);
    expect(verifyStripeSignature(BODY, `t=${NOW},v0=egal,v1=${sig}`, SECRET, NOW)).toBe(true);
  });
});

describe("isHandledStripeEvent", () => {
  it("erkennt die fünf behandelten Ereignistypen", () => {
    for (const typ of STRIPE_EVENT_TYPES) expect(isHandledStripeEvent(typ)).toBe(true);
  });

  it("lehnt andere Typen und Nicht-Strings ab", () => {
    expect(isHandledStripeEvent("customer.subscription.created")).toBe(false);
    expect(isHandledStripeEvent(null)).toBe(false);
    expect(isHandledStripeEvent(42)).toBe(false);
    expect(isHandledStripeEvent(undefined)).toBe(false);
  });
});

/* Die Preis-Zuordnung liest process.env, deshalb hier gestubbte Umgebungsvariablen.
 * vi.unstubAllEnvs im afterEach stellt den Ausgangszustand wieder her. */
describe("Umgebungsabhängige Helfer", () => {
  beforeEach(() => {
    for (const code of PLAN_CODES) vi.stubEnv(`STRIPE_PRICE_${code.toUpperCase()}`, undefined);
    vi.stubEnv("STRIPE_SECRET_KEY", undefined);
    vi.stubEnv("STRIPE_WEBHOOK_SECRET", undefined);
    vi.stubEnv("BILLING_PROVIDER", undefined);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  function allePreiseSetzen() {
    vi.stubEnv("STRIPE_PRICE_STARTER", "price_starter");
    vi.stubEnv("STRIPE_PRICE_PRO", "price_pro");
    vi.stubEnv("STRIPE_PRICE_AGENCY", "price_agency");
    vi.stubEnv("STRIPE_PRICE_SOVEREIGN", "price_sovereign");
  }

  describe("planCodeForPrice", () => {
    it("findet den Tarif zur hinterlegten Preis-ID", () => {
      allePreiseSetzen();
      expect(planCodeForPrice("price_starter")).toBe("starter");
      expect(planCodeForPrice("price_pro")).toBe("pro");
      expect(planCodeForPrice("price_agency")).toBe("agency");
      expect(planCodeForPrice("price_sovereign")).toBe("sovereign");
    });

    it("liefert null für unbekannte, leere oder fehlende Preis-IDs", () => {
      allePreiseSetzen();
      expect(planCodeForPrice("price_unbekannt")).toBeNull();
      expect(planCodeForPrice(null)).toBeNull();
      expect(planCodeForPrice(undefined)).toBeNull();
      expect(planCodeForPrice("")).toBeNull();
    });

    it("liefert null, wenn gar keine Preise konfiguriert sind", () => {
      expect(planCodeForPrice("price_pro")).toBeNull();
    });
  });

  describe("priceForPlan", () => {
    it("liest STRIPE_PRICE_<PLAN> in Großbuchstaben", () => {
      vi.stubEnv("STRIPE_PRICE_PRO", "price_pro");
      expect(priceForPlan("pro")).toBe("price_pro");
    });

    it("liefert null für nicht konfigurierte oder leere Werte", () => {
      vi.stubEnv("STRIPE_PRICE_AGENCY", "");
      expect(priceForPlan("agency")).toBeNull();
      expect(priceForPlan("pro")).toBeNull();
      expect(priceForPlan("gibtsnicht")).toBeNull();
    });
  });

  describe("stripeConfigStatus", () => {
    it("meldet ready, wenn Provider, Schlüssel und alle Preise gesetzt sind", () => {
      vi.stubEnv("BILLING_PROVIDER", "stripe");
      vi.stubEnv("STRIPE_SECRET_KEY", "sk_live_abc");
      vi.stubEnv("STRIPE_WEBHOOK_SECRET", SECRET);
      allePreiseSetzen();
      expect(stripeConfigStatus()).toEqual({
        requested: true,
        secretKey: true,
        webhookSecret: true,
        missingPrices: [],
        testMode: false,
        ready: true,
      });
    });

    it("erkennt BILLING_PROVIDER unabhängig von Groß-/Kleinschreibung", () => {
      vi.stubEnv("BILLING_PROVIDER", "Stripe");
      expect(stripeConfigStatus().requested).toBe(true);
    });

    it("ist nicht ready, wenn BILLING_PROVIDER=stripe ohne Secret-Key gesetzt ist", () => {
      vi.stubEnv("BILLING_PROVIDER", "stripe");
      vi.stubEnv("STRIPE_WEBHOOK_SECRET", SECRET);
      allePreiseSetzen();
      const status = stripeConfigStatus();
      expect(status.requested).toBe(true);
      expect(status.secretKey).toBe(false);
      expect(status.ready).toBe(false);
    });

    it("ist nicht ready ohne Webhook-Secret", () => {
      vi.stubEnv("BILLING_PROVIDER", "stripe");
      vi.stubEnv("STRIPE_SECRET_KEY", "sk_live_abc");
      allePreiseSetzen();
      const status = stripeConfigStatus();
      expect(status.webhookSecret).toBe(false);
      expect(status.ready).toBe(false);
    });

    it("listet fehlende Tarifpreise in missingPrices auf", () => {
      vi.stubEnv("BILLING_PROVIDER", "stripe");
      vi.stubEnv("STRIPE_SECRET_KEY", "sk_live_abc");
      vi.stubEnv("STRIPE_WEBHOOK_SECRET", SECRET);
      vi.stubEnv("STRIPE_PRICE_STARTER", "price_starter");
      vi.stubEnv("STRIPE_PRICE_PRO", "price_pro");
      const status = stripeConfigStatus();
      expect(status.missingPrices).toEqual(["agency", "sovereign"]);
      expect(status.ready).toBe(false);
    });

    it("erkennt Testschlüssel an sk_test_", () => {
      vi.stubEnv("BILLING_PROVIDER", "stripe");
      vi.stubEnv("STRIPE_SECRET_KEY", "sk_test_abc");
      vi.stubEnv("STRIPE_WEBHOOK_SECRET", SECRET);
      allePreiseSetzen();
      const status = stripeConfigStatus();
      expect(status.testMode).toBe(true);
      expect(status.ready).toBe(true);
    });

    it("meldet bei komplett leerer Umgebung requested=false und alle Preise fehlend", () => {
      expect(stripeConfigStatus()).toEqual({
        requested: false,
        secretKey: false,
        webhookSecret: false,
        missingPrices: ["starter", "pro", "agency", "sovereign"],
        testMode: false,
        ready: false,
      });
    });

    it("ist nicht ready, wenn ein anderer Provider konfiguriert ist", () => {
      vi.stubEnv("BILLING_PROVIDER", "manual");
      vi.stubEnv("STRIPE_SECRET_KEY", "sk_live_abc");
      vi.stubEnv("STRIPE_WEBHOOK_SECRET", SECRET);
      allePreiseSetzen();
      expect(stripeConfigStatus().ready).toBe(false);
    });
  });

  /* Der Tarif eines Abos wird über die Preis-ID aufgelöst, deshalb steht dieser Block
   * ebenfalls im Bereich mit gestubbter Umgebung. */
  describe("mapStripeEvent: customer.subscription.updated", () => {
    function abo(overrides: Record<string, unknown> = {}): { object: Record<string, unknown> } {
      return {
        object: {
          id: "sub_1Abc",
          object: "subscription",
          customer: "cus_1Abc",
          status: "active",
          cancel_at_period_end: false,
          metadata: {},
          items: {
            object: "list",
            data: [
              {
                id: "si_1Abc",
                object: "subscription_item",
                price: { id: "price_pro", object: "price", metadata: {} },
                current_period_start: 1_735_689_600,
                current_period_end: 1_738_368_000,
              },
            ],
          },
          ...overrides,
        },
      };
    }

    it("liest Abo-ID, Kunde, Zeitraum und Tarif über die Preis-ID", () => {
      allePreiseSetzen();
      const m = mapStripeEvent("customer.subscription.updated", abo());
      expect(m.subscription_id).toBe("sub_1Abc");
      expect(m.customer_id).toBe("cus_1Abc");
      expect(m.workspace_id).toBeNull();
      expect(m.patch).toMatchObject({
        provider: "stripe",
        provider_subscription_id: "sub_1Abc",
        provider_customer_id: "cus_1Abc",
        status: "active",
        cancel_at_period_end: false,
        plan_code: "pro",
        current_period_start: "2025-01-01T00:00:00.000Z",
        current_period_end: "2025-02-01T00:00:00.000Z",
      });
    });

    it("bevorzugt den Zeitraum auf Abo-Ebene vor dem der Position", () => {
      allePreiseSetzen();
      const m = mapStripeEvent(
        "customer.subscription.updated",
        abo({ current_period_start: 1_704_067_200, current_period_end: 1_706_745_600 }),
      );
      expect(m.patch.current_period_start).toBe("2024-01-01T00:00:00.000Z");
      expect(m.patch.current_period_end).toBe("2024-02-01T00:00:00.000Z");
    });

    it("bildet die Stripe-Status auf die internen Status ab", () => {
      allePreiseSetzen();
      const erwartet: Record<string, string> = {
        trialing: "trialing",
        active: "active",
        past_due: "past_due",
        unpaid: "past_due",
        incomplete: "past_due",
        canceled: "canceled",
        incomplete_expired: "canceled",
        paused: "paused",
      };
      for (const [stripeStatus, intern] of Object.entries(erwartet)) {
        const m = mapStripeEvent("customer.subscription.updated", abo({ status: stripeStatus }));
        expect(m.patch.status, `Status ${stripeStatus}`).toBe(intern);
      }
    });

    it("lässt den Status unangetastet, wenn Stripe einen unbekannten Wert schickt", () => {
      allePreiseSetzen();
      const m = mapStripeEvent("customer.subscription.updated", abo({ status: "irgendwas_neues" }));
      expect(m.patch.status).toBeUndefined();
      expect("status" in m.patch).toBe(false);
    });

    it("übernimmt cancel_at_period_end als echten Boolean", () => {
      allePreiseSetzen();
      expect(mapStripeEvent("customer.subscription.updated", abo({ cancel_at_period_end: true })).patch.cancel_at_period_end).toBe(true);
      expect(mapStripeEvent("customer.subscription.updated", abo({ cancel_at_period_end: null })).patch.cancel_at_period_end).toBe(false);
    });

    it("nimmt den Tarif aus price.metadata.plan_code, wenn die Preis-ID unbekannt ist", () => {
      const daten = abo();
      const items = daten.object.items as { data: Record<string, unknown>[] };
      items.data[0].price = { id: "price_unbekannt", metadata: { plan_code: "agency" } };
      expect(mapStripeEvent("customer.subscription.updated", daten).patch.plan_code).toBe("agency");
    });

    it("fällt zuletzt auf metadata.plan_code des Abos zurück", () => {
      const daten = abo({ metadata: { plan_code: "sovereign" } });
      const items = daten.object.items as { data: Record<string, unknown>[] };
      items.data[0].price = { id: "price_unbekannt", metadata: {} };
      expect(mapStripeEvent("customer.subscription.updated", daten).patch.plan_code).toBe("sovereign");
    });

    it("ignoriert unbekannte Tarif-Codes", () => {
      const daten = abo({ metadata: { plan_code: "enterprise" } });
      const items = daten.object.items as { data: Record<string, unknown>[] };
      items.data[0].price = { id: "price_unbekannt", metadata: {} };
      expect(mapStripeEvent("customer.subscription.updated", daten).patch.plan_code).toBeUndefined();
    });

    it("löst einen expandierten Kunden auf seine ID auf (refId)", () => {
      allePreiseSetzen();
      const m = mapStripeEvent(
        "customer.subscription.updated",
        abo({ customer: { id: "cus_expandiert", object: "customer", email: "kunde@example.de" } }),
      );
      expect(m.customer_id).toBe("cus_expandiert");
      expect(m.patch.provider_customer_id).toBe("cus_expandiert");
    });

    it("setzt trial_ends_at nur, wenn trial_end im Ereignis vorkommt", () => {
      allePreiseSetzen();
      const ohne = mapStripeEvent("customer.subscription.updated", abo());
      expect("trial_ends_at" in ohne.patch).toBe(false);

      const mit = mapStripeEvent("customer.subscription.updated", abo({ trial_end: 1_738_368_000 }));
      expect(mit.patch.trial_ends_at).toBe("2025-02-01T00:00:00.000Z");

      const beendet = mapStripeEvent("customer.subscription.updated", abo({ trial_end: null }));
      expect("trial_ends_at" in beendet.patch).toBe(true);
      expect(beendet.patch.trial_ends_at).toBeNull();
    });

    it("liest workspace_id aus den Abo-Metadaten, wenn vorhanden", () => {
      allePreiseSetzen();
      const m = mapStripeEvent("customer.subscription.updated", abo({ metadata: { workspace_id: "ws_42" } }));
      expect(m.workspace_id).toBe("ws_42");
    });

    it("setzt den Zeitraum auf null, wenn Stripe gar keine Periode mitschickt", () => {
      // Dokumentiert das tatsächliche Verhalten: fehlende Felder werden als null in den Patch geschrieben.
      allePreiseSetzen();
      const daten = abo();
      const items = daten.object.items as { data: Record<string, unknown>[] };
      items.data = [{ id: "si_1Abc", price: { id: "price_pro", metadata: {} } }];
      const m = mapStripeEvent("customer.subscription.updated", daten);
      expect(m.patch.current_period_start).toBeNull();
      expect(m.patch.current_period_end).toBeNull();
    });
  });
});

describe("mapStripeEvent: checkout.session.completed", () => {
  const sitzung = {
    object: {
      id: "cs_test_a1",
      object: "checkout.session",
      client_reference_id: "ws_aus_reference",
      customer: "cus_1Abc",
      customer_email: null,
      customer_details: { email: "rechnung@example.de", name: "Beispiel GmbH" },
      metadata: { workspace_id: "ws_aus_metadata", plan_code: "pro" },
      mode: "subscription",
      payment_status: "paid",
      status: "complete",
      subscription: "sub_1Abc",
    },
  };

  it("übernimmt Workspace, Kunde, Abo, Tarif und Rechnungs-E-Mail", () => {
    const m = mapStripeEvent("checkout.session.completed", sitzung);
    expect(m.workspace_id).toBe("ws_aus_metadata");
    expect(m.customer_id).toBe("cus_1Abc");
    expect(m.subscription_id).toBe("sub_1Abc");
    expect(m.patch).toEqual({
      provider: "stripe",
      plan_code: "pro",
      provider_customer_id: "cus_1Abc",
      provider_subscription_id: "sub_1Abc",
      status: "active",
      cancel_at_period_end: false,
      billing_email: "rechnung@example.de",
    });
  });

  it("nutzt client_reference_id als Rückfallebene für die workspace_id", () => {
    const ohneMetadata = { object: { ...sitzung.object, metadata: { plan_code: "pro" } } };
    expect(mapStripeEvent("checkout.session.completed", ohneMetadata).workspace_id).toBe("ws_aus_reference");
  });

  it("liefert workspace_id null, wenn weder Metadaten noch client_reference_id gesetzt sind", () => {
    const leer = { object: { ...sitzung.object, metadata: {}, client_reference_id: null } };
    const m = mapStripeEvent("checkout.session.completed", leer);
    expect(m.workspace_id).toBeNull();
    expect(m.patch.plan_code).toBeUndefined();
  });

  it("fällt bei der E-Mail auf customer_email zurück", () => {
    const ohneDetails = { object: { ...sitzung.object, customer_details: {}, customer_email: "fallback@example.de" } };
    expect(mapStripeEvent("checkout.session.completed", ohneDetails).patch.billing_email).toBe("fallback@example.de");
  });

  it("lässt billing_email weg, wenn Stripe keine E-Mail mitschickt", () => {
    const ohneMail = { object: { ...sitzung.object, customer_details: {}, customer_email: null } };
    expect("billing_email" in mapStripeEvent("checkout.session.completed", ohneMail).patch).toBe(false);
  });

  it("löst expandierte customer- und subscription-Objekte auf ihre IDs auf", () => {
    const expandiert = {
      object: {
        ...sitzung.object,
        customer: { id: "cus_expandiert", object: "customer" },
        subscription: { id: "sub_expandiert", object: "subscription", status: "active" },
      },
    };
    const m = mapStripeEvent("checkout.session.completed", expandiert);
    expect(m.customer_id).toBe("cus_expandiert");
    expect(m.subscription_id).toBe("sub_expandiert");
    expect(m.patch.provider_customer_id).toBe("cus_expandiert");
    expect(m.patch.provider_subscription_id).toBe("sub_expandiert");
  });

  it("verträgt eine Sitzung ohne Abo (Einmalzahlung) ohne zu werfen", () => {
    const ohneAbo = { object: { ...sitzung.object, subscription: null, mode: "payment" } };
    const m = mapStripeEvent("checkout.session.completed", ohneAbo);
    expect(m.subscription_id).toBeNull();
    expect(m.patch.status).toBe("active");
  });

  it("verträgt völlig leere Ereignisdaten", () => {
    const m = mapStripeEvent("checkout.session.completed", undefined);
    expect(m).toEqual({
      workspace_id: null,
      customer_id: null,
      subscription_id: null,
      patch: {
        provider: "stripe",
        provider_customer_id: null,
        provider_subscription_id: null,
        status: "active",
        cancel_at_period_end: false,
      },
    });
  });
});

describe("mapStripeEvent: customer.subscription.deleted", () => {
  const geloescht = {
    object: {
      id: "sub_1Abc",
      object: "subscription",
      customer: "cus_1Abc",
      status: "canceled",
      canceled_at: 1_738_368_000,
      cancel_at_period_end: false,
      metadata: { workspace_id: "ws_42" },
      items: { object: "list", data: [{ id: "si_1Abc", price: { id: "price_unbekannt", metadata: {} } }] },
    },
  };

  it("setzt den Status auf canceled", () => {
    const m = mapStripeEvent("customer.subscription.deleted", geloescht);
    expect(m.patch.status).toBe("canceled");
    expect(m.subscription_id).toBe("sub_1Abc");
    expect(m.customer_id).toBe("cus_1Abc");
    expect(m.workspace_id).toBe("ws_42");
    expect(m.patch.provider).toBe("stripe");
  });

  it("setzt canceled auch dann, wenn Stripe im Objekt noch active meldet", () => {
    const widerspruch = { object: { ...geloescht.object, status: "active" } };
    expect(mapStripeEvent("customer.subscription.deleted", widerspruch).patch.status).toBe("canceled");
  });
});

describe("mapStripeEvent: invoice.paid", () => {
  const rechnung = {
    object: {
      id: "in_1Abc",
      object: "invoice",
      customer: "cus_1Abc",
      customer_email: "rechnung@example.de",
      status: "paid",
      subscription: "sub_1Abc",
      lines: {
        object: "list",
        data: [{ id: "il_1Abc", object: "line_item", period: { start: 1_735_689_600, end: 1_738_368_000 } }],
      },
    },
  };

  it("setzt active und übernimmt Abrechnungszeitraum sowie E-Mail", () => {
    const m = mapStripeEvent("invoice.paid", rechnung);
    expect(m.subscription_id).toBe("sub_1Abc");
    expect(m.customer_id).toBe("cus_1Abc");
    expect(m.patch).toEqual({
      provider: "stripe",
      status: "active",
      current_period_start: "2025-01-01T00:00:00.000Z",
      current_period_end: "2025-02-01T00:00:00.000Z",
      billing_email: "rechnung@example.de",
    });
  });

  it("findet die Abo-ID auch in der neueren Struktur parent.subscription_details", () => {
    const neu = {
      object: {
        ...rechnung.object,
        subscription: undefined,
        parent: { type: "subscription_details", subscription_details: { subscription: "sub_aus_parent" } },
      },
    };
    expect(mapStripeEvent("invoice.paid", neu).subscription_id).toBe("sub_aus_parent");
  });

  it("löst ein expandiertes subscription-Objekt auf", () => {
    const expandiert = { object: { ...rechnung.object, subscription: { id: "sub_expandiert", object: "subscription" } } };
    expect(mapStripeEvent("invoice.paid", expandiert).subscription_id).toBe("sub_expandiert");
  });

  it("lässt den Zeitraum weg, wenn die Rechnung keine Positionen hat", () => {
    const ohneZeilen = { object: { ...rechnung.object, lines: { object: "list", data: [] }, customer_email: null } };
    expect(mapStripeEvent("invoice.paid", ohneZeilen).patch).toEqual({ provider: "stripe", status: "active" });
  });
});

describe("mapStripeEvent: invoice.payment_failed", () => {
  it("setzt den Status auf past_due", () => {
    const m = mapStripeEvent("invoice.payment_failed", {
      object: {
        id: "in_1Abc",
        object: "invoice",
        customer: "cus_1Abc",
        status: "open",
        attempt_count: 2,
        subscription: "sub_1Abc",
      },
    });
    expect(m.patch).toEqual({ provider: "stripe", status: "past_due" });
    expect(m.subscription_id).toBe("sub_1Abc");
    expect(m.customer_id).toBe("cus_1Abc");
  });

  it("findet die Abo-ID auch über parent.subscription_details", () => {
    const m = mapStripeEvent("invoice.payment_failed", {
      object: {
        id: "in_1Abc",
        object: "invoice",
        customer: { id: "cus_expandiert", object: "customer" },
        parent: { subscription_details: { subscription: { id: "sub_aus_parent", object: "subscription" } } },
      },
    });
    expect(m.subscription_id).toBe("sub_aus_parent");
    expect(m.customer_id).toBe("cus_expandiert");
  });
});
