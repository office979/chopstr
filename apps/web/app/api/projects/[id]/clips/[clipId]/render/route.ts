import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { signalApprove } from "@/lib/temporal";
import { renderAcceptance } from "@/lib/clips/acceptance";
import { candidateFeatures, recordDecision } from "@/lib/decision-log";
import type { Candidate } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* POST: Render (erneut) anstoßen. Signal approve(candidate_id, "platform:clip_id") an project-<source_id>;
 * ohne Temporal wird der Clip `draft` und der lokale Worker holt ihn ab; im Demo-Modus startet das Repository die Simulation.
 *
 * Kandidat ohne Urteil (von der Automatik zurückgehalten, lib/clips/acceptance.ts): der Klick ist die
 * menschliche Annahme. Zuerst das Urteil (bedingt, accepted, verdict_by = aktueller Nutzer, Audit und
 * Decision Log wie in der Verdict-Route), danach Signal oder Warteschlange; der lokale Worker findet
 * den Clip erst mit angenommenem Kandidaten. clip.render dürfen nur Rollen, die auch beurteilen dürfen
 * (Test in tests/clip-acceptance.test.ts). Abgelehnter oder ersetzter Kandidat: 409 mit Fehlertext,
 * es wird nichts gerendert. */
export async function POST(_request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  if (clip.status === "rendering") {
    return Response.json({ error: "Dieser Clip wird gerade gerendert" }, { status: 409 });
  }
  if (!clip.candidate_id) {
    return Response.json({ error: "Clip ohne Kandidat kann nicht neu gerendert werden" }, { status: 409 });
  }

  const candidateId = clip.candidate_id;
  const acceptance = renderAcceptance(await repo.getCandidate(candidateId));
  if (acceptance.kind === "refuse") return Response.json({ error: acceptance.error }, { status: 409 });
  let accepted: Candidate | null = null;
  if (acceptance.kind === "accept") {
    /* Bedingt: nur solange kein Urteil vorliegt. Zwei gleichzeitige Klicks oder ein Urteil in der
     * Prüfliste dazwischen ergeben genau eine Annahme. */
    accepted = await repo.setCandidateVerdictIfOpen(candidateId, "accepted", acceptance.reason);
    if (accepted) {
      await repo.audit({
        action: "candidate.accepted",
        entity: "candidates",
        entity_id: candidateId,
        payload: {
          source_id: id,
          version: accepted.version,
          total: accepted.total,
          gate_passed: accepted.gate_passed,
          reason: acceptance.reason,
          platforms: [clip.platform],
          clip_ids: [clipId],
          via: "render",
        },
      });
      const source = await repo.getSource(id);
      await recordDecision({
        decision_type: "candidate_verdict",
        actor_type: "user",
        brand_profile_id: source?.brand_profile_id ?? null,
        source_id: id,
        candidate_id: candidateId,
        features: { ...candidateFeatures(accepted), platforms: [clip.platform] },
        alternatives: [{ verdict: "rejected" }],
        chosen: { verdict: "accepted", reason: acceptance.reason, clip_ids: [clipId], via: "render" },
      });
    } else {
      /* Inzwischen hat jemand anders geurteilt: abgelehnt oder ersetzt heißt 409, angenommen heißt
       * rendern ohne zweiten Eintrag im Decision Log. */
      const current = await repo.getCandidate(candidateId);
      if (!current) return Response.json({ error: "Kandidat nicht gefunden" }, { status: 404 });
      const again = renderAcceptance(current);
      if (again.kind === "refuse") return Response.json({ error: again.error }, { status: 409 });
      if (again.kind === "accept") {
        return Response.json({ error: "Das Urteil konnte nicht gespeichert werden, bitte erneut versuchen" }, { status: 409 });
      }
    }
  }

  /* Ziel "plattform:clip_id": der Worker rendert genau diesen Clip (wichtig für Hook-A/B, Variante B hat dieselbe Plattform) */
  const signaled = await signalApprove({ sourceId: id, candidateId, destination: `${clip.platform}:${clipId}` });
  /* Ohne Signal (kein TEMPORAL_ADDRESS oder fehlgeschlagen) geht der Clip als `draft` in die Warteschlange des lokalen Workers */
  const updated = (await repo.requestClipRender(clipId, signaled)) ?? clip;
  await repo.audit({
    action: "clip.render_requested",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, candidate_id: candidateId, platform: clip.platform, previous_status: clip.status, signaled, accepted: Boolean(accepted) },
  });
  return Response.json({ ok: true, clip: updated, signaled, accepted: Boolean(accepted), demo: repo.kind === "demo" });
}
