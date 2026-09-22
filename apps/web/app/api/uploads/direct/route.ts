import type { NextRequest } from "next/server";
import { createHash, randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { Readable, Writable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { bucketName, isDemoMode, isDirectUpload, localStorageDir, uploadMaxBytes } from "@/lib/env";
import { getQuota } from "@/lib/billing/quota";
import { noteUsageThresholds } from "@/lib/outbox";
import { finalizeUpload, isUuid, type UploadMeta } from "@/lib/uploads/finalize";
import { MultipartParser, multipartBoundary } from "@/lib/uploads/multipart";

export const dynamic = "force-dynamic";
/* Große Dateien: kein Timeout der Route-Funktion in der Entwicklung, Hosting-Limits gelten trotzdem */
export const maxDuration = 3600;

/* POST multipart/form-data (lokaler Testmodus, UPLOAD_MODE=direct): Feld `file` plus dieselben Metadaten wie beim
 * tus-Upload (title, brand_profile_id, rights_status, rights_confirmed, expected_speakers, brief_*, platform,
 * source_owner/title/url, client_ref). Rolle `source.upload`, Kontingent-Gate wie POST /api/uploads/token,
 * Rechte-Checkbox Pflicht, maximal UPLOAD_MAX_BYTES. Die Datei wird streamend nach
 * LOCAL_STORAGE_DIR/<sources-bucket>/uploads/<uuid><ext> geschrieben (SHA-256 nebenbei), danach legt
 * lib/uploads/finalize.ts die Quelle an wie der tusd-Hook. Antwort: { source_id, workflow_id }. */

const META_FIELDS = [
  "title",
  "brand_profile_id",
  "rights_status",
  "rights_confirmed",
  "expected_speakers",
  "brief_audience",
  "brief_wanted",
  "brief_exclude",
  "platform",
  "source_owner",
  "source_title",
  "source_url",
  "client_ref",
] as const;

const EXT_BY_MIME: Record<string, string> = {
  "video/mp4": ".mp4",
  "video/quicktime": ".mov",
  "video/x-matroska": ".mkv",
  "video/webm": ".webm",
  "audio/mpeg": ".mp3",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/x-m4a": ".m4a",
  "audio/mp4": ".m4a",
};

function extensionFor(filename: string, contentType: string): string {
  const fromName = path.extname(filename).toLowerCase();
  if (/^\.[a-z0-9]{1,8}$/.test(fromName)) return fromName;
  return EXT_BY_MIME[contentType.toLowerCase()] ?? "";
}

class TooLargeError extends Error {}

function json(status: number, body: Record<string, unknown>) {
  return Response.json(body, { status });
}

export async function POST(request: NextRequest) {
  if (!isDirectUpload() || isDemoMode()) {
    return json(404, { error: "Der direkte Upload ist nur im lokalen Testmodus (UPLOAD_MODE=direct) verfügbar." });
  }
  const dir = localStorageDir();
  if (!dir) return json(500, { error: "LOCAL_STORAGE_DIR ist nicht gesetzt." });

  const auth = await requireApiRole("source.upload");
  if (auth instanceof Response) return auth;

  const boundary = multipartBoundary(request.headers.get("content-type"));
  if (!boundary || !request.body) return json(400, { error: "Erwartet multipart/form-data mit Feld file." });

  const maxBytes = uploadMaxBytes();
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes + 1024 * 1024) {
    return json(413, { error: `Datei zu groß. Maximal ${Math.round(maxBytes / (1024 * 1024 * 1024))} GB.` });
  }

  const repo = getRepo();
  const quota = await getQuota(repo);
  void noteUsageThresholds(auth.workspaceId, quota);
  if (quota.exhausted) {
    return json(402, { error: quota.message, code: "quota_exhausted", used_minutes: quota.used_minutes, included_minutes: quota.included_minutes });
  }

  const uploadsDir = path.join(dir, bucketName("sources"), "uploads");
  await mkdir(uploadsDir, { recursive: true });

  const meta: UploadMeta = {};
  interface StoredFile {
    key: string;
    target: string;
    filename: string;
    contentType: string;
    bytes: number;
  }
  const state: { file: StoredFile | null } = { file: null };
  const hash = createHash("sha256");

  const parser = new MultipartParser(boundary, {
    onField(name, value) {
      if ((META_FIELDS as readonly string[]).includes(name)) meta[name] = value;
    },
    onFile(info) {
      if (info.field !== "file" || state.file) {
        /* Unbekannte oder doppelte Datei-Teile verwerfen */
        return new Writable({ write: (_chunk, _enc, cb) => cb() });
      }
      const id = randomUUID();
      const ext = extensionFor(info.filename, info.contentType);
      const current: StoredFile = {
        key: `uploads/${id}${ext}`,
        target: path.join(uploadsDir, `${id}${ext}`),
        filename: info.filename,
        contentType: info.contentType || "application/octet-stream",
        bytes: 0,
      };
      state.file = current;
      const out = createWriteStream(current.target);
      /* Datei-Senke: zählen, hashen, auf die Platte; der write-Callback trägt den Rückstau des Dateisystems */
      const sink = new Writable({
        write(chunk: Buffer, _enc, cb) {
          current.bytes += chunk.length;
          if (current.bytes > maxBytes) {
            cb(new TooLargeError(`Datei zu groß. Maximal ${Math.round(maxBytes / (1024 * 1024 * 1024))} GB.`));
            return;
          }
          hash.update(chunk);
          out.write(chunk, cb);
        },
        final(cb) {
          out.end(cb);
        },
      });
      out.on("error", (error) => sink.destroy(error));
      return sink;
    },
  });

  const cleanup = async () => {
    if (state.file) await rm(state.file.target, { force: true });
  };

  try {
    await pipeline(Readable.fromWeb(request.body as import("node:stream/web").ReadableStream<Uint8Array>), parser);
  } catch (error) {
    await cleanup();
    if (error instanceof TooLargeError) return json(413, { error: error.message });
    const message = error instanceof Error ? error.message : "Upload fehlgeschlagen";
    console.warn("[uploads/direct] Upload abgebrochen:", message);
    return json(400, { error: `Upload fehlgeschlagen: ${message}` });
  }

  const stored = state.file;
  if (!stored) return json(400, { error: "Datei fehlt (Feld file)." });
  if (stored.bytes <= 0) {
    await cleanup();
    return json(400, { error: "Die Datei ist leer." });
  }
  if (meta.rights_confirmed !== "true") {
    await cleanup();
    return json(400, { error: "Die Rechte am Material müssen bestätigt werden." });
  }
  if (!meta.title?.trim()) {
    await cleanup();
    return json(400, { error: "Titel fehlt." });
  }

  let brandProfileId: string | null = null;
  if (meta.brand_profile_id) {
    if (!isUuid(meta.brand_profile_id)) {
      await cleanup();
      return json(400, { error: "Markenprofil ungültig" });
    }
    const brand = await repo.getBrandProfile(meta.brand_profile_id);
    if (!brand) {
      await cleanup();
      return json(404, { error: "Markenprofil nicht gefunden" });
    }
    brandProfileId = brand.id;
  }

  const sha256 = hash.digest("hex");
  const result = await finalizeUpload({
    session: auth,
    brandProfileId,
    meta: { ...meta, filename: stored.filename, filetype: stored.contentType },
    storageKey: stored.key,
    storageBucket: bucketName("sources"),
    sizeBytes: stored.bytes,
    sha256,
    via: "direct",
  });
  return Response.json({ ...result, size_bytes: stored.bytes, sha256 });
}
