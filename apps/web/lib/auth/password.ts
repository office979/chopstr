import "server-only";
import { hash, verify, type Algorithm } from "@node-rs/argon2";

/* Passwort-Hash: Argon2id, m = 65536 KiB, t = 3, p = 4, Ausgabe als PHC-String (in users.password_hash). */

const OPTIONS = {
  /* Algorithm.Argon2id (const enum, isolatedModules) */
  algorithm: 2 as Algorithm,
  memoryCost: 65536,
  timeCost: 3,
  parallelism: 4,
};

export const PASSWORD_MIN_LENGTH = 10;

export async function hashPassword(password: string): Promise<string> {
  return hash(password, OPTIONS);
}

export async function verifyPassword(phc: string | null | undefined, password: string): Promise<boolean> {
  if (!phc) return false;
  try {
    return await verify(phc, password, OPTIONS);
  } catch {
    return false;
  }
}

/* Deutsche Feldprüfung für Formulare */
export function passwordProblem(password: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) return `Mindestens ${PASSWORD_MIN_LENGTH} Zeichen.`;
  if (password.length > 200) return "Höchstens 200 Zeichen.";
  if (!/[a-zA-ZäöüÄÖÜß]/.test(password) || !/[0-9]/.test(password)) return "Bitte Buchstaben und mindestens eine Ziffer kombinieren.";
  return null;
}
