import "server-only";
import { timingSafeEqual } from "node:crypto";
import { isDevelopment } from "@/lib/auth/cookies";
import { apiErrorResponse } from "@/lib/api/errors";

/* Interne Endpunkte Worker ↔ Web (PHASE5.md): Header X-Internal-Secret = INTERNAL_API_SECRET.
 * Ohne gesetztes Secret sind die Endpunkte nur in der Entwicklung erreichbar (mit Warnung), in Produktion 503. */

export function checkInternalSecret(request: Request): Response | null {
  const expected = process.env.INTERNAL_API_SECRET?.trim();
  if (!expected) {
    if (isDevelopment()) {
      console.warn("[internal] INTERNAL_API_SECRET nicht gesetzt, Anfrage wird ohne Prüfung angenommen (nur Entwicklung)");
      return null;
    }
    return apiErrorResponse(503, "not_configured", "INTERNAL_API_SECRET ist nicht gesetzt.");
  }
  const given = request.headers.get("x-internal-secret") ?? "";
  const a = Buffer.from(given, "utf8");
  const b = Buffer.from(expected, "utf8");
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return apiErrorResponse(401, "unauthorized", "Internes Secret fehlt oder ist falsch.");
  }
  return null;
}
