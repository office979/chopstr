/* Die Sperrgründe für das Veröffentlichen, in der Form, die die Schnittstelle schon kennt.
 *
 * Gerechnet wird hier nichts mehr. Die Regeln stehen in packages/schema/ausgabe_regeln_v1.json und
 * werden von lib/clips/ausgabe.ts ausgewertet, für Download und Veröffentlichung gemeinsam. Dass
 * es beides gab, war der Fehler: die alte Fassung dieser Datei prüfte fünf Dinge, von denen eines
 * gar nicht prüfbar war.
 *
 * Das Urteil am Kandidaten (`candidate.human_verdict === "accepted"`) prüft verdictReason. Früher
 * galt es als immer erfüllt, weil ein Clip nur durch das Annehmen entstand. Das stimmt nicht mehr:
 * die Analyse legt für jeden Kandidaten einen Entwurf an, auch für die, die sie wegen Humor, eines
 * sensiblen Themas oder einer freigaberelevanten Behauptung zurückhält (docs/ENTSCHEIDUNGEN.md P27).
 * Deren Kandidat hat kein Urteil, bis ein Mensch ihn annimmt. Die Oberfläche (clip-context.ts), die
 * Schnittstelle (/api/v1/clips/{id}/publish) und der Worker (publish.check_gates) prüfen deshalb
 * dieselbe Bedingung mit demselben Text. Daneben bleibt die Frage aus den Ausgaberegeln: hat ein
 * Mensch diesen Clip freigegeben?
 */

import { ausgabeSatz, type Ausgabe, type AusgabeCode } from "@/lib/clips/ausgabe";
import type { Candidate } from "@/lib/repo/types";

export type GateCode = AusgabeCode | "candidate_missing" | "candidate_not_accepted";

export interface GateReason {
  code: GateCode;
  message: string;
  href?: string;
}

export function gateReasons(a: Ausgabe): GateReason[] {
  return a.gruende.map((g) => ({ code: g.code, message: ausgabeSatz(g), ...(g.href ? { href: g.href } : {}) }));
}

/* Urteil im Sperrgrund, gleichlautend mit VERDICT_LABELS in workers/chopstr_worker/activities/publish.py. */
const VERDICT_LABELS: Record<string, string> = { rejected: "abgelehnt", edited: "durch eine neue Version ersetzt" };

/* Sperrgrund aus dem Urteil am Kandidaten, oder null, wenn er angenommen ist. Gilt nur für das
 * Veröffentlichen; das Nachtragen eines selbst geposteten Clips (Zweck „eintragen“) prüft es nicht.
 * Ein ersetzter Kandidat (edited) sperrt also auch in der Oberfläche. Texte wie im Worker
 * (publish.check_gates). */
export function verdictReason(
  candidateId: string | null,
  candidate: Pick<Candidate, "human_verdict"> | null,
): GateReason | null {
  if (!candidateId) return { code: "candidate_missing", message: "Clip hat keinen Kandidaten" };
  const verdict = candidate?.human_verdict ?? null;
  if (verdict === "accepted") return null;
  const label = verdict == null ? "offen" : (VERDICT_LABELS[verdict] ?? verdict);
  return { code: "candidate_not_accepted", message: `Kandidat ist nicht angenommen (Urteil ${label})` };
}
