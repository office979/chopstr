import "server-only";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { bucketName, localStorageDir } from "@/lib/env";

/* Lokale Medienauslieferung (MEDIA_MODE=local): Dateien aus LOCAL_STORAGE_DIR/<bucket-name>/<key> mit Content-Type,
 * Accept-Ranges und Range-Antworten (206) für das Scrubbing im <video>. Die Berechtigung prüft die Route. */

const CONTENT_TYPES: Record<string, string> = {
  ".mp4": "video/mp4",
  ".m4v": "video/mp4",
  ".mov": "video/quicktime",
  ".webm": "video/webm",
  ".mkv": "video/x-matroska",
  ".m3u8": "application/vnd.apple.mpegurl",
  ".ts": "video/mp2t",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".m4a": "audio/mp4",
  ".aac": "audio/aac",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".srt": "application/x-subrip; charset=utf-8",
  ".vtt": "text/vtt; charset=utf-8",
  ".ass": "text/x-ssa; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
};

export function contentTypeFor(key: string): string {
  return CONTENT_TYPES[path.extname(key).toLowerCase()] ?? "application/octet-stream";
}

/* Key ohne Traversal, ohne absolute Pfade, ohne leere Segmente */
export function isSafeMediaKey(key: string): boolean {
  if (!key || key.length > 1024) return false;
  if (key.startsWith("/") || key.includes("\\") || key.includes("\0")) return false;
  return key.split("/").every((seg) => seg.length > 0 && seg !== "." && seg !== "..");
}

export function localMediaPath(bucket: "sources" | "derived", key: string): string | null {
  const dir = localStorageDir();
  if (!dir || !isSafeMediaKey(key)) return null;
  const root = path.resolve(dir);
  const target = path.resolve(root, bucketName(bucket), key);
  if (!target.startsWith(root + path.sep)) return null;
  return target;
}

export interface RangeSpec {
  start: number;
  end: number;
}

/* `bytes=a-b`, `bytes=a-`, `bytes=-n`; null = kein oder unbrauchbarer Header, undefined = nicht erfüllbar (416) */
export function parseRange(header: string | null, size: number): RangeSpec | null | undefined {
  if (!header) return null;
  const m = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!m) return null;
  const [, a, b] = m;
  if (a === "" && b === "") return null;
  let start: number;
  let end: number;
  if (a === "") {
    const suffix = Number(b);
    if (!Number.isFinite(suffix) || suffix <= 0) return undefined;
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(a);
    end = b === "" ? size - 1 : Math.min(Number(b), size - 1);
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= size) return undefined;
  return { start, end };
}

/* Datei als Response: 200 komplett oder 206 mit Range; HEAD ohne Body */
export async function serveLocalFile(filePath: string, key: string, request: Request): Promise<Response> {
  let info: Awaited<ReturnType<typeof stat>>;
  try {
    info = await stat(filePath);
  } catch {
    return new Response("Nicht gefunden", { status: 404 });
  }
  if (!info.isFile()) return new Response("Nicht gefunden", { status: 404 });

  const size = info.size;
  const headers = new Headers({
    "Content-Type": contentTypeFor(key),
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=3600",
    "Last-Modified": info.mtime.toUTCString(),
    "X-Content-Type-Options": "nosniff",
  });
  const range = parseRange(request.headers.get("range"), size);
  if (range === undefined) {
    headers.set("Content-Range", `bytes */${size}`);
    return new Response(null, { status: 416, headers });
  }
  const start = range ? range.start : 0;
  const end = range ? range.end : size - 1;
  const length = size === 0 ? 0 : end - start + 1;
  headers.set("Content-Length", String(length));
  if (range) headers.set("Content-Range", `bytes ${start}-${end}/${size}`);
  const status = range ? 206 : 200;

  if (request.method === "HEAD" || length === 0) return new Response(null, { status, headers });
  const stream = createReadStream(filePath, { start, end });
  return new Response(Readable.toWeb(stream) as ReadableStream, { status, headers });
}
