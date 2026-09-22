import "server-only";

/* Rate-Limit für Anmeldeversuche: 5 Versuche pro 15 Minuten je E-Mail und je IP.
 * In-Memory (pro Prozess). TODO: Redis (REDIS_URL) für mehrere Instanzen. */

export const LOGIN_MAX_ATTEMPTS = 5;
export const LOGIN_WINDOW_MS = 15 * 60 * 1000;

interface Bucket {
  count: number;
  resetAt: number;
}

declare global {
  var __chopstrRateLimit: Map<string, Bucket> | undefined;
}

function store(): Map<string, Bucket> {
  if (!globalThis.__chopstrRateLimit) globalThis.__chopstrRateLimit = new Map();
  return globalThis.__chopstrRateLimit;
}

function bucket(key: string): Bucket {
  const s = store();
  const now = Date.now();
  const b = s.get(key);
  if (!b || b.resetAt <= now) {
    const fresh = { count: 0, resetAt: now + LOGIN_WINDOW_MS };
    s.set(key, fresh);
    if (s.size > 10_000) {
      for (const [k, v] of s) if (v.resetAt <= now) s.delete(k);
    }
    return fresh;
  }
  return b;
}

export interface RateLimitState {
  allowed: boolean;
  retryAfterS: number;
}

/* Prüft alle Schlüssel (E-Mail, IP), ohne zu zählen */
export function checkRateLimit(keys: string[]): RateLimitState {
  let retry = 0;
  for (const key of keys) {
    const b = bucket(key);
    if (b.count >= LOGIN_MAX_ATTEMPTS) retry = Math.max(retry, Math.ceil((b.resetAt - Date.now()) / 1000));
  }
  return { allowed: retry === 0, retryAfterS: retry };
}

/* Zählt einen fehlgeschlagenen Versuch */
export function recordAttempt(keys: string[]): void {
  for (const key of keys) bucket(key).count += 1;
}

/* Nach Erfolg zurücksetzen */
export function clearAttempts(keys: string[]): void {
  for (const key of keys) store().delete(key);
}
