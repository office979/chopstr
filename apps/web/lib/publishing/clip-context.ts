import "server-only";
import { getRepo } from "@/lib/repo";
import { getQuota } from "@/lib/billing/quota";
import { latestByClip } from "@/lib/guest/approval";
import { getPublishingRepo } from "@/lib/repo/publishing";
import type { Candidate, Clip, GuestApproval, HookVersion, Plan, Source, Workspace } from "@/lib/repo/types";
import type { ClipExtras } from "@/lib/repo/types-publishing";
import { publishGates, type GateReason } from "./gates";

/* Clip mit allem, was Gates, Decision Log und Serien-Prüfung brauchen: Quelle, Kandidat, jüngste Gast-Freigabe,
 * aktuelle Hook-Version, Workspace, Plan und Zusatzspalten. */
export interface ClipContext {
  clip: Clip;
  extras: ClipExtras;
  source: Source;
  candidate: Candidate | null;
  approval: GuestApproval | null;
  hook: HookVersion | null;
  workspace: Workspace;
  plan: Plan | null;
  gates: GateReason[];
}

export async function loadClipContext(sourceId: string, clipId: string): Promise<ClipContext | null> {
  const repo = getRepo();
  const [source, clip] = await Promise.all([repo.getSource(sourceId), repo.getClip(clipId)]);
  if (!source || !clip || clip.source_id !== sourceId) return null;
  const [candidate, approvals, hook, workspace, quota, extras] = await Promise.all([
    clip.candidate_id ? repo.getCandidate(clip.candidate_id) : Promise.resolve(null),
    repo.listGuestApprovals(sourceId),
    repo.getCurrentHook(clipId),
    repo.getWorkspace(),
    getQuota(repo),
    getPublishingRepo().getClipExtras([clipId]),
  ]);
  const approval = latestByClip(approvals).get(clipId) ?? null;
  return {
    clip,
    extras: extras[0] ?? { id: clipId, experiment_id: null, variant: null, series_id: null, series_index: null, reframe_override: null },
    source,
    candidate,
    approval,
    hook,
    workspace,
    plan: quota.plan,
    gates: publishGates({ clip, candidate, approval, workspace, plan: quota.plan }),
  };
}
