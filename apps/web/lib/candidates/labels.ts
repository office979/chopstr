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

/* Der ausführliche Satz je Risikohinweis, als Erklärung neben dem Wort. */
export const RISK_LABELS: Record<RiskFlag, string> = {
  humor: "Ist Witz, bitte selbst prüfen",
  sensitive_topic: "Heikles Thema",
  claim: "Enthält eine Behauptung. Stimmt sie?",
  ad: "Muss als Werbung gekennzeichnet werden",
  heuristic_only: "Ohne KI gefunden",
};

/* Der Risikohinweis als ein Wort, für die Kandidatenliste (lib/candidates/review.ts). */
export const RISK_WORDS: Record<RiskFlag, string> = {
  humor: "Humor",
  sensitive_topic: "Heikles Thema",
  claim: "Behauptung",
  ad: "Werbung",
  heuristic_only: "Ohne Sprachmodell",
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

/* Hier standen formatTotal und qualityWord: ohne Aufrufer und mit einer Skala bis 10, die `total`
 * nie hatte. Die eine Qualitätszahl rechnet jetzt lib/candidates/review.ts (qualityScore) auf der
 * Skala der Richtlinie (docs/decisions/052-eine-qualitaetszahl.md). */
