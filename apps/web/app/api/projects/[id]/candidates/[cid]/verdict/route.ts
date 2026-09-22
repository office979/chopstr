import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { signalApprove } from "@/lib/temporal";
import type { Clip, Platform } from "@/lib/repo/types";
import { PLATFORMS, isPlatform } from "@/lib/clips/labels";
import { candidateFeatures, recordDecision } from "@/lib/decision-log";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; cid: string }> };

interface VerdictBody {
  verdict?: unknown;
  reason?: unknown;
  platforms?: unknown;
  /* Hochformat-Schalter aus der Oberfläche. Fehlt er, gilt der Standard: Hochformat an. */
  keep_source_aspect?: unknown;
}

/* POST: menschliches Urteil. accepted -> Clips je Zielplattform anlegen (packages/schema/CLIPS.md), Signal
 * approve(candidate_id, platform) je Clip an project-<source_id>; rejected -> Grund ist Pflicht (Lernsignal).
 * Jede Aktion schreibt audit_log. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("candidate.verdict");
  if (auth instanceof Response) return auth;
  const { id, cid } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });

  let body: VerdictBody;
  try {
    body = (await request.json()) as VerdictBody;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const verdict = body.verdict;
  if (verdict !== "accepted" && verdict !== "rejected") {
    return Response.json({ error: "verdict muss accepted oder rejected sein" }, { status: 400 });
  }
  const reason = typeof body.reason === "string" ? body.reason.trim().slice(0, 500) : "";
  if (verdict === "rejected" && !reason) {
    return Response.json({ error: "Beim Ablehnen ist ein kurzer Grund Pflicht" }, { status: 400 });
  }

  const existing = await repo.getCandidate(cid);
  if (!existing || existing.source_id !== id) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });
  if (existing.human_verdict === "edited") {
    return Response.json({ error: "Dieser Kandidat wurde durch eine neue Version ersetzt" }, { status: 409 });
  }

  /* Ziele: Standard alle vier; die Standard-Plattform des Markenprofils ist immer dabei */
  const brand = source.brand_profile_id ? await repo.getBrandProfile(source.brand_profile_id) : null;
  const defaultPlatform: Platform = brand?.default_platform ?? source.brief.platform ?? "linkedin";
  let platforms: Platform[] = PLATFORMS;
  if (Array.isArray(body.platforms)) {
    const requested = body.platforms.filter(isPlatform);
    if (requested.length === 0) {
      return Response.json({ error: "Mindestens ein Ziel wählen" }, { status: 400 });
    }
    platforms = PLATFORMS.filter((p) => requested.includes(p) || p === defaultPlatform);
  }

  const keepSourceAspect = body.keep_source_aspect === true;

  let clips: Clip[] = [];
  if (verdict === "accepted") {
    try {
      clips = await repo.createClips(cid, platforms, { keepSourceAspect });
    } catch (error) {
      return Response.json({ error: error instanceof Error ? error.message : "Clips konnten nicht angelegt werden" }, { status: 500 });
    }
  }

  const candidate = await repo.setCandidateVerdict(cid, verdict, reason || undefined);
  if (!candidate) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });

  /* Decision Log (A3): menschliches Urteil mit Rubrik-Merkmalen, Lernsignal für learning.py */
  await recordDecision({
    decision_type: "candidate_verdict",
    actor_type: "user",
    brand_profile_id: source.brand_profile_id,
    source_id: id,
    candidate_id: cid,
    features: { ...candidateFeatures(candidate), platforms: verdict === "accepted" ? clips.map((c) => c.platform) : [] },
    alternatives: [{ verdict: verdict === "accepted" ? "rejected" : "accepted" }],
    chosen: { verdict, reason: reason || null, clip_ids: clips.map((c) => c.id) },
  });

  const signaled: Platform[] = [];
  if (verdict === "accepted") {
    for (const clip of clips) {
      await repo.audit({
        action: "clip.created",
        entity: "clips",
        entity_id: clip.id,
        payload: { source_id: id, candidate_id: cid, platform: clip.platform, aspect: clip.aspect, ad_label: clip.ad_label },
      });
      const ok = await signalApprove({ sourceId: id, candidateId: cid, destination: clip.platform });
      if (ok) signaled.push(clip.platform);
    }
  }

  await repo.audit({
    action: verdict === "accepted" ? "candidate.accepted" : "candidate.rejected",
    entity: "candidates",
    entity_id: cid,
    payload: {
      source_id: id,
      version: candidate.version,
      total: candidate.total,
      gate_passed: candidate.gate_passed,
      reason: reason || null,
      platforms: verdict === "accepted" ? clips.map((c) => c.platform) : null,
      clip_ids: clips.map((c) => c.id),
      signaled,
    },
  });

  return Response.json({
    ok: true,
    candidate,
    clips,
    platforms: clips.map((c) => c.platform),
    signaled,
    demo: repo.kind === "demo",
  });
}
