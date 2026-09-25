import "server-only";
import { getRepo } from "@/lib/repo";
import { getQuota } from "@/lib/billing/quota";
import { freigabeVeraltet, latestByClip } from "@/lib/guest/approval";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { pruefstand, type Pruefstand } from "@/lib/clips/pruefstand";
import { stilPruefen } from "@/lib/clips/caption-style";
import { aspectForSource } from "@/lib/clips/presets";
import { ausgabe, type Ausgabe } from "@/lib/clips/ausgabe";
import type { Candidate, Clip, GuestApproval, HookVersion, Plan, Source, Workspace } from "@/lib/repo/types";
import type { ClipExtras } from "@/lib/repo/types-publishing";
import { gateReasons, type GateReason } from "./gates";

/* Clip mit allem, was Gates, Decision Log und Serien-Prüfung brauchen: Quelle, Kandidat, jüngste Gast-Freigabe,
 * aktuelle Hook-Version, Workspace, Plan und Zusatzspalten.
 *
 * Seit der gemeinsamen Ausgabeentscheidung liegt hier auch die Antwort auf die zwei Fragen, die
 * beim Hinausgeben zählen: darf diese Fassung heruntergeladen werden, darf sie veröffentlicht
 * werden. Beide kommen aus derselben Rechnung, damit die Oberfläche und die Routen nicht mehr
 * getrennt zu verschiedenen Ergebnissen kommen können. */
export interface ClipContext {
  clip: Clip;
  extras: ClipExtras;
  source: Source;
  candidate: Candidate | null;
  approval: GuestApproval | null;
  hook: HookVersion | null;
  workspace: Workspace;
  plan: Plan | null;
  stand: Pruefstand;
  herunterladen: Ausgabe;
  veroeffentlichen: Ausgabe;
  /* Nachtragen, dass jemand selbst gepostet hat. Siehe lib/clips/ausgabe.ts, Zweck „eintragen". */
  eintragen: Ausgabe;
  /* Dieselbe Antwort in der Form, die die Schnittstelle seit Phase 5 liefert. */
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
  const extra: ClipExtras = extras[0] ?? {
    id: clipId,
    experiment_id: null,
    variant: null,
    series_id: null,
    series_index: null,
    reframe_override: null,
    caption_style: {},
    zeitmarken: [],
  };

  /* Derselbe Prüfstand wie in der Clip-Liste, mit denselben Eingaben. */
  const gespeicherterStil = stilPruefen(extra.caption_style);
  const stand = pruefstand({
    clip,
    freigabe: approval,
    bearbeitet:
      Object.keys(gespeicherterStil).length > 0 || (clip.zeitmarken?.length ?? 0) > 0 || clip.composition.length > 1,
    kandidat: candidate,
    quellformatAbweichend: aspectForSource(source.width, source.height) !== clip.aspect,
  });

  const eingabe = {
    stand,
    technik: clip.export_checks,
    gastOffen: clip.guest_approval_required && approval?.decision == null,
    gastNein: clip.guest_approval_required && approval?.decision != null && approval.decision !== "approved",
    gastVeraltet: freigabeVeraltet(approval ?? undefined, clip.updated_at),
  };
  const herunterladen = ausgabe("herunterladen", eingabe);
  const eintragen = ausgabe("eintragen", eingabe);
  const veroeffentlichen = ausgabe("veroeffentlichen", {
    ...eingabe,
    vertragUnterschrieben: Boolean(workspace.dpa_signed_at),
    tarifDarfPosten: Boolean(quota.plan?.features?.publishing),
  });

  return {
    clip,
    extras: extra,
    source,
    candidate,
    approval,
    hook,
    workspace,
    plan: quota.plan,
    stand,
    herunterladen,
    veroeffentlichen,
    eintragen,
    gates: gateReasons(veroeffentlichen),
  };
}
