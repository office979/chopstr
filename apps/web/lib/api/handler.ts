import "server-only";
import type { NextRequest } from "next/server";
import { withSessionContext } from "@/lib/session";
import { ApiError, apiErrorResponse } from "@/lib/api/errors";
import { hasScope, resolveApiKey, type ApiAuth } from "@/lib/api/auth";
import { consumeRateLimit, rateLimitHeaders } from "@/lib/api/rate-limit";
import type { ApiScope } from "@/lib/repo/types-api";

/* Rahmen für jede v1-Route: Bearer-Auth → Rate-Limit (600/min je Schlüssel) → Scope-Prüfung → Handler im
 * Sitzungskontext des Schlüssels. ApiError wird zur Fehlerantwort, alles andere zu 500 mit deutscher Meldung.
 *
 *   export const GET = apiRoute("read", async (request, { auth, params }) => apiJson({ ... }));
 */

export interface ApiContext<P> {
  auth: ApiAuth;
  params: P;
}

type Handler<P> = (request: NextRequest, ctx: ApiContext<P>) => Promise<Response>;

const SCOPE_LABEL: Record<ApiScope, string> = { read: "read", write: "write", publish: "publish", admin: "admin" };

function withHeaders(res: Response, headers: Record<string, string>): Response {
  const out = new Response(res.body, { status: res.status, statusText: res.statusText, headers: new Headers(res.headers) });
  for (const [k, v] of Object.entries(headers)) out.headers.set(k, v);
  return out;
}

export function apiRoute<P = Record<string, never>>(scope: ApiScope, handler: Handler<P>) {
  return async (request: NextRequest, ctx?: { params?: Promise<P> }): Promise<Response> => {
    let auth: ApiAuth;
    try {
      auth = await resolveApiKey(request.headers);
    } catch (error) {
      if (error instanceof ApiError) return apiErrorResponse(error.status, error.code, error.message, error.headers);
      console.error("[api] Auth fehlgeschlagen:", error);
      return apiErrorResponse(500, "internal", "Interner Fehler bei der Authentifizierung.");
    }
    const limit = consumeRateLimit(auth.key.id);
    const limitHeaders = rateLimitHeaders(limit);
    if (!limit.allowed) {
      return apiErrorResponse(429, "rate_limited", `Zu viele Anfragen: höchstens ${limit.limit} pro Minute je Schlüssel. Bitte in ${limit.retryAfterS} s erneut versuchen.`, limitHeaders);
    }
    if (!hasScope(auth.scopes, scope)) {
      return apiErrorResponse(403, "scope_missing", `Scope ${SCOPE_LABEL[scope]} fehlt. Der Schlüssel hat: ${auth.scopes.join(", ") || "keine Scopes"}.`, limitHeaders);
    }
    try {
      const params = (await ctx?.params) ?? ({} as P);
      const res = await withSessionContext(auth.session, () => handler(request, { auth, params }));
      return withHeaders(res, limitHeaders);
    } catch (error) {
      if (error instanceof ApiError) return apiErrorResponse(error.status, error.code, error.message, { ...limitHeaders, ...error.headers });
      console.error("[api] Unbehandelter Fehler:", error);
      return apiErrorResponse(500, "internal", "Interner Fehler. Bitte später erneut versuchen.", limitHeaders);
    }
  };
}
