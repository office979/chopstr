import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { signalApprove } from "@/lib/temporal";
import type { Candidate, Clip, Platform } from "@/lib/repo/types";
import { PLATFORMS, isPlatform } from "@/lib/clips/labels";
import { candidateFeatures, recordDecision } from "@/lib/decision-log";
import { EDITED_ERROR, acceptancePlatform, unchosenAutoDrafts } from "@/lib/clips/acceptance";
import { OVERRIDE_REASON_PREFIX, editorialFlagReason, reviewState } from "@/lib/candidates/review";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; cid: string }> };

interface VerdictBody {
  verdict?: unknown;
  reason?: unknown;
  platforms?: unknown;
  /* Hochformat-Schalter aus der Oberfläche. Fehlt er, gilt der Standard: Hochformat an. */
  keep_source_aspect?: unknown;
  /* Pflicht beim Annehmen eines nicht freigabefähigen Kandidaten: warum trotz Befund. */
  override_reason?: unknown;
  /* Nur bei revise: die Stelle im fertigen Clip, um die es geht (Sekunden). */
  at_s?: unknown;
}

/* Obergrenze für at_s: kein Clip ist länger als ein paar Minuten, eine größere Zahl ist ein Fehler. */
const MAX_AT_S = 3600;

/* POST: menschliches Urteil. accepted -> Clips je Zielplattform anlegen (packages/schema/CLIPS.md), Signal
 * approve(candidate_id, platform) je Clip an project-<source_id>; rejected -> Grund ist Pflicht (Lernsignal);
 * revise („Flag an Redaktion“) -> Kommentar ist Pflicht, optional die Sekunde im Clip. Jede Aktion
 * schreibt audit_log.
 *
 * revise: Die Datenbank kennt kein Urteil `revise` (Migration 0001), deshalb wird das Urteil auf offen
 * gesetzt und der Grund mit EDITORIAL_FLAG_PREFIX gespeichert. Offen heisst: nicht veröffentlichbar,
 * bis jemand annimmt (lib/publishing/gates.ts). Im Decision Log steht `revise` ausdrücklich.
 *
 * Ein Kandidat der Klasse „nicht freigabefähig“ (Regel 14, lib/candidates/review.ts) lässt sich nur
 * mit override_reason annehmen; die Begründung steht im Urteil und im Audit
 * (docs/decisions/051-kandidatenliste-freigabe.md). */
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
  if (verdict !== "accepted" && verdict !== "rejected" && verdict !== "revise") {
    return Response.json({ error: "verdict muss accepted, rejected oder revise sein" }, { status: 400 });
  }
  const reason = typeof body.reason === "string" ? body.reason.trim().slice(0, 500) : "";
  if (verdict === "rejected" && !reason) {
    return Response.json({ error: "Beim Ablehnen ist ein kurzer Grund Pflicht" }, { status: 400 });
  }
  if (verdict === "revise" && !reason) {
    return Response.json({ error: "Für die Redaktion ist ein kurzer Kommentar Pflicht" }, { status: 400 });
  }
  let atS: number | null = null;
  if (verdict === "revise" && body.at_s != null && body.at_s !== "") {
    const n = Number(body.at_s);
    if (!Number.isFinite(n) || n < 0 || n > MAX_AT_S) {
      return Response.json({ error: "Die Sekunde muss eine Zahl ab 0 sein" }, { status: 400 });
    }
    atS = Math.round(n * 10) / 10;
  }
  const overrideReason = typeof body.override_reason === "string" ? body.override_reason.trim().slice(0, 500) : "";

  const existing = await repo.getCandidate(cid);
  if (!existing || existing.source_id !== id) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });
  if (existing.human_verdict === "edited") {
    return Response.json({ error: EDITED_ERROR }, { status: 409 });
  }

  if (verdict === "revise") return flagForEditors(id, cid, source.brand_profile_id, existing, reason, atS);

  /* Nicht freigabefähig verschwindet nicht durch Anklicken (Regel 14): Annehmen nur mit Begründung. */
  const review = reviewState(existing);
  if (verdict === "accepted" && review.state === "blocked" && !overrideReason) {
    return Response.json(
      {
        error: "Dieser Vorschlag ist nicht freigabefähig. Annehmen geht nur mit einer Begründung, warum trotz Befund.",
        code: "override_reason_required",
      },
      { status: 400 },
    );
  }
  const overridden = verdict === "accepted" && review.state === "blocked";
  const storedReason = overridden ? `${OVERRIDE_REASON_PREFIX}${overrideReason}` : reason;

  /* Ziele: genau die gewählten. Die Standard-Plattform des Markenprofils ist in der Oberfläche
   * vorausgewählt, aber abwählbar; sie wird hier nicht mehr erzwungen. Ohne Angabe gilt die
   * Plattform eines schon vorhandenen Clips des Kandidaten (der Entwurf der Analyse wird so
   * wiederverwendet), sonst Markenprofil, Briefing, reels wie im Worker (lib/clips/acceptance.ts). */
  let platforms: Platform[];
  if (Array.isArray(body.platforms)) {
    const requested = body.platforms.filter(isPlatform);
    if (requested.length === 0) {
      return Response.json({ error: "Mindestens ein Ziel wählen" }, { status: 400 });
    }
    platforms = PLATFORMS.filter((p) => requested.includes(p));
  } else {
    const brand = source.brand_profile_id ? await repo.getBrandProfile(source.brand_profile_id) : null;
    platforms = [acceptancePlatform(cid, await repo.listClips(id), brand, source)];
  }

  const keepSourceAspect = body.keep_source_aspect === true;

  let clips: Clip[] = [];
  if (verdict === "accepted") {
    try {
      clips = await repo.createClips(cid, platforms, { keepSourceAspect });
    } catch (error) {
      return Response.json({ error: error instanceof Error ? error.message : "Clips konnten nicht angelegt werden" }, { status: 500 });
    }
    /* Ausdrücklich gewählte Plattformen: Automatik-Entwürfe auf anderen Plattformen fallen weg, bevor
     * das Urteil sie für den lokalen Worker renderbar macht. */
    if (Array.isArray(body.platforms)) {
      for (const draft of unchosenAutoDrafts(cid, await repo.listClips(id), platforms)) {
        await repo.updateClip(draft.id, { status: "deleted" });
        await repo.audit({
          action: "clip.auto_draft_dropped",
          entity: "clips",
          entity_id: draft.id,
          payload: { source_id: id, candidate_id: cid, platform: draft.platform, chosen: platforms },
        });
      }
    }
  }

  const candidate = await repo.setCandidateVerdict(cid, verdict, storedReason || undefined);
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
    chosen: {
      verdict,
      reason: storedReason || null,
      clip_ids: clips.map((c) => c.id),
      ...(overridden ? { override_reason: overrideReason, review_state: "blocked" } : {}),
    },
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
      reason: storedReason || null,
      platforms: verdict === "accepted" ? clips.map((c) => c.platform) : null,
      clip_ids: clips.map((c) => c.id),
      signaled,
      ...(overridden
        ? { override_reason: overrideReason, review_state: "blocked", review_reasons: review.reasons.map((r) => r.code) }
        : {}),
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

/* Flag an Redaktion: Urteil offen, Grund mit Präfix, Audit `candidate.flagged`, Decision Log mit
 * `revise`. Es entsteht kein Clip und kein Render. */
async function flagForEditors(
  sourceId: string,
  cid: string,
  brandProfileId: string | null,
  existing: Candidate,
  comment: string,
  atS: number | null,
): Promise<Response> {
  const repo = getRepo();
  const reason = editorialFlagReason(comment, atS);
  const candidate = await repo.setCandidateVerdict(cid, null, reason);
  if (!candidate) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });
  await recordDecision({
    decision_type: "candidate_verdict",
    actor_type: "user",
    brand_profile_id: brandProfileId,
    source_id: sourceId,
    candidate_id: cid,
    features: { ...candidateFeatures(candidate), platforms: [] },
    alternatives: [{ verdict: "accepted" }, { verdict: "rejected" }],
    chosen: { verdict: "revise", reason, comment, at_s: atS, previous_verdict: existing.human_verdict },
  });
  await repo.audit({
    action: "candidate.flagged",
    entity: "candidates",
    entity_id: cid,
    payload: {
      source_id: sourceId,
      version: candidate.version,
      comment,
      at_s: atS,
      reason,
      previous_verdict: existing.human_verdict,
    },
  });
  return Response.json({ ok: true, candidate, clips: [], platforms: [], signaled: [], demo: repo.kind === "demo" });
}
