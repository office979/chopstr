/* Formatierung im DACH-Format */

export function formatTimecode(seconds: number | null | undefined, withMillis = false): string {
  if (seconds == null || !Number.isFinite(seconds)) return "--:--";
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m).padStart(2, "0");
  const base = h > 0 ? `${h}:${mm}:${String(sec).padStart(2, "0")}` : `${mm}:${String(sec).padStart(2, "0")}`;
  if (!withMillis) return base;
  const ms = Math.floor((s - Math.floor(s)) * 100);
  return `${base},${String(ms).padStart(2, "0")}`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "unbekannt";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toLocaleString("de-AT", { maximumFractionDigits: i === 0 ? 0 : 1 })} ${units[i]}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "unbekannt";
  return new Date(iso).toLocaleDateString("de-AT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "unbekannt";
  return new Date(iso).toLocaleString("de-AT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortHash(hash: string | null | undefined, length = 12): string {
  if (!hash) return "wird berechnet";
  return `${hash.slice(0, length)}…`;
}
