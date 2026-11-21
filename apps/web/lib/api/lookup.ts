import "server-only";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import type { Candidate, Clip, Source } from "@/lib/repo/types";
import type { Publication } from "@/lib/repo/types-api";
import { notFound } from "@/lib/api/errors";

/* Laden mit 404 auf Deutsch; untergeordnete Objekte werden immer über ihre Quelle abgesichert (Brand-Scope, Workspace).
 * Eine ID, die keine UUID ist, kann es nicht geben: 404 statt eines 500 aus Postgres (invalid input syntax). */

const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuidShape(id: string): boolean {
  return UUID_SHAPE.test(id);
}

export async function loadSource(id: string): Promise<Source> {
  if (!isUuidShape(id)) throw notFound("Quelle nicht gefunden.");
  const source = await getRepo().getSource(id);
  if (!source) throw notFound("Quelle nicht gefunden.");
  return source;
}

export async function loadCandidate(id: string): Promise<{ candidate: Candidate; source: Source }> {
  if (!isUuidShape(id)) throw notFound("Kandidat nicht gefunden.");
  const candidate = await getRepo().getCandidate(id);
  if (!candidate) throw notFound("Kandidat nicht gefunden.");
  const source = await getRepo().getSource(candidate.source_id);
  if (!source) throw notFound("Kandidat nicht gefunden.");
  return { candidate, source };
}

export async function loadClip(id: string): Promise<{ clip: Clip; source: Source }> {
  if (!isUuidShape(id)) throw notFound("Clip nicht gefunden.");
  const clip = await getRepo().getClip(id);
  if (!clip || clip.status === "deleted") throw notFound("Clip nicht gefunden.");
  const source = await getRepo().getSource(clip.source_id);
  if (!source) throw notFound("Clip nicht gefunden.");
  return { clip, source };
}

export async function loadPublication(id: string): Promise<Publication> {
  if (!isUuidShape(id)) throw notFound("Publikation nicht gefunden.");
  const publication = await getApiRepo().getPublication(id);
  if (!publication) throw notFound("Publikation nicht gefunden.");
  return publication;
}
