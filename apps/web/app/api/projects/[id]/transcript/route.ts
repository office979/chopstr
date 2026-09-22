import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole, requireApiSession } from "@/lib/auth/guard";
import type { CorrectionInput, TranscriptWord } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* GET: aktuelle Transkript-Version */
export async function GET(_request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });
  const transcript = await repo.getCurrentTranscript(id);
  if (!transcript) return Response.json({ error: "Kein Transkript vorhanden" }, { status: 404 });
  return Response.json(transcript);
}

interface SaveBody {
  words?: unknown;
  corrections?: unknown;
  speaker_names?: unknown;
}

function isWord(w: unknown): w is TranscriptWord {
  if (!w || typeof w !== "object") return false;
  const o = w as Record<string, unknown>;
  return (
    typeof o.text === "string" &&
    typeof o.start === "number" &&
    typeof o.end === "number" &&
    typeof o.prob === "number" &&
    typeof o.speaker === "string"
  );
}

function isCorrection(c: unknown): c is CorrectionInput {
  if (!c || typeof c !== "object") return false;
  const o = c as Record<string, unknown>;
  return (
    typeof o.word_index === "number" &&
    typeof o.old_text === "string" &&
    typeof o.new_text === "string" &&
    typeof o.add_to_vocab === "boolean"
  );
}

/* POST: neue transcript_versions-Zeile (origin manual), transcript_corrections, optional Wörter ins Marken-Wörterbuch */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("transcript.edit");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });

  let body: SaveBody;
  try {
    body = (await request.json()) as SaveBody;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  if (!Array.isArray(body.words) || !body.words.every(isWord) || body.words.length === 0) {
    return Response.json({ error: "words fehlt oder ist ungültig" }, { status: 400 });
  }
  const corrections = Array.isArray(body.corrections) ? body.corrections.filter(isCorrection) : [];
  const speakerNames: Record<string, string> = {};
  if (body.speaker_names && typeof body.speaker_names === "object") {
    for (const [k, v] of Object.entries(body.speaker_names as Record<string, unknown>)) {
      if (typeof v === "string" && v.trim()) speakerNames[k] = v.trim().slice(0, 80);
    }
  }

  const words: TranscriptWord[] = body.words.map((w) => ({
    text: w.text,
    start: w.start,
    end: w.end,
    prob: w.prob,
    speaker: w.speaker,
    filler: w.filler ?? null,
    negation: Boolean(w.negation),
    sentence_idx: typeof w.sentence_idx === "number" ? w.sentence_idx : 0,
  }));

  const version = await repo.saveTranscript(id, { words, corrections, speaker_names: speakerNames });

  const vocab = corrections
    .filter((c) => c.add_to_vocab)
    .map((c) => c.new_text.replace(/[.,;:!?]+$/, "").trim())
    .filter(Boolean);
  if (vocab.length > 0 && source.brand_profile_id) {
    await repo.addBrandVocab(source.brand_profile_id, vocab);
  }

  await repo.audit({
    action: "transcript.corrected",
    entity: "transcript_versions",
    entity_id: version.id,
    payload: {
      source_id: id,
      version: version.version,
      corrections: corrections.length,
      vocab_added: vocab,
      speakers_renamed: Object.keys(speakerNames).length,
    },
  });

  return Response.json({ ok: true, version, vocab_added: vocab });
}
