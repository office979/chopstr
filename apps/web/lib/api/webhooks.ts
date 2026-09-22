import "server-only";
import { randomBytes } from "node:crypto";
import { WEBHOOK_EVENTS } from "@/lib/repo/types-api";

/* Regeln für Webhook-Endpunkte (PHASE5.md): nur https, Host darf nicht privat oder lokal sein; Secret 32 Bytes base64url. */

const PRIVATE_HOST_RE = /^(localhost|.*\.local|.*\.internal|.*\.localhost|0\.0\.0\.0|\[?::1\]?)$/i;

function isPrivateIpv4(host: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 10 || a === 127 || a === 0 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
}

export function webhookUrlProblem(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return "Bitte eine vollständige URL angeben.";
  }
  if (url.protocol !== "https:") return "Webhooks brauchen https.";
  const host = url.hostname.toLowerCase();
  if (!host.includes(".") && host !== "localhost") return "Der Host muss ein öffentlicher Domainname sein.";
  if (PRIVATE_HOST_RE.test(host) || isPrivateIpv4(host) || host.startsWith("[")) return "Private oder lokale Hosts sind nicht erlaubt.";
  if (url.username || url.password) return "Zugangsdaten in der URL sind nicht erlaubt.";
  return null;
}

export function normalizeEvents(raw: unknown): { events: string[]; unknown: string[] } {
  const list = Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [];
  const known = new Set<string>(WEBHOOK_EVENTS);
  const events = [...new Set(list.filter((e) => known.has(e)))];
  const unknown = list.filter((e) => !known.has(e));
  return { events, unknown };
}

export function generateWebhookSecret(): string {
  return `whsec_${randomBytes(32).toString("base64url")}`;
}
