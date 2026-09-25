import type { Candidate, CandidateStructure, HumanVerdict, RiskFlag, RubricKey } from "@/lib/repo/types";

/* Deutsche Labels für Struktur, Rubrik, Risiken und Urteile (nur Anzeige) */

export const STRUCTURE_LABELS: Record<CandidateStructure, string> = {
  payoff_first: "Pointe am Anfang",
  tension_first: "Spannung am Anfang",
  hook_build_payoff: "Aufbau zur Pointe",
  decision_story: "Eine Entscheidung",
  how_to_list: "Schritt für Schritt",
  loop: "Endet wie es anfängt",
};

export function structureLabel(s: CandidateStructure | null): string {
  return s ? STRUCTURE_LABELS[s] : "Ohne klare Form";
}

export const RUBRIC_ORDER: RubricKey[] = ["hook", "payoff", "specificity", "tension", "audience_fit"];

export const RUBRIC_LABELS: Record<RubricKey, string> = {
  hook: "Anfang packt",
  payoff: "Pointe sitzt",
  specificity: "Konkret",
  tension: "Spannend",
  audience_fit: "Passt zur Zielgruppe",
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
  humor: "Ist Witz, bitte selbst prüfen",
  sensitive_topic: "Heikles Thema",
  claim: "Enthält eine Behauptung. Stimmt sie?",
  ad: "Muss als Werbung gekennzeichnet werden",
  heuristic_only: "Ohne KI gefunden",
};

export function formatSeconds(s: number): string {
  return `${s.toLocaleString("de-AT", { maximumFractionDigits: s < 10 ? 1 : 0 })} s`;
}

/* Orange Chips: alles, was ein Mensch prüfen muss */
export function warningsOf(c: Pick<Candidate, "risk_flags" | "story_graph_flags">): Warning[] {
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

/* Bewertung als Wort statt Zahl (docs/BEDIENKONZEPT.md, Abschnitt 5.5).
 * Die Zahl bleibt über formatTotal in „Details für Profis“ erreichbar. */
export function qualityWord(total: number | null): string {
  if (total == null) return "Noch nicht bewertet";
  if (total >= 8) return "Sehr stark";
  if (total >= 6) return "Stark";
  if (total >= 4) return "Geht so";
  return "Eher schwach";
}
