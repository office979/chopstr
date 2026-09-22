import "server-only";
import { isDemoMode } from "@/lib/env";

/* Objektspeicher der Web-App (Phase 4, Block B): CI-Assets im `derived`-Bucket.
 *
 * Mit S3_ENDPOINT (oder S3_REGION plus Schlüssel) läuft alles über @aws-sdk/client-s3 mit path-style
 * Adressierung (MinIO, Hetzner Object Storage). Ohne S3-Konfiguration oder im Demo-Modus liegen die Objekte
 * im Speicher des Serverprozesses (überlebt Hot Reloads über globalThis, nicht den Neustart). Der Worker
 * liest dieselben Keys aus dem `derived`-Bucket (workers/chopstr_worker/storage.py). */

export type Bucket = "sources" | "derived";

export interface StoredObject {
  body: Uint8Array;
  contentType: string | null;
}

export interface ObjectStore {
  readonly kind: "s3" | "memory";
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

function bucketName(bucket: Bucket): string {
  if (bucket === "sources") return process.env.S3_BUCKET_SOURCES ?? "chopstr-sources";
  return process.env.S3_BUCKET_DERIVED ?? "chopstr-derived";
}

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

export function getStore(): ObjectStore {
  if (isDemoMode() || !s3Configured()) return memoryStore;
  return s3Store;
}
