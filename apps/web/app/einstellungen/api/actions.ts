"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { requireRole } from "@/lib/session";
import { isForbiddenError } from "@/lib/auth/permissions";
import { field, type FormState } from "@/lib/auth/form";
import { generateApiKey, isScope } from "@/lib/api/auth";
import type { ApiScope } from "@/lib/repo/types-api";

/* Server Actions der Schlüsselverwaltung (api.manage). Der Klartext steht nur einmal in `secret` der Antwort. */

export interface ApiKeyFormState extends FormState {
  secret?: string;
  secretName?: string;
}

const EXPIRY_DAYS: Record<string, number | null> = { never: null, "30": 30, "90": 90, "365": 365 };

function denied(error: unknown): ApiKeyFormState | null {
  if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
  return null;
}

export async function createApiKeyAction(_prev: ApiKeyFormState, formData: FormData): Promise<ApiKeyFormState> {
  try {
    await requireRole("api.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const name = field(formData, "name", 80);
  const scopes = formData.getAll("scopes").filter(isScope) as ApiScope[];
  const expiry = field(formData, "expires", 8);
  const errors: Record<string, string> = {};
  if (name.length < 2) errors.name = "Bitte einen Namen mit mindestens zwei Zeichen angeben.";
  if (scopes.length === 0) errors.scopes = "Mindestens einen Scope wählen.";
  if (!(expiry in EXPIRY_DAYS)) errors.expires = "Bitte eine Gültigkeit wählen.";
  if (Object.keys(errors).length) return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };

  const days = EXPIRY_DAYS[expiry];
  const expiresAt = days ? new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString() : null;
  const generated = generateApiKey();
  const key = await getApiRepo().createApiKey({ name, scopes, expires_at: expiresAt, key_prefix: generated.key_prefix, key_hash: generated.key_hash });
  await getRepo().audit({
    action: "api_key.created",
    entity: "api_keys",
    entity_id: key.id,
    payload: { name, key_prefix: key.key_prefix, scopes, expires_at: expiresAt },
  });
  revalidatePath("/einstellungen/api");
  return { ok: true, message: `Schlüssel „${name}“ angelegt. Kopiere ihn jetzt, er wird nur einmal angezeigt.`, errors: {}, secret: generated.plaintext, secretName: name };
}

export async function revokeApiKeyAction(_prev: FormState, formData: FormData): Promise<FormState> {
  try {
    await requireRole("api.manage");
  } catch (error) {
    return denied(error) ?? Promise.reject(error);
  }
  const id = field(formData, "id", 40);
  const key = await getApiRepo().revokeApiKey(id);
  if (!key) return { ok: false, message: "Schlüssel nicht gefunden oder bereits widerrufen.", errors: {} };
  await getRepo().audit({ action: "api_key.revoked", entity: "api_keys", entity_id: key.id, payload: { name: key.name, key_prefix: key.key_prefix } });
  revalidatePath("/einstellungen/api");
  return { ok: true, message: `Schlüssel „${key.name}“ widerrufen.`, errors: {} };
}
