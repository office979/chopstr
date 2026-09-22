import "server-only";

/* Rate-Limit der öffentlichen API: API_RATE_LIMIT_PER_MIN (Default 600) Anfragen pro Minute je Schlüssel.
 * Festes Minutenfenster, In-Memory je Prozess. TODO: Redis (REDIS_URL) für mehrere Instanzen. */

export const RATE_LIMIT_DEFAULT = 600;
const WINDOW_MS = 60 * 1000;

interface Bucket {
  count: number;
  resetAt: number;
}

declare global {
  var __chopstrApiRateLimit: Map<string, Bucket> | undefined;
}

function store(): Map<string, Bucket> {
  if (!globalThis.__chopstrApiRateLimit) globalThis.__chopstrApiRateLimit = new Map();
  return globalThis.__chopstrApiRateLimit;
}

export function rateLimitPerMinute(): number {
  const raw = Number(process.env.API_RATE_LIMIT_PER_MIN);
  return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : RATE_LIMIT_DEFAULT;
}

export interface RateLimitResult {
  allowed: boolean;
  limit: number;
  remaining: number;
  /* Sekunden bis zum Fenster-Ende */
  retryAfterS: number;
}

export function consumeRateLimit(keyId: string): RateLimitResult {
  const limit = rateLimitPerMinute();
  const s = store();
  const now = Date.now();
  let b = s.get(keyId);
  if (!b || b.resetAt <= now) {
    b = { count: 0, resetAt: now + WINDOW_MS };
    s.set(keyId, b);
    if (s.size > 10_000) {
      for (const [k, v] of s) if (v.resetAt <= now) s.delete(k);
    }
  }
  const retryAfterS = Math.max(1, Math.ceil((b.resetAt - now) / 1000));
  if (b.count >= limit) return { allowed: false, limit, remaining: 0, retryAfterS };
  b.count += 1;
  return { allowed: true, limit, remaining: Math.max(0, limit - b.count), retryAfterS };
}

export function rateLimitHeaders(r: RateLimitResult): Record<string, string> {
  return {
    "X-RateLimit-Limit": String(r.limit),
    "X-RateLimit-Remaining": String(r.remaining),
    ...(r.allowed ? {} : { "Retry-After": String(r.retryAfterS) }),
  };
}
