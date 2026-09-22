import "server-only";
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import type { Credentials } from "@/lib/repo/types-publishing";

/* Zugangsdaten der Plattform-Verbindungen: AES-256-GCM mit CREDENTIALS_KEY (32 Bytes base64).
 * Format in platform_connections.credentials: `v1:<iv b64>:<tag b64>:<ciphertext b64>`.
 * Ohne Schlüssel: in Produktion Fehler; in der Entwicklung Klartext mit Präfix `plain:` und Warnung
 * (einmal je Prozess). Nie im Klartext loggen. */

const PREFIX = "v1:";
const PLAIN = "plain:";
let warned = false;

export class CredentialsKeyError extends Error {
  constructor(message = "CREDENTIALS_KEY fehlt oder ist ungültig (32 Bytes base64).") {
    super(message);
    this.name = "CredentialsKeyError";
  }
}

function isProduction(): boolean {
  return (process.env.APP_ENV ?? process.env.NODE_ENV) === "production";
}

export function credentialsKey(): Buffer | null {
  const raw = process.env.CREDENTIALS_KEY?.trim();
  if (!raw) return null;
  const buf = Buffer.from(raw, "base64");
  if (buf.length !== 32) throw new CredentialsKeyError();
  return buf;
}

export function credentialsKeyConfigured(): boolean {
  try {
    return credentialsKey() != null;
  } catch {
    return false;
  }
}

export function encryptCredentials(creds: Credentials): string {
  const plaintext = JSON.stringify(creds);
  const key = credentialsKey();
  if (!key) {
    if (isProduction()) throw new CredentialsKeyError("CREDENTIALS_KEY ist in Produktion Pflicht; Zugangsdaten werden nicht gespeichert.");
    if (!warned) {
      console.warn("[publishing] CREDENTIALS_KEY fehlt: Zugangsdaten werden unverschlüsselt gespeichert (nur Entwicklung).");
      warned = true;
    }
    return PLAIN + plaintext;
  }
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const enc = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${PREFIX}${iv.toString("base64")}:${tag.toString("base64")}:${enc.toString("base64")}`;
}

export function decryptCredentials(stored: string | null | undefined): Credentials | null {
  if (!stored) return null;
  if (stored.startsWith(PLAIN)) {
    try {
      return JSON.parse(stored.slice(PLAIN.length)) as Credentials;
    } catch {
      return null;
    }
  }
  if (!stored.startsWith(PREFIX)) return null;
  const key = credentialsKey();
  if (!key) throw new CredentialsKeyError("CREDENTIALS_KEY fehlt, verschlüsselte Zugangsdaten können nicht gelesen werden.");
  const [, ivB64, tagB64, dataB64] = stored.split(":");
  if (!ivB64 || !tagB64 || !dataB64) return null;
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(ivB64, "base64"));
  decipher.setAuthTag(Buffer.from(tagB64, "base64"));
  const dec = Buffer.concat([decipher.update(Buffer.from(dataB64, "base64")), decipher.final()]);
  return JSON.parse(dec.toString("utf8")) as Credentials;
}

export function isEncrypted(stored: string | null | undefined): boolean {
  return Boolean(stored && stored.startsWith(PREFIX));
}
