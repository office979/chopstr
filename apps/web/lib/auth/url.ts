import "server-only";
import { headers } from "next/headers";

/* Basis-URL für Links in E-Mails: APP_BASE_URL, sonst aus den Request-Headern (Proxy-Header zuerst). */
export async function appBaseUrl(): Promise<string> {
  const configured = process.env.APP_BASE_URL?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  try {
    const h = await headers();
    const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
    const proto = h.get("x-forwarded-proto") ?? (host.startsWith("localhost") || host.startsWith("127.") ? "http" : "https");
    return `${proto}://${host}`;
  } catch {
    return "http://localhost:3000";
  }
}

/* Nur relative Pfade als Ziel nach dem Login zulassen (kein Open Redirect) */
export function safeNext(value: unknown, fallback = "/"): string {
  if (typeof value !== "string") return fallback;
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return fallback;
  if (value.startsWith("/anmelden") || value.startsWith("/registrieren") || value.startsWith("/abmelden")) return fallback;
  return value;
}
