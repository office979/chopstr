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

/* Lokaler Testmodus ohne Docker: direkter Upload in einen Ordner statt tusd, Medien aus demselben Ordner */
export type UploadMode = "tus" | "direct";

export function uploadMode(): UploadMode {
  const raw = process.env.UPLOAD_MODE ?? process.env.NEXT_PUBLIC_UPLOAD_MODE;
  return raw === "direct" ? "direct" : "tus";
}

export function isDirectUpload(): boolean {
  return uploadMode() === "direct";
}

/* MEDIA_MODE=local: GET /api/media/[...key] liefert Dateien aus LOCAL_STORAGE_DIR */
export function isLocalMedia(): boolean {
  return process.env.MEDIA_MODE === "local";
}

export function localStorageDir(): string | null {
  const dir = process.env.LOCAL_STORAGE_DIR?.trim();
  return dir ? dir : null;
}

/* Bucket-Ordner unter LOCAL_STORAGE_DIR, identisch mit dem Python-Worker (storage.py: <dir>/<bucket-name>/<key>) */
export function bucketName(bucket: "sources" | "derived"): string {
  if (bucket === "sources") return process.env.S3_BUCKET_SOURCES ?? "chopstr-sources";
  return process.env.S3_BUCKET_DERIVED ?? "chopstr-derived";
}

/* Ohne TEMPORAL_ADDRESS holt der lokale Worker (python -m chopstr_worker.local_worker) Quellen, Clips und Löschjobs per Polling ab */
export function temporalConfigured(): boolean {
  return !isDemoMode() && Boolean(process.env.TEMPORAL_ADDRESS);
}
