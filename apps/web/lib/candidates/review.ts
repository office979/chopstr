import type { Candidate, CandidateSegment, RiskFlag } from "@/lib/repo/types";
import { AUTO_HOLD_REASON_PREFIX, isHeldCandidate } from "@/lib/clips/acceptance";
import { RISK_LABELS, RISK_WORDS } from "@/lib/candidates/labels";
import { timecode } from "@/lib/clips/timecode";

/* Die Kandidatenliste als Freigabe (docs/decisions/051-kandidatenliste-freigabe.md).
 *
 * Alles, was die Karte über einen Kandidaten sagt, wird hier gerechnet, damit Karte, Sortierung und
 * Verdict-Route dieselbe Antwort geben: Ergebnisklasse (Regel 14 im Master-Prompt), Urteil mit
 * Grund (P27), Belegstellen (Regel 12), Flags als Wörter und genau eine Qualitätszahl
 * (docs/decisions/052-eine-qualitaetszahl.md). */

export type ReviewStateKind = "passed" | "uncertain" | "blocked";
export type ReviewOrigin = "rule" | "model" | "confirmed";

export interface SourceSpan {
  start_s: number;
  end_s: number;
}

export interface ReviewReason {
  code: string;
  text: string;
  source_span: SourceSpan | null;
  origin: ReviewOrigin;
}

export interface ReviewRepair {
  attempted: boolean;
  kind: string | null;
  result: string | null;
}

export interface ReviewState {
  state: ReviewStateKind;
  reasons: ReviewReason[];
  repair: ReviewRepair | null;
  /* true, wenn der Worker kein `rubric.review_state` geschrieben hat und die Klasse aus Gates,
   * Risikohinweisen und Haltegrund abgeleitet ist. */
  derived: boolean;
}

export const REVIEW_STATE_LABEL: Record<ReviewStateKind, string> = {
  passed: "Prüfungen bestanden",
  uncertain: "Bewertung unsicher",
  blocked: "Nicht freigabefähig",
};

export const REVIEW_STATE_ORDER: Record<ReviewStateKind, number> = { passed: 0, uncertain: 1, blocked: 2 };

/* Präfix des Urteils „Flag an Redaktion“. Die Datenbank kennt kein Urteil `revise`
 * (Migration 0001: accepted, rejected, edited); deshalb bleibt das Urteil offen und der Grund trägt
 * diesen Präfix, so wie der Haltegrund der Automatik (P27). */
export const EDITORIAL_FLAG_PREFIX = "an Redaktion: ";
/* Präfix der Begründung, wenn jemand einen nicht freigabefähigen Kandidaten trotzdem annimmt. */
export const OVERRIDE_REASON_PREFIX = "trotz Befund angenommen: ";

type ReviewInput = Pick<
  Candidate,
  "rubric" | "gate_passed" | "gates" | "risk_flags" | "story_graph_flags" | "verdict_reason" | "human_verdict" | "start_s" | "end_s"
>;

function finite(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/* Eine Spanne in einer der beiden Formen, die vorkommen: `{start_s, end_s}` (Vertrag Lane P3) oder
 * `{source_in, source_out}` (ClipCandidate, packages/schema/CLIP_CANDIDATE.md). */
export function readSpan(raw: unknown): SourceSpan | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const start = finite(r.start_s) ? r.start_s : finite(r.source_in) ? r.source_in : null;
  const end = finite(r.end_s) ? r.end_s : finite(r.source_out) ? r.source_out : null;
  if (start == null || end == null || end < start || start < 0) return null;
  return { start_s: start, end_s: end };
}

function readReason(raw: unknown): ReviewReason | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.text !== "string" || !r.text.trim()) return null;
  const origin: ReviewOrigin = r.origin === "model" || r.origin === "confirmed" ? r.origin : "rule";
  return {
    code: typeof r.code === "string" && r.code ? r.code : "unknown",
    text: r.text.trim(),
    source_span: readSpan(r.source_span),
    origin,
  };
}

function readRepair(raw: unknown): ReviewRepair | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  return {
    attempted: r.attempted === true,
    kind: typeof r.kind === "string" ? r.kind : null,
    result: typeof r.result === "string" ? r.result : null,
  };
}

/* Vom Worker geschrieben (Lane P3): `rubric.review_state`. Fehlt es oder ist es unlesbar, null. */
function storedReviewState(rubric: unknown): ReviewState | null {
  const raw = (rubric as Record<string, unknown> | null)?.review_state;
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (r.state !== "passed" && r.state !== "uncertain" && r.state !== "blocked") return null;
  const reasons = Array.isArray(r.reasons) ? r.reasons.map(readReason).filter((x): x is ReviewReason => x != null) : [];
  return { state: r.state, reasons, repair: readRepair(r.repair), derived: false };
}

/* Die Codes im Haltegrund der Automatik (activities/analyze.auto_accept_blockers) als Wörter. */
const HOLD_WORDS: Record<string, string> = {
  humor: "Humor",
  sensitive_topic: "heikles Thema",
  claim: "Behauptung, die geprüft werden muss",
  claim_unchecked: "Text ließ sich nicht prüfen",
};

/* Die Codes aus dem Haltegrund, ohne Präfix und ohne den Schluss „menschliche Prüfung nötig“. */
export function holdCodes(verdictReason: string | null): string[] {
  if (!verdictReason?.startsWith(AUTO_HOLD_REASON_PREFIX)) return [];
  return verdictReason
    .slice(AUTO_HOLD_REASON_PREFIX.length)
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s && s !== "menschliche Prüfung nötig");
}

/* Der Haltegrund in Klartext, wie P27 ihn an der Karte verlangt. */
export function holdText(verdictReason: string | null): string | null {
  const codes = holdCodes(verdictReason);
  if (!codes.length) return null;
  return `Automatische Freigabe ausgesetzt: ${codes.map((c) => HOLD_WORDS[c] ?? c).join(", ")}. Ein Mensch entscheidet.`;
}

/* Ohne `rubric.review_state` (alle Läufe vor Lane P3): Klasse aus dem, was schon da ist.
 *
 * Nicht freigabefähig: ein gerissenes Tor (`gate_passed = false` entsteht nur durch eine Revision
 * in der Web-App, CANDIDATES.md). Unsicher: Haltegrund der Automatik, Humor oder heikles Thema
 * (Regel 11), ein Story-Graph-Treffer (spätere Relativierung). Sonst bestanden. Das Flag `claim`
 * allein macht nicht unsicher: es trifft fast jeden Kandidaten (P36), freigaberelevant ist nur, was
 * im Haltegrund steht. */
function derivedReviewState(c: ReviewInput): ReviewState {
  const clip: SourceSpan | null = finite(c.start_s) && finite(c.end_s) && c.end_s >= c.start_s ? { start_s: c.start_s, end_s: c.end_s } : null;
  if (c.gate_passed === false) {
    const reasons: ReviewReason[] = Object.entries(c.gates ?? {})
      .filter(([, g]) => g && g.passed === false)
      .map(([key, g]) => ({ code: `gate_${key}`, text: g.detail?.trim() || "Prüfung nicht bestanden", source_span: clip, origin: "rule" }));
    if (!reasons.length) reasons.push({ code: "gate", text: "Eine Pflichtprüfung ist nicht bestanden", source_span: clip, origin: "rule" });
    return { state: "blocked", reasons, repair: null, derived: true };
  }
  const reasons: ReviewReason[] = [];
  const held = holdText(c.verdict_reason);
  const heldCodes = holdCodes(c.verdict_reason);
  if (held && isHeldCandidate(c)) reasons.push({ code: "auto_hold", text: held, source_span: clip, origin: "rule" });
  for (const flag of ["humor", "sensitive_topic"] as RiskFlag[]) {
    if (c.risk_flags?.includes(flag) && !(held && heldCodes.includes(flag))) {
      reasons.push({ code: flag, text: RISK_LABELS[flag], source_span: clip, origin: "rule" });
    }
  }
  for (const f of c.story_graph_flags ?? []) {
    if (!finite(f.seconds_after) || !finite(c.end_s)) continue;
    const at = c.end_s + f.seconds_after;
    const what = f.text?.trim() ? `: „${f.text.trim()}“` : "";
    reasons.push({
      code: "later_qualification",
      text: `${f.confirmed === true ? "Spätere Relativierung" : "Mögliche spätere Relativierung"} ${timecode(f.seconds_after)} nach dem Ende${what}`,
      source_span: { start_s: at, end_s: at },
      origin: f.confirmed === true ? "model" : "rule",
    });
  }
  return { state: reasons.length ? "uncertain" : "passed", reasons, repair: null, derived: true };
}

export function reviewState(c: ReviewInput): ReviewState {
  return storedReviewState(c.rubric) ?? derivedReviewState(c);
}

/* Eine Titelkarten-Reparatur am Kandidaten, falls die Pipeline eine gesetzt hat. `rubric.repair`
 * ist unter Fassung 1 schon mit `{rounds, expanded_front, …}` belegt; eine Reparatur erkennt man
 * dort nur an `kind = "title_card"`. */
export function titleCardRepair(rubric: unknown): { text: string; source_span: SourceSpan | null } | null {
  const r = rubric as Record<string, unknown> | null;
  for (const raw of [r?.repair_applied, r?.repair]) {
    if (!raw || typeof raw !== "object") continue;
    const x = raw as Record<string, unknown>;
    if (x.kind === "title_card" && typeof x.text === "string" && x.text.trim()) {
      return { text: x.text.trim(), source_span: readSpan(x.source_span) };
    }
  }
  return null;
}

/* Das menschliche Urteil, wie es an der Karte steht. */
export type VerdictStatus = "open" | "held" | "flagged" | "auto_accepted" | "accepted" | "rejected" | "replaced";

export interface VerdictView {
  status: VerdictStatus;
  label: string;
  /* Der Grund in Klartext, wenn es einen gibt: Haltegrund, Kommentar an die Redaktion, Ablehnung. */
  reason: string | null;
}

export function verdictView(c: Pick<Candidate, "human_verdict" | "verdict_reason" | "verdict_by">): VerdictView {
  const reason = c.verdict_reason?.trim() || null;
  if (c.human_verdict === "rejected") return { status: "rejected", label: "Abgelehnt", reason };
  if (c.human_verdict === "edited") return { status: "replaced", label: "Ersetzt", reason: null };
  if (c.human_verdict === "accepted") {
    if (c.verdict_by == null) return { status: "auto_accepted", label: "Automatisch angenommen", reason: null };
    const override = reason?.startsWith(OVERRIDE_REASON_PREFIX) ? `Trotz Befund: ${reason.slice(OVERRIDE_REASON_PREFIX.length)}` : null;
    return { status: "accepted", label: "Angenommen", reason: override };
  }
  if (reason?.startsWith(EDITORIAL_FLAG_PREFIX)) {
    return { status: "flagged", label: "An Redaktion", reason: reason.slice(EDITORIAL_FLAG_PREFIX.length) };
  }
  const held = holdText(reason);
  if (held) return { status: "held", label: "Zurückgehalten", reason: held };
  return { status: "open", label: "Offen", reason: null };
}

/* Die eine Qualitätszahl: `total` auf der Skala der Richtlinie.
 *
 * Nominal 0 bis 14 (sieben Kriterien zu je 0 bis 2). Mit Klanganteil (`rubric.klang` gesetzt) hebt
 * der Klang-Faktor den Wert um höchstens 15 Prozent, also bis 16,1 (CANDIDATES.md, `total`;
 * clip_policy_v1.yaml und v2.yaml: audio.gewicht 0,15). Ein ausdrückliches
 * `rubric.policy_total_max` gewinnt. Keine Umrechnung auf 0 bis 10 und keine Reichweite
 * (docs/decisions/052-eine-qualitaetszahl.md). */
export const NOMINAL_TOTAL_MAX = 14;
export const SOUND_TOTAL_MAX = 16.1;

export interface QualityScore {
  value: number;
  max: number;
  text: string;
}

function decimal(n: number): string {
  return n.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function qualityScore(c: Pick<Candidate, "total" | "rubric">): QualityScore | null {
  if (!finite(c.total)) return null;
  const r = c.rubric as unknown as Record<string, unknown> | null;
  const explicit = r?.policy_total_max;
  const max = finite(explicit) && explicit > 0 ? explicit : finite(r?.klang) ? SOUND_TOTAL_MAX : NOMINAL_TOTAL_MAX;
  return { value: c.total, max, text: `Qualität ${decimal(c.total)} von ${decimal(max).replace(/,0$/, "")}` };
}

/* Belegstellen als Zeitbereiche im Quellvideo (Regel 12). Einstieg und Pointe aus dem
 * ClipCandidate, wenn die Rubrik sie trägt; sonst der ganze Clip. */
export interface Evidence {
  kind: "opening" | "payoff" | "clip";
  label: string;
  span: SourceSpan;
}

export function evidenceSpans(c: Pick<Candidate, "rubric" | "start_s" | "end_s">): Evidence[] {
  const r = c.rubric as unknown as Record<string, unknown> | null;
  const out: Evidence[] = [];
  const opening = readSpan(r?.opening_source_span);
  if (opening) out.push({ kind: "opening", label: "Einstieg", span: opening });
  const payoff = readSpan(r?.payoff_source_span);
  if (payoff) out.push({ kind: "payoff", label: "Pointe", span: payoff });
  if (!out.length && finite(c.start_s) && finite(c.end_s) && c.end_s >= c.start_s) {
    out.push({ kind: "clip", label: "Clip", span: { start_s: c.start_s, end_s: c.end_s } });
  }
  return out;
}

export function spanText(span: SourceSpan): string {
  if (span.end_s - span.start_s < 0.05) return `bei ${timecode(span.start_s)}`;
  return `${timecode(span.start_s)} bis ${timecode(span.end_s)}`;
}

/* Wo im fertigen Clip eine Stelle der Quelle liegt. Die Segmente laufen in Abspielreihenfolge
 * (ein Teaser kann vor dem Body stehen); liegt die Stelle in keinem, gilt der Anfang des Clips. */
export function clipOffset(segments: Pick<CandidateSegment, "start" | "end">[], sourceTime: number): number {
  let played = 0;
  for (const seg of segments) {
    if (sourceTime >= seg.start && sourceTime <= seg.end) return played + (sourceTime - seg.start);
    played += Math.max(0, seg.end - seg.start);
  }
  return 0;
}

/* Flags als Wörter, mit dem ausführlichen Satz als Erklärung. */
export function riskWords(c: Pick<Candidate, "risk_flags">): { key: RiskFlag; word: string; title: string }[] {
  return (c.risk_flags ?? []).filter((f) => RISK_WORDS[f]).map((f) => ({ key: f, word: RISK_WORDS[f], title: RISK_LABELS[f] }));
}

/* Reihenfolge der Liste: zuerst bestanden, dann unsicher, dann nicht freigabefähig; innerhalb
 * nach Qualität absteigend (ohne Wert ganz hinten), bei Gleichstand nach Startzeit. Abgelehnte
 * Kandidaten stehen am Ende, gleich welcher Klasse: über sie ist entschieden. */
export function compareForReview(a: (ReviewInput & Pick<Candidate, "total">) | null, b: (ReviewInput & Pick<Candidate, "total">) | null): number {
  if (!a || !b) return a ? -1 : b ? 1 : 0;
  const ra = a.human_verdict === "rejected" ? 1 : 0;
  const rb = b.human_verdict === "rejected" ? 1 : 0;
  if (ra !== rb) return ra - rb;
  const sa = REVIEW_STATE_ORDER[reviewState(a).state];
  const sb = REVIEW_STATE_ORDER[reviewState(b).state];
  if (sa !== sb) return sa - sb;
  const ta = finite(a.total) ? a.total : -Infinity;
  const tb = finite(b.total) ? b.total : -Infinity;
  if (ta !== tb) return tb - ta;
  return (a.start_s ?? 0) - (b.start_s ?? 0);
}

/* Der Grund, der beim Flag an die Redaktion gespeichert wird. Die Sekunde zählt im fertigen Clip,
 * wie bei der Rückmeldung eines Gastes. */
export function editorialFlagReason(comment: string, atS: number | null): string {
  const where = atS != null ? ` (bei ${timecode(atS)} im Clip)` : "";
  return `${EDITORIAL_FLAG_PREFIX}${comment.trim()}${where}`;
}
