"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import { requireRole } from "@/lib/session";
import { isForbiddenError } from "@/lib/auth/permissions";
import { isEmail, normalizeEmail } from "@/lib/auth/tokens";
import { field, type FormState } from "@/lib/auth/form";
import type { BillingAddress } from "@/lib/repo/types";

const COUNTRIES = ["AT", "DE", "CH", "IT", "FR", "NL", "BE", "LU", "LI", "PL", "CZ", "SK", "HU", "SI", "HR", "DK", "SE", "FI", "NO", "IE", "ES", "PT"];
const VAT_RE = /^[A-Z]{2}[A-Z0-9]{2,12}$/;

/* Rechnungsadresse (Firma, Straße, PLZ, Ort, Land, UID) und Rechnungs-E-Mail → subscriptions.billing_address */
export async function updateBillingAddressAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requireRole("billing.manage");
  } catch (error) {
    if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
    throw error;
  }
  const address: BillingAddress = {
    company: field(formData, "company", 160),
    street: field(formData, "street", 160),
    zip: field(formData, "zip", 12),
    city: field(formData, "city", 80),
    country: field(formData, "country", 2).toUpperCase(),
    vat_id: field(formData, "vat_id", 20).toUpperCase().replace(/\s+/g, ""),
  };
  const email = normalizeEmail(formData.get("billing_email"));
  const errors: Record<string, string> = {};
  if (!address.company || address.company.length < 2) errors.company = "Bitte die Firma angeben.";
  if (!address.street) errors.street = "Bitte Straße und Hausnummer angeben.";
  if (!address.zip) errors.zip = "Bitte die PLZ angeben.";
  if (!address.city) errors.city = "Bitte den Ort angeben.";
  if (!COUNTRIES.includes(address.country ?? "")) errors.country = "Bitte ein EU- oder EWR-Land wählen.";
  if (address.vat_id && !VAT_RE.test(address.vat_id)) errors.vat_id = "UID im Format ATU12345678 oder DE123456789.";
  if (email && !isEmail(email)) errors.billing_email = "Bitte eine gültige E-Mail-Adresse angeben.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };
  if (!address.vat_id) delete address.vat_id;

  const repo = getRepo();
  const sub = await repo.updateSubscription({ billing_address: address, billing_email: email || null });
  await repo.audit({ action: "billing.address_updated", entity: "subscriptions", entity_id: sub.id, payload: { ...address, billing_email: email || null } });
  revalidatePath("/einstellungen/abrechnung");
  return { ok: true, message: "Rechnungsadresse gespeichert.", errors: {} };
}
