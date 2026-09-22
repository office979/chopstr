import "server-only";
import { bucketName, isDemoMode, localStorageDir } from "@/lib/env";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";

/* Objektspeicher der Web-App (Phase 4, Block B): CI-Assets im `derived`-Bucket.
 *
 * Mit S3_ENDPOINT (oder S3_REGION plus Schlüssel) läuft alles über @aws-sdk/client-s3 mit path-style
 * Adressierung (MinIO, Hetzner Object Storage). Mit LOCAL_STORAGE_DIR (lokaler Testmodus ohne Docker) liegen die
 * Objekte als Dateien unter <dir>/<bucket-name>/<key>. Sonst oder im Demo-Modus liegen sie im Speicher des
 * Serverprozesses (überlebt Hot Reloads über globalThis, nicht den Neustart). Der Worker liest dieselben Keys
 * aus dem `derived`-Bucket (workers/chopstr_worker/storage.py). */

export type Bucket = "sources" | "derived";

export interface StoredObject {
  body: Uint8Array;
  contentType: string | null;
}

export interface ObjectStore {
  readonly kind: "s3" | "memory" | "local";
  put(bucket: Bucket, key: string, body: Uint8Array, contentType: string | null): Promise<void>;
  get(bucket: Bucket, key: string): Promise<StoredObject | null>;
  delete(bucket: Bucket, key: string): Promise<void>;
}

declare global {
  var __chopstrMemoryStore: Map<string, StoredObject> | undefined;
}

function memoryMap(): Map<string, StoredObject> {
  if (!globalThis.__chopstrMemoryStore) globalThis.__chopstrMemoryStore = new Map();
  return globalThis.__chopstrMemoryStore;
}

const memoryStore: ObjectStore = {
  kind: "memory",
  async put(bucket, key, body, contentType) {
    memoryMap().set(`${bucket}/${key}`, { body, contentType });
  },
  async get(bucket, key) {
    return memoryMap().get(`${bucket}/${key}`) ?? null;
  },
  async delete(bucket, key) {
    memoryMap().delete(`${bucket}/${key}`);
  },
};


function s3Configured(): boolean {
  return Boolean(process.env.S3_ENDPOINT || (process.env.S3_ACCESS_KEY && process.env.S3_SECRET_KEY));
}

let s3Client: import("@aws-sdk/client-s3").S3Client | null = null;

async function s3(): Promise<import("@aws-sdk/client-s3").S3Client> {
  if (s3Client) return s3Client;
  const { S3Client } = await import("@aws-sdk/client-s3");
  const accessKeyId = process.env.S3_ACCESS_KEY ?? process.env.AWS_ACCESS_KEY_ID;
  const secretAccessKey = process.env.S3_SECRET_KEY ?? process.env.AWS_SECRET_ACCESS_KEY;
  s3Client = new S3Client({
    region: process.env.S3_REGION ?? "eu-central-1",
    endpoint: process.env.S3_ENDPOINT || undefined,
    forcePathStyle: (process.env.S3_FORCE_PATH_STYLE ?? "true") !== "false",
    credentials: accessKeyId && secretAccessKey ? { accessKeyId, secretAccessKey } : undefined,
  });
  return s3Client;
}

const s3Store: ObjectStore = {
  kind: "s3",
  async put(bucket, key, body, contentType) {
    const { PutObjectCommand } = await import("@aws-sdk/client-s3");
    await (await s3()).send(new PutObjectCommand({ Bucket: bucketName(bucket), Key: key, Body: body, ContentType: contentType ?? undefined }));
  },
  async get(bucket, key) {
    const { GetObjectCommand, NoSuchKey } = await import("@aws-sdk/client-s3");
    try {
      const out = await (await s3()).send(new GetObjectCommand({ Bucket: bucketName(bucket), Key: key }));
      const bytes = out.Body ? await out.Body.transformToByteArray() : new Uint8Array();
      return { body: bytes, contentType: out.ContentType ?? null };
    } catch (error) {
      if (error instanceof NoSuchKey || (error as { name?: string })?.name === "NoSuchKey") return null;
      throw error;
    }
  },
  async delete(bucket, key) {
    const { DeleteObjectCommand } = await import("@aws-sdk/client-s3");
    await (await s3()).send(new DeleteObjectCommand({ Bucket: bucketName(bucket), Key: key }));
  },
};

/* Lokaler Testmodus: LOCAL_STORAGE_DIR/<bucket-name>/<key>, derselbe Ordner wie beim Python-Worker */
function localPath(bucket: Bucket, key: string): string {
  const root = path.resolve(localStorageDir() ?? "");
  const target = path.resolve(root, bucketName(bucket), key.replace(/^\/+/, ""));
  if (target !== root && !target.startsWith(root + path.sep)) throw new Error("Ungültiger Storage-Key");
  return target;
}

function contentTypeFromExt(key: string): string | null {
  const ext = path.extname(key).toLowerCase();
  const map: Record<string, string> = { ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };
  return map[ext] ?? null;
}

const localStore: ObjectStore = {
  kind: "local",
  async put(bucket, key, body) {
    const target = localPath(bucket, key);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, body);
  },
  async get(bucket, key) {
    try {
      const body = await readFile(localPath(bucket, key));
      return { body: new Uint8Array(body), contentType: contentTypeFromExt(key) };
    } catch (error) {
      if ((error as { code?: string })?.code === "ENOENT") return null;
      throw error;
    }
  },
  async delete(bucket, key) {
    await rm(localPath(bucket, key), { force: true });
  },
};

export function getStore(): ObjectStore {
  if (isDemoMode()) return memoryStore;
  if (s3Configured()) return s3Store;
  if (localStorageDir()) return localStore;
  return memoryStore;
}
