import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { isDevelopment } from "@/lib/auth/cookies";

/* Upload-Token (PHASE4.md, Abschnitt 3): der tusd-Hook hat keine Sitzung. Der Browser holt vor dem Upload
 * POST /api/uploads/token und schickt das Token als tus-Metadatum `upload_token` mit.
 *   upload_token = base64url(JSON payload) + "." + base64url(HMAC-SHA256(payload, TUS_HOOK_SECRET))
 *   payload = { workspace_id, user_id, brand_profile_id, exp } (exp: Unix-Sekunden, 1 Stunde) */

export const UPLOAD_TOKEN_TTL_S = 60 * 60;

export interface UploadTokenPayload {
  workspace_id: string;
  user_id: string;
  brand_profile_id: string | null;
  exp: number;
}

export type UploadTokenCheck = { ok: true; payload: UploadTokenPayload } | { ok: false; error: string };

function secret(): string {
  const s = process.env.TUS_HOOK_SECRET;
  if (s) return s;
  if (isDevelopment()) {
    console.warn("[upload-token] TUS_HOOK_SECRET nicht gesetzt, Entwicklungs-Secret wird verwendet");
    return "dev-hook-secret";
  }
  throw new Error("TUS_HOOK_SECRET ist nicht gesetzt");
}

function sign(payloadB64: string): string {
  return createHmac("sha256", secret()).update(payloadB64).digest("base64url");
}

export function signUploadToken(payload: Omit<UploadTokenPayload, "exp"> & { exp?: number }): string {
  const full: UploadTokenPayload = {
    workspace_id: payload.workspace_id,
    user_id: payload.user_id,
    brand_profile_id: payload.brand_profile_id ?? null,
    exp: payload.exp ?? Math.floor(Date.now() / 1000) + UPLOAD_TOKEN_TTL_S,
  };
  const body = Buffer.from(JSON.stringify(full), "utf8").toString("base64url");
  return `${body}.${sign(body)}`;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function verifyUploadToken(token: string | undefined | null): UploadTokenCheck {
  if (!token || typeof token !== "string") return { ok: false, error: "Upload-Token fehlt." };
  const dot = token.indexOf(".");
  if (dot <= 0) return { ok: false, error: "Upload-Token ist ungültig." };
  const body = token.slice(0, dot);
  const given = token.slice(dot + 1);
  const expected = sign(body);
  const a = Buffer.from(given, "utf8");
  const b = Buffer.from(expected, "utf8");
  if (a.length !== b.length || !timingSafeEqual(a, b)) return { ok: false, error: "Upload-Token ist ungültig (Signatur)." };

  let payload: UploadTokenPayload;
  try {
    payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as UploadTokenPayload;
  } catch {
    return { ok: false, error: "Upload-Token ist ungültig (Inhalt)." };
  }
  if (!UUID_RE.test(payload.workspace_id ?? "") || !UUID_RE.test(payload.user_id ?? "")) {
    return { ok: false, error: "Upload-Token ist ungültig (IDs)." };
  }
  if (payload.brand_profile_id != null && !UUID_RE.test(payload.brand_profile_id)) {
    return { ok: false, error: "Upload-Token ist ungültig (Marke)." };
  }
  if (typeof payload.exp !== "number" || payload.exp * 1000 < Date.now()) {
    return { ok: false, error: "Upload-Token ist abgelaufen. Bitte den Upload neu starten." };
  }
  return { ok: true, payload: { ...payload, brand_profile_id: payload.brand_profile_id ?? null } };
}
