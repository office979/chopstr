import type { NextRequest } from "next/server";
import { checkInternalSecret } from "@/lib/api/internal-auth";
import { apiErrorResponse, apiJson } from "@/lib/api/errors";
import { sendMail } from "@/lib/auth/mail";
import { isEmail, normalizeEmail } from "@/lib/auth/tokens";

export const dynamic = "force-dynamic";

/* Worker → Web: { to: [], subject, text, html? } → { ok, delivered, logged }. Versand über lib/auth/mail.ts
 * (SMTP_URL, sonst Konsole). html wird derzeit nicht gesendet (Textmail), bleibt im Vertrag optional. */
export async function POST(request: NextRequest) {
  const denied = checkInternalSecret(request);
  if (denied) return denied;
  let body: { to?: unknown; subject?: unknown; text?: unknown; html?: unknown } = {};
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return apiErrorResponse(400, "invalid_json", "Ungültiger JSON-Body.");
  }
  const to = (Array.isArray(body.to) ? body.to : [body.to]).map(normalizeEmail).filter((e) => e && isEmail(e));
  const subject = typeof body.subject === "string" ? body.subject.trim().slice(0, 200) : "";
  const text = typeof body.text === "string" ? body.text : "";
  if (!to.length) return apiErrorResponse(400, "validation_failed", "to braucht mindestens eine gültige E-Mail-Adresse.");
  if (!subject) return apiErrorResponse(400, "validation_failed", "subject fehlt.");
  if (!text.trim()) return apiErrorResponse(400, "validation_failed", "text fehlt.");
  let delivered = 0;
  let logged = 0;
  const failed: string[] = [];
  for (const recipient of to) {
    try {
      const r = await sendMail({ to: recipient, subject, text });
      if (r.delivered) delivered += 1;
      if (r.logged) logged += 1;
    } catch (error) {
      failed.push(recipient);
      console.warn("[internal/mail] Versand fehlgeschlagen:", error instanceof Error ? error.message : error);
    }
  }
  return apiJson({ ok: failed.length === 0, delivered, logged, failed });
}
