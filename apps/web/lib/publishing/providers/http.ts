import { ProviderError } from "./types";

/* Kleine fetch-Helfer für Provider-Aufrufe. Fehlermeldungen enthalten nie Tokens (nur Status und gekürzten Body). */

const TIMEOUT_MS = Number(process.env.PUBLISH_HTTP_TIMEOUT_MS ?? 30_000);

async function run(url: string, init: RequestInit): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } catch (error) {
    throw new ProviderError(`Aufruf fehlgeschlagen: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
  }
}

function safeSnippet(text: string): string {
  return text.replace(/(access_token|refresh_token|client_secret)["']?\s*[:=]\s*["']?[^"',&\s]+/gi, "$1=[redacted]").slice(0, 300);
}

export async function readJson<T>(res: Response, what: string): Promise<T> {
  const text = await res.text();
  if (!res.ok) {
    throw new ProviderError(`${what} antwortete mit ${res.status}: ${safeSnippet(text)}`, res.status);
  }
  try {
    return (text ? JSON.parse(text) : {}) as T;
  } catch {
    throw new ProviderError(`${what} lieferte kein JSON`, res.status);
  }
}

export async function getJson<T>(url: string, headers: Record<string, string>, what: string): Promise<T> {
  const res = await run(url, { method: "GET", headers });
  return readJson<T>(res, what);
}

export async function postJson<T>(url: string, body: unknown, headers: Record<string, string>, what: string): Promise<{ data: T; headers: Headers }> {
  const res = await run(url, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  const data = await readJson<T>(res, what);
  return { data, headers: res.headers };
}

export async function postForm<T>(url: string, form: Record<string, string>, headers: Record<string, string>, what: string): Promise<T> {
  const res = await run(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", ...headers },
    body: new URLSearchParams(form).toString(),
  });
  return readJson<T>(res, what);
}

export async function putBytes(url: string, bytes: Uint8Array, headers: Record<string, string>, what: string): Promise<Response> {
  const res = await run(url, { method: "PUT", headers, body: bytes as unknown as BodyInit });
  if (!res.ok && res.status !== 308) {
    throw new ProviderError(`${what} antwortete mit ${res.status}: ${safeSnippet(await res.text())}`, res.status);
  }
  return res;
}

export function bearer(token: string | undefined): Record<string, string> {
  if (!token) throw new ProviderError("Kein Access-Token in den Zugangsdaten");
  return { Authorization: `Bearer ${token}` };
}

export function expiresAtFrom(expiresInSeconds: unknown): string | null {
  const n = Number(expiresInSeconds);
  if (!Number.isFinite(n) || n <= 0) return null;
  return new Date(Date.now() + n * 1000).toISOString();
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
