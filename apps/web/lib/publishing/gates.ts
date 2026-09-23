import type { Candidate, Clip, GuestApproval, Plan, Workspace } from "@/lib/repo/types";

/* Gates vor dem Anlegen einer Publikation (PHASE5.md): Clip rendered, Kandidat accepted, Gast-Freigabe approved
 * falls verlangt, AVV angenommen, Plan features.publishing. Deutsche Gründe, leer wenn alles offen ist.
 * Ohne Server-Abhängigkeiten (Client zeigt dieselben Gründe). */

export interface PublishGateInput {
  clip: Pick<Clip, "status" | "guest_approval_required" | "candidate_id">;
  candidate: Pick<Candidate, "human_verdict"> | null;
  approval: Pick<GuestApproval, "decision"> | null | undefined;
  workspace: Pick<Workspace, "dpa_signed_at"> | null;
  plan: Pick<Plan, "features" | "name"> | null;
}

export interface GateReason {
  code: "clip_not_rendered" | "candidate_not_accepted" | "guest_approval" | "dpa" | "plan";
  message: string;
  href?: string;
}

export function publishGates(input: PublishGateInput): GateReason[] {
  const out: GateReason[] = [];
  if (input.clip.status !== "rendered" && input.clip.status !== "exported") {
    out.push({ code: "clip_not_rendered", message: "Der Clip ist noch nicht fertig." });
  }
  if (!input.candidate || input.candidate.human_verdict !== "accepted") {
    out.push({ code: "candidate_not_accepted", message: "Du hast diesen Clip noch nicht genommen." });
  }
  if (input.clip.guest_approval_required && input.approval?.decision !== "approved") {
    out.push({ code: "guest_approval", message: "Die Person, die du gefragt hast, hat noch nicht geantwortet." });
  }
  if (!input.workspace?.dpa_signed_at) {
    out.push({ code: "dpa", message: "Ein Vertrag fehlt noch.", href: "/rechtliches/avv" });
  }
  if (!input.plan?.features?.publishing) {
    out.push({ code: "plan", message: `Im Tarif ${input.plan?.name ?? "Starter"} kannst du nicht direkt posten. Herunterladen geht aber.`, href: "/einstellungen/abrechnung" });
  }
  return out;
}
