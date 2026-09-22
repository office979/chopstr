import "server-only";
import { createHash, randomBytes } from "node:crypto";
import type { Role } from "@/lib/auth/permissions";
import type { Session } from "@/lib/session";
import { getApiRepo } from "@/lib/repo/api";
import { API_SCOPES, type ApiKeyLookup, type ApiScope } from "@/lib/repo/types-api";
import { unauthorized } from "@/lib/api/errors";

/* API-Schlüssel (PHASE5.md, 5a): Klartext `chp_live_<32 Bytes base64url>`, in der Datenbank nur key_prefix
 * (erste 8 Zeichen nach chp_live_) und key_hash (SHA-256 des vollständigen Schlüssels). Auflösung zu
 * { workspaceId, scopes, role } mit Rolle nach Vertrag: read → reviewer, write und publish → editor, admin → admin.
 * Die Route läuft dann in withSessionContext(session) und nutzt dieselben Repository-Methoden wie die Web-App. */

export const KEY_PREFIX = "chp_live_";
export const KEY_PREFIX_VISIBLE = 8;

export interface GeneratedKey {
  plaintext: string;
  key_prefix: string;
  key_hash: string;
}

export function hashApiKey(plaintext: string): string {
  return createHash("sha256").update(plaintext, "utf8").digest("hex");
}

export function generateApiKey(): GeneratedKey {
  const plaintext = `${KEY_PREFIX}${randomBytes(32).toString("base64url")}`;
  return { plaintext, key_prefix: plaintext.slice(KEY_PREFIX.length, KEY_PREFIX.length + KEY_PREFIX_VISIBLE), key_hash: hashApiKey(plaintext) };
}

export function isScope(v: unknown): v is ApiScope {
  return typeof v === "string" && (API_SCOPES as readonly string[]).includes(v);
}

/* admin schließt write und read ein, write schließt read ein, publish schließt read ein */
export function hasScope(scopes: readonly string[], needed: ApiScope): boolean {
  if (scopes.includes(needed)) return true;
  if (needed === "read") return scopes.length > 0;
  if (needed === "write") return scopes.includes("admin");
  return false;
}

export function roleForScopes(scopes: readonly string[]): Role {
  if (scopes.includes("admin")) return "admin";
  if (scopes.includes("write") || scopes.includes("publish")) return "editor";
  return "reviewer";
}

export interface ApiAuth {
  key: ApiKeyLookup;
  workspaceId: string;
  scopes: ApiScope[];
  role: Role;
  session: Session;
}

const KEY_RE = /^chp_live_[A-Za-z0-9_-]{40,50}$/;

export function parseBearer(headers: Headers): string | null {
  const raw = headers.get("authorization");
  if (!raw) return null;
  const m = /^Bearer\s+(.+)$/i.exec(raw.trim());
  return m ? m[1].trim() : null;
}

/* last_used_at höchstens einmal pro Minute je Schlüssel schreiben */
declare global {
  var __chopstrApiKeyTouched: Map<string, number> | undefined;
}
const TOUCH_INTERVAL_MS = 60 * 1000;

async function touch(id: string): Promise<void> {
  if (!globalThis.__chopstrApiKeyTouched) globalThis.__chopstrApiKeyTouched = new Map();
  const map = globalThis.__chopstrApiKeyTouched;
  const last = map.get(id) ?? 0;
  const now = Date.now();
  if (now - last < TOUCH_INTERVAL_MS) return;
  map.set(id, now);
  try {
    await getApiRepo().touchApiKey(id);
  } catch (error) {
    console.warn("[api] last_used_at konnte nicht gesetzt werden:", error instanceof Error ? error.message : error);
  }
}

export function sessionForKey(key: ApiKeyLookup): Session {
  const role = roleForScopes(key.scopes);
  return {
    sessionId: null,
    /* Audit-Einträge laufen auf den Ersteller des Schlüssels; ohne Ersteller auf die Schlüssel-ID */
    userId: key.created_by ?? key.id,
    email: key.created_by_email ?? `api-key+${key.key_prefix}@chopstr.local`,
    displayName: key.created_by_name ? `${key.created_by_name} (API ${key.name})` : `API-Schlüssel ${key.name}`,
    emailVerified: true,
    locale: "de-AT",
    activeWorkspaceId: key.workspace_id,
    demo: false,
    workspaceId: key.workspace_id,
    workspaceName: key.workspace_name,
    role,
    brandScope: null,
  };
}

/* Löst den Bearer-Schlüssel auf; wirft ApiError 401 bei fehlendem, unbekanntem, abgelaufenem oder widerrufenem Schlüssel */
export async function resolveApiKey(headers: Headers): Promise<ApiAuth> {
  const token = parseBearer(headers);
  if (!token) throw unauthorized("API-Schlüssel fehlt. Bitte Authorization: Bearer chp_live_… senden.");
  if (!KEY_RE.test(token)) throw unauthorized("API-Schlüssel ungültig.");
  const key = await getApiRepo().findApiKeyByHash(hashApiKey(token));
  if (!key) throw unauthorized("API-Schlüssel ungültig.");
  if (key.revoked_at) throw unauthorized("API-Schlüssel wurde widerrufen.");
  if (key.expires_at && Date.parse(key.expires_at) <= Date.now()) throw unauthorized("API-Schlüssel ist abgelaufen.");
  const scopes = key.scopes.filter(isScope);
  void touch(key.id);
  return { key, workspaceId: key.workspace_id, scopes, role: roleForScopes(scopes), session: sessionForKey(key) };
}
