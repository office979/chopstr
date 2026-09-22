import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { TITLE_CARD_MAX_WORDS, titleCardWords } from "@/lib/candidates/revise";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; cid: string }> };

interface ReviseBody {
  first_sent?: unknown;
  last_sent?: unknown;
  title_card?: unknown;
}

/* POST: Verlängern, Kürzen oder Titelkarte. Legt eine neue Kandidaten-Version an (version + 1),
 * die alte Zeile bekommt human_verdict = 'edited'. Gates werden deterministisch neu berechnet. */
export async function POST(request: NextRequest, { params }: Params) {
  const { id, cid } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });

  let body: ReviseBody;
  try {
    body = (await request.json()) as ReviseBody;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const existing = await repo.getCandidate(cid);
  if (!existing || existing.source_id !== id) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });
  if (existing.human_verdict === "edited") {
    return Response.json({ error: "Dieser Kandidat wurde bereits durch eine neue Version ersetzt" }, { status: 409 });
  }

  const first = typeof body.first_sent === "number" ? body.first_sent : existing.first_sent;
  const last = typeof body.last_sent === "number" ? body.last_sent : existing.last_sent;
  if (first == null || last == null || !Number.isInteger(first) || !Number.isInteger(last) || first < 0 || first > last) {
    return Response.json({ error: "first_sent und last_sent müssen gültige Satzindizes sein" }, { status: 400 });
  }

  let titleCard: string | undefined;
  if (body.title_card !== undefined) {
    if (typeof body.title_card !== "string") return Response.json({ error: "title_card muss Text sein" }, { status: 400 });
    const words = titleCardWords(body.title_card);
    if (words.length > TITLE_CARD_MAX_WORDS) {
      return Response.json({ error: `Titelkarte: höchstens ${TITLE_CARD_MAX_WORDS} Wörter` }, { status: 400 });
    }
    titleCard = words.join(" ").slice(0, 120);
  }

  let candidate;
  try {
    candidate = await repo.reviseCandidate(cid, { first_sent: first, last_sent: last, title_card: titleCard });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Anpassen fehlgeschlagen" }, { status: 400 });
  }
  if (!candidate) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });

  await repo.audit({
    action: "candidate.revised",
    entity: "candidates",
    entity_id: candidate.id,
    payload: {
      source_id: id,
      parent_id: cid,
      version: candidate.version,
      first_sent: candidate.first_sent,
      last_sent: candidate.last_sent,
      title_card: candidate.rubric.suggested_title_card || null,
      gate_passed: candidate.gate_passed,
    },
  });

  return Response.json({ ok: true, candidate });
}
