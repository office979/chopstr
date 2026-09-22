import "server-only";
import { getRepo } from "@/lib/repo";
import type { Candidate, Clip, Source } from "@/lib/repo/types";
import { notFound } from "@/lib/api/errors";

/* Laden mit 404 auf Deutsch; untergeordnete Objekte werden immer über ihre Quelle abgesichert (Brand-Scope, Workspace) */

export async function loadSource(id: string): Promise<Source> {
  const source = await getRepo().getSource(id);
  if (!source) throw notFound("Quelle nicht gefunden.");
  return source;
}

export async function loadCandidate(id: string): Promise<{ candidate: Candidate; source: Source }> {
  const candidate = await getRepo().getCandidate(id);
  if (!candidate) throw notFound("Kandidat nicht gefunden.");
  const source = await getRepo().getSource(candidate.source_id);
  if (!source) throw notFound("Kandidat nicht gefunden.");
  return { candidate, source };
}

export async function loadClip(id: string): Promise<{ clip: Clip; source: Source }> {
  const clip = await getRepo().getClip(id);
  if (!clip || clip.status === "deleted") throw notFound("Clip nicht gefunden.");
  const source = await getRepo().getSource(clip.source_id);
  if (!source) throw notFound("Clip nicht gefunden.");
  return { clip, source };
}
