/* Zentrale Umgebungsvariablen mit Defaults */

export const UPLOAD_MAX_BYTES_DEFAULT = 5 * 1024 * 1024 * 1024; // 5 GB

export function uploadMaxBytes(): number {
  const raw = process.env.UPLOAD_MAX_BYTES ?? process.env.NEXT_PUBLIC_UPLOAD_MAX_BYTES;
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? n : UPLOAD_MAX_BYTES_DEFAULT;
}

/* Demo-Modus: keine Datenbank konfiguriert */
export function isDemoMode(): boolean {
  return !process.env.DATABASE_URL;
}

export function appVersion(): string {
  return process.env.APP_VERSION ?? "0.1.0";
}
