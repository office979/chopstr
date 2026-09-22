/* Hilfen für kompakte, deutsche Tool-Ausgaben und Listenbegrenzung. */

import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

export const LIST_LIMIT = 50;

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "?";
  const total = Math.max(0, Math.round(value));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export function formatDecimal(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "?";
  return value.toFixed(digits).replace(".", ",");
}

/* Nimmt Listen entgegen, die die API entweder roh oder unter einem Schlüssel liefert. */
export function unwrapList<T>(body: unknown, ...keys: string[]): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    for (const key of [...keys, "data", "items"]) {
      const value = record[key];
      if (Array.isArray(value)) return value as T[];
    }
  }
  return [];
}

/* Nimmt Einzelobjekte entgegen, die die API roh oder unter einem Schlüssel liefert. */
export function unwrapObject<T>(body: unknown, ...keys: string[]): T {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    for (const key of keys) {
      const value = record[key];
      if (value && typeof value === "object" && !Array.isArray(value)) return value as T;
    }
  }
  return body as T;
}

export interface Truncated<T> {
  items: T[];
  total: number;
  truncated: boolean;
}

export function limitList<T>(items: T[], limit = LIST_LIMIT): Truncated<T> {
  return { items: items.slice(0, limit), total: items.length, truncated: items.length > limit };
}

export function truncationNote(t: Truncated<unknown>, what: string): string {
  return t.truncated ? `\nHinweis: ${t.total} ${what} vorhanden, hier die ersten ${t.items.length}.` : "";
}

export function countWords(text: string): number {
  return text
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0).length;
}

export function firstWords(text: string, n: number): { text: string; truncated: boolean } {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length <= n) return { text: words.join(" "), truncated: false };
  return { text: words.slice(0, n).join(" "), truncated: true };
}

/* Standardausgabe: kurzes Resümee als Text plus strukturierter JSON-Anhang. */
export function textResult(summary: string, data?: Record<string, unknown>): CallToolResult {
  const content: CallToolResult["content"] = [{ type: "text", text: summary }];
  if (data !== undefined) {
    content.push({ type: "text", text: "```json\n" + JSON.stringify(data, null, 2) + "\n```" });
  }
  return data !== undefined ? { content, structuredContent: data } : { content };
}

export function errorResult(message: string, data?: Record<string, unknown>): CallToolResult {
  const content: CallToolResult["content"] = [{ type: "text", text: message }];
  return data !== undefined ? { content, structuredContent: data, isError: true } : { content, isError: true };
}

/* Vorschau für schreibende Tools ohne confirm: true. Keine stille Aktion. */
export function previewResult(action: string, description: string, payload: Record<string, unknown>): CallToolResult {
  const summary = [
    `Vorschau (noch nichts ausgeführt): ${description}`,
    "",
    "Wenn das so passt, denselben Aufruf mit confirm: true wiederholen. Bitte vorher beim Nutzer rückfragen, falls die Aktion nicht ausdrücklich gewünscht war.",
  ].join("\n");
  return textResult(summary, { preview: true, action, ...payload });
}
