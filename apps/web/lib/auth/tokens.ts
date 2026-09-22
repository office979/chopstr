import "server-only";
import { randomBytes } from "node:crypto";

/* Zufallstoken (Sitzungs-IDs, Magic-Links, Passwort-Reset, Einladungen): 32 Bytes base64url */
export function randomToken(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export const LOGIN_TOKEN_TTL_MS = 15 * 60 * 1000;
export const INVITE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

const TOKEN_RE = /^[A-Za-z0-9_-]{20,128}$/;

export function isTokenShape(value: unknown): value is string {
  return typeof value === "string" && TOKEN_RE.test(value);
}

export function normalizeEmail(raw: unknown): string {
  return typeof raw === "string" ? raw.trim().toLowerCase() : "";
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function isEmail(value: string): boolean {
  return EMAIL_RE.test(value) && value.length <= 254;
}
