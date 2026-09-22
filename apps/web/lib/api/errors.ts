/* Fehlerform der öffentlichen API (PHASE5.md): { error: { code, message } }, Meldungen auf Deutsch. */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly headers: Record<string, string>;
  constructor(status: number, code: string, message: string, headers: Record<string, string> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.headers = headers;
  }
}

export function apiJson(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store", ...headers } });
}

export function apiErrorResponse(status: number, code: string, message: string, headers: Record<string, string> = {}): Response {
  return apiJson({ error: { code, message } }, status, headers);
}

export const badRequest = (message: string, code = "bad_request") => new ApiError(400, code, message);
export const unauthorized = (message = "API-Schlüssel fehlt oder ist ungültig.") => new ApiError(401, "unauthorized", message);
export const paymentRequired = (message: string, code = "quota_exceeded") => new ApiError(402, code, message);
export const forbidden = (message: string, code = "forbidden") => new ApiError(403, code, message);
export const notFound = (message: string) => new ApiError(404, "not_found", message);
export const conflict = (message: string, code = "conflict") => new ApiError(409, code, message);

/* Statuscode → Fehlercode für Antworten bestehender Routen, die nur { error: "…" } liefern */
export function codeForStatus(status: number): string {
  switch (status) {
    case 400:
      return "bad_request";
    case 401:
      return "unauthorized";
    case 402:
      return "quota_exceeded";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 410:
      return "gone";
    case 429:
      return "rate_limited";
    default:
      return status >= 500 ? "internal" : "error";
  }
}
