# Stripe einrichten

Der Code ist fertig: Checkout, Tarifwechsel mit anteiliger Verrechnung, Kündigung zum
Periodenende, Kundenportal und Webhook. Was fehlt, sind die Produkte in deinem Stripe-Konto und
sechs Umgebungsvariablen. Dieses Dokument führt da durch.

Solange etwas fehlt, läuft chopstr weiter über `manual`: Der Tarifwechsel schreibt direkt in die
Datenbank und die Rechnung kommt per E-Mail. Niemand steht im Regen, es wird nur nicht abgebucht.
Unter `Einstellungen > Abrechnung` steht dann, welche Variable genau fehlt.

---

## 1. Produkte und Preise anlegen

Vier Tarife, alle monatlich wiederkehrend, Währung Euro. Die Beträge stehen in der Tabelle
`plans` und müssen mit Stripe übereinstimmen, sonst zahlt der Kunde etwas anderes, als die App
anzeigt.

| Tarif | Produktname | Preis | Enthalten | Mehrverbrauch |
|---|---|---|---|---|
| `starter` | chopstr Starter | 29 € / Monat | 4 Stunden | 9 € / Stunde |
| `pro` | chopstr Pro | 79 € / Monat | 12 Stunden | 7,50 € / Stunde |
| `agency` | chopstr Agentur | 199 € / Monat | 40 Stunden | 6 € / Stunde |
| `sovereign` | chopstr Sovereign | 399 € / Monat | 40 Stunden | 6 € / Stunde |

In Stripe unter **Produktkatalog > Produkt hinzufügen**, je Tarif ein Produkt mit einem
wiederkehrenden Preis pro Monat. Nach dem Speichern die Preis-ID kopieren, sie beginnt mit
`price_`. Die Produkt-ID (`prod_`) braucht chopstr nicht.

**Der Mehrverbrauch wird nicht über Stripe abgerechnet.** chopstr zählt die Stunden selbst
(`usage_periods`) und zeigt sie unter Abrechnung an. Wer das automatisch abrechnen will, braucht
in Stripe zusätzlich einen verbrauchsabhängigen Preis; das ist bewusst nicht gebaut, weil die
Entscheidung über Rundung und Abrechnungszeitpunkt kaufmännisch ist, nicht technisch.

---

## 2. Webhook einrichten

In Stripe unter **Entwickler > Webhooks > Endpunkt hinzufügen**.

- Adresse: `https://DEINE-DOMAIN/api/billing/webhook`
- Diese fünf Ereignisse auswählen, mehr wertet chopstr nicht aus:

```
checkout.session.completed
customer.subscription.updated
customer.subscription.deleted
invoice.paid
invoice.payment_failed
```

Nach dem Anlegen das Signaturgeheimnis kopieren, es beginnt mit `whsec_`.

Die Signatur wird selbst geprüft (`lib/billing/stripe.ts`), mit einem Zeitfenster von fünf
Minuten gegen Wiedereinspielung. Ein falsch gesetztes Geheimnis fällt also sofort als 400 auf und
nicht erst in der Buchhaltung.

---

## 3. Umgebungsvariablen setzen

```bash
BILLING_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_live_...        # zum Testen sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_AGENCY=price_...
STRIPE_PRICE_SOVEREIGN=price_...
```

`BILLING_PROVIDER=stripe` allein reicht nicht: Ohne `STRIPE_SECRET_KEY` schaltet chopstr
absichtlich still auf `manual` zurück, damit ein Konfigurationsfehler keinen Kaufabbruch erzeugt.

---

## 4. Prüfen

Öffne `Einstellungen > Abrechnung`. Dort steht jetzt entweder nichts (alles eingerichtet, Live-
Schlüssel), ein Hinweis auf den Testmodus, oder eine Liste der fehlenden Variablen.

Mit Testschlüsseln einmal durchspielen:

1. Tarif anklicken, Stripe-Checkout öffnet sich
2. Testkarte `4242 4242 4242 4242`, beliebiges Ablaufdatum in der Zukunft, beliebige Prüfziffer
3. Nach dem Kauf landest du wieder unter Abrechnung mit `?checkout=erfolg`
4. Der Webhook setzt das Abo auf `active`, der Tarif steht in der Oberfläche

Webhooks lokal testen ohne öffentliche Adresse:

```bash
stripe login
stripe listen --forward-to localhost:3000/api/billing/webhook
```

`stripe listen` gibt ein eigenes `whsec_` aus, das nur für diese Sitzung gilt. Das gehört dann in
`STRIPE_WEBHOOK_SECRET`, nicht das aus dem Dashboard.

---

## Was der Code tut

| Datei | Aufgabe |
|---|---|
| `lib/billing/provider.ts` | Umschaltung `manual` oder `stripe`, Tarifwechsel, Kündigung, Portal |
| `lib/billing/stripe.ts` | Signaturprüfung, Preis zu Tarif, Ereignisse übersetzen, Konfigurationsprüfung |
| `app/api/billing/checkout/route.ts` | startet die Checkout-Sitzung |
| `app/api/billing/webhook/route.ts` | nimmt Stripe-Ereignisse an, idempotent |
| `app/api/billing/portal/route.ts` | leitet ins Kundenportal (Rechnungen, Zahlungsmittel) |
| `app/api/billing/plan/route.ts` | Tarifwechsel aus der Oberfläche |

**Tarifwechsel bei laufendem Abo** tauscht den Preis direkt im bestehenden Stripe-Abo und
verrechnet anteilig (`proration_behavior: create_prorations`). Es entsteht also keine zweite
Zahlung und kein zweites Abo.

**Kündigung** setzt `cancel_at_period_end`. Der Zugang bleibt bis zum Ende der bezahlten Periode,
danach fällt der Workspace auf den Starter-Tarif zurück.

---

## Offen, bewusst

- **Mehrverbrauch** wird gezählt und angezeigt, aber nicht automatisch abgerechnet (siehe oben).
- **Mollie** ist im Interface vorgesehen, aber nicht gebaut. Wer es braucht, implementiert
  `BillingProvider` ein zweites Mal; die Oberfläche muss dafür nicht angefasst werden.
- **Steuern**: `tax_id_collection` ist eingeschaltet, Stripe fragt also die UID ab. Ob Stripe Tax
  die Umsatzsteuer berechnen soll, ist eine steuerliche Entscheidung und im Dashboard zu treffen.
