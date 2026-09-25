import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { signalApprove } from "@/lib/temporal";
import { ASPECT_LABELS, PLATFORM_LABELS } from "@/lib/clips/labels";
import { FASSUNG_FORMATE, formatSatz, plattformFuerFormat } from "@/lib/clips/fassungen";
import type { Aspect, Platform } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

const ASPEKTE = FASSUNG_FORMATE;

function istAspect(v: unknown): v is Aspect {
  return typeof v === "string" && (ASPEKTE as string[]).includes(v);
}

function istPlattform(v: unknown): v is Platform {
  return v === "tiktok" || v === "reels" || v === "shorts" || v === "linkedin";
}

/* Eine weitere Fassung desselben Moments in einem anderen Zielformat.
 *
 * Das Format ist hier die Einheit und nicht die Plattform, und das ist eine bewusste Entscheidung.
 * TikTok, Reels und Shorts sind bei chopstr alle hochkant im selben Format; eine zweite Datei
 * dafür wäre Bild für Bild dieselbe Datei mit einem anderen Wort im Feld daneben. Wer die braucht,
 * braucht keine zweite Datei, sondern einen anderen Text zum Posten.
 *
 * Was sich wirklich unterscheidet, ist das Format: ein hochkanter Clip und ein quadratischer haben
 * einen anderen Bildausschnitt, einen anderen sicheren Bereich für die Untertitel und eine andere
 * Schriftgrösse. Das ist eine echte zweite Fassung, und die entsteht hier.
 */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;

  let body: { aspect?: unknown; destination?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (!istAspect(body.aspect)) {
    return Response.json({ error: `Format muss eines von ${ASPEKTE.join(", ")} sein.` }, { status: 400 });
  }
  const aspect = body.aspect;
  /* Ohne ausdrückliche Wahl die Plattform, für die dieses Format der Standard ist. */
  const destination: Platform = istPlattform(body.destination) ? body.destination : plattformFuerFormat(aspect);

  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  if (!clip.candidate_id) {
    return Response.json({ error: "Zu diesem Clip gibt es keinen Moment, aus dem eine zweite Fassung entstehen könnte." }, { status: 409 });
  }

  const neu = await repo.createClipFassung(clipId, aspect, destination);
  if (!neu) {
    return Response.json(
      { error: `Für diesen Moment gibt es schon eine Fassung in ${ASPECT_LABELS[aspect]}. Eine zweite wäre dieselbe Datei.`, code: "fassung_vorhanden" },
      { status: 409 },
    );
  }

  const signaled = await signalApprove({ sourceId: id, candidateId: clip.candidate_id, destination: `${destination}:${neu.id}` });
  await repo.audit({
    action: "clip.fassung_created",
    entity: "clips",
    entity_id: neu.id,
    payload: { source_id: id, vorlage: clipId, candidate_id: clip.candidate_id, aspect, destination, signaled },
  });
  return Response.json({
    ok: true,
    clip: neu,
    signaled,
    message: `Fassung ${formatSatz(aspect)} für ${PLATFORM_LABELS[destination]} wird geclippt.`,
  });
}
