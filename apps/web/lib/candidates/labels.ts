import type { Candidate, CandidateStructure, HumanVerdict, RiskFlag, RubricKey } from "@/lib/repo/types";

/* Deutsche Labels für Struktur, Rubrik, Risiken und Urteile (nur Anzeige) */

export const STRUCTURE_LABELS: Record<CandidateStructure, string> = {
  payoff_first: "Payoff zuerst",
  tension_first: "Spannung zuerst",
  hook_build_payoff: "Hook, Aufbau, Payoff",
  decision_story: "Entscheidungsgeschichte",
  how_to_list: "Schrittfolge",
  loop: "Schleife",
};

export function structureLabel(s: CandidateStructure | null): string {
  return s ? STRUCTURE_LABELS[s] : "Struktur offen";
}

export const RUBRIC_ORDER: RubricKey[] = ["hook", "payoff", "specificity", "tension", "audience_fit"];

export const RUBRIC_LABELS: Record<RubricKey, string> = {
  hook: "Hook",
  payoff: "Payoff",
  specificity: "Konkretheit",
  tension: "Spannung",
  audience_fit: "Zielgruppe",
};

export const VERDICT_LABELS: Record<HumanVerdict, string> = {
  accepted: "Angenommen",
  rejected: "Abgelehnt",
  edited: "Bearbeitet",
};

export interface Warning {
  key: string;
  label: string;
}

const RISK_LABELS: Record<RiskFlag, string> = {
  humor: "Humor: Mensch prüft",
  sensitive_topic: "Sensibles Thema",
  claim: "Behauptung prüfen",
  ad: "Werbung kennzeichnen",
  heuristic_only: "Heuristik ohne Sprachmodell",
};

export function formatSeconds(s: number): string {
  return `${s.toLocaleString("de-AT", { maximumFractionDigits: s < 10 ? 1 : 0 })} s`;
}

/* Orange Chips: alles, was ein Mensch prüfen muss */
export function warningsOf(c: Candidate): Warning[] {
  const out: Warning[] = [];
  c.story_graph_flags.forEach((f, i) => {
    out.push({
      key: `flag-${i}`,
      label: f.confirmed === null ? `Mögliche Relativierung ${formatSeconds(f.seconds_after)} später` : `Relativierung ${formatSeconds(f.seconds_after)} später`,
    });
  });
  for (const r of c.risk_flags) {
    if (RISK_LABELS[r]) out.push({ key: r, label: RISK_LABELS[r] });
  }
  return out;
}

export function formatTotal(total: number | null): string {
  if (total == null) return "offen";
  return total.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}
