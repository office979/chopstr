/* Tools für Kandidaten: Liste mit Filtern, Annehmen, Ablehnen, Anpassen. */

import { z } from "zod";
import { confirmSchema, guarded, idSchema, platformSchema, type ToolContext } from "./common.js";
import { formatDecimal, formatSeconds, limitList, previewResult, textResult, truncationNote, unwrapList, unwrapObject } from "../format.js";
import type { Candidate, Clip } from "../types.js";

export function candidateSummary(c: Candidate): Record<string, unknown> {
  const gates = c.gates ?? {};
  const failedGates = Object.entries(gates)
    .filter(([, g]) => g && g.passed === false)
    .map(([name, g]) => `${name}: ${g?.detail ?? ""}`.trim());
  return {
    id: c.id,
    version: c.version ?? null,
    start_s: c.start_s ?? null,
    end_s: c.end_s ?? null,
    duration_s: c.rubric?.duration_s ?? (c.start_s !== undefined && c.end_s !== undefined ? Math.round((c.end_s - c.start_s) * 10) / 10 : null),
    structure: c.structure ?? null,
    total: c.total ?? null,
    gate_passed: c.gate_passed ?? null,
    failed_gates: failedGates,
    risk_flags: c.risk_flags ?? [],
    story_graph_flags: (c.story_graph_flags ?? []).map((f) => ({ marker: f.marker ?? null, confirmed: f.confirmed ?? null, reason: f.reason ?? null, repair: f.repair ?? null })),
    human_verdict: c.human_verdict ?? null,
    verdict_reason: c.verdict_reason ?? null,
    why: c.why ?? null,
    scores: c.rubric?.scores ?? null,
    suggested_title_card: c.rubric?.suggested_title_card ?? null,
    first_sent: c.first_sent ?? null,
    last_sent: c.last_sent ?? null,
    text: c.rubric?.text ?? null,
  };
}

function candidateLine(c: Candidate): string {
  const range = `${formatSeconds(c.start_s ?? null)} bis ${formatSeconds(c.end_s ?? null)}`;
  const gate = c.gate_passed === true ? "Gates ok" : c.gate_passed === false ? "Gate verletzt" : "Gates ?";
  const verdict = c.human_verdict ? `, Urteil ${c.human_verdict}` : "";
  const flags = (c.risk_flags ?? []).length ? `, Flags ${(c.risk_flags ?? []).join("/")}` : "";
  return `${c.id}  Score ${formatDecimal(c.total ?? null)}  ${range}  ${c.structure ?? "?"}  ${gate}${verdict}${flags}\n    ${c.why ?? ""}`.trimEnd();
}

export function registerCandidateTools({ server, api }: ToolContext): void {
  server.registerTool(
    "list_candidates",
    {
      title: "Kandidaten auflisten",
      description:
        "Listet die Clip-Kandidaten einer Quelle nach Score, mit Zeitfenster, Struktur, Pflichtkriterien (Gates), Risiko-Flags, Story-Graph-Hinweisen und Begründung. Filter: gate_passed (nur mit bestandenen Gates) und verdict (accepted, rejected, edited oder open für noch nicht beurteilte). Höchstens 50 Einträge.",
      inputSchema: {
        source_id: idSchema.describe("ID der Quelle"),
        gate_passed: z.boolean().optional().describe("true: nur Kandidaten, die alle Pflichtkriterien erfüllen"),
        verdict: z.enum(["accepted", "rejected", "edited", "open"]).optional().describe("Nach menschlichem Urteil filtern, open = noch ohne Urteil"),
        limit: z.number().int().min(1).max(50).optional().describe("Höchstzahl, Standard 50"),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ source_id, gate_passed, verdict, limit }) =>
      guarded(async () => {
        const body = await api.get<unknown>(`/sources/${encodeURIComponent(source_id)}/candidates`, {
          gate_passed,
          verdict: verdict === "open" ? undefined : verdict,
        });
        let candidates = unwrapList<Candidate>(body, "candidates");
        if (gate_passed !== undefined) candidates = candidates.filter((c) => Boolean(c.gate_passed) === gate_passed);
        if (verdict === "open") candidates = candidates.filter((c) => !c.human_verdict);
        else if (verdict) candidates = candidates.filter((c) => c.human_verdict === verdict);
        candidates.sort((a, b) => (b.total ?? 0) - (a.total ?? 0));
        const t = limitList(candidates, limit ?? 50);
        const summary =
          t.items.length === 0
            ? "Keine Kandidaten für diese Filter."
            : `${t.total} Kandidat(en) für Quelle ${source_id}:\n` + t.items.map(candidateLine).join("\n") + truncationNote(t, "Kandidaten");
        return textResult(summary, { source_id, total: t.total, truncated: t.truncated, candidates: t.items.map(candidateSummary) });
      }),
  );

  server.registerTool(
    "accept_candidate",
    {
      title: "Kandidat annehmen",
      description:
        "Nimmt einen Kandidaten an. chopstr legt je Zielplattform einen Clip an und startet den Render. Schreibende Aktion: nur mit confirm: true, sonst Vorschau. Vorher die Rubrik, Gates und Story-Graph-Hinweise prüfen (list_candidates).",
      inputSchema: {
        candidate_id: idSchema.describe("ID des Kandidaten"),
        platforms: z.array(platformSchema).min(1).optional().describe("Zielplattformen, Standard alle vier; die Standardplattform des Markenprofils ist immer dabei"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ candidate_id, platforms, confirm }) =>
      guarded(async () => {
        const targets = platforms ?? ["tiktok", "reels", "shorts", "linkedin"];
        if (confirm !== true) {
          return previewResult("accept_candidate", `Kandidat ${candidate_id} annehmen und Clips für ${targets.join(", ")} anlegen und rendern.`, {
            candidate_id,
            platforms: targets,
          });
        }
        const body = await api.post<unknown>(`/candidates/${encodeURIComponent(candidate_id)}/verdict`, { verdict: "accepted", platforms: targets });
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const clips = unwrapList<Clip>(record.clips ?? [], "clips");
        const candidate = unwrapObject<Candidate>(record.candidate ?? record, "candidate");
        const clipLines = clips.map((c) => `  ${c.platform ?? "?"}: Clip ${c.id} (${c.status ?? "draft"})`);
        return textResult(
          [`Kandidat ${candidate_id} angenommen.`, clips.length ? `Clips angelegt:` : "Keine Clip-IDs in der Antwort.", ...clipLines, "Der Render läuft im Hintergrund; Status mit list_clips oder get_clip prüfen."].join("\n"),
          { candidate_id, verdict: candidate.human_verdict ?? "accepted", clips: clips.map((c) => ({ id: c.id, platform: c.platform ?? null, status: c.status ?? null })) },
        );
      }),
  );

  server.registerTool(
    "reject_candidate",
    {
      title: "Kandidat ablehnen",
      description:
        "Lehnt einen Kandidaten ab. Ein kurzer Grund ist Pflicht (Lernsignal für die Gewichte des Markenprofils). Schreibende Aktion: nur mit confirm: true, sonst Vorschau.",
      inputSchema: {
        candidate_id: idSchema.describe("ID des Kandidaten"),
        reason: z.string().min(3).max(500).describe("Kurzer Grund, zum Beispiel: Aussage ohne Kontext missverständlich"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ candidate_id, reason, confirm }) =>
      guarded(async () => {
        const trimmed = reason.trim();
        if (!trimmed) return textResult("Beim Ablehnen ist ein kurzer Grund Pflicht.", { error: "reason_required" });
        if (confirm !== true) {
          return previewResult("reject_candidate", `Kandidat ${candidate_id} ablehnen mit Grund: „${trimmed}“.`, { candidate_id, reason: trimmed });
        }
        const body = await api.post<unknown>(`/candidates/${encodeURIComponent(candidate_id)}/verdict`, { verdict: "rejected", reason: trimmed });
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const candidate = unwrapObject<Candidate>(record.candidate ?? record, "candidate");
        return textResult(`Kandidat ${candidate_id} abgelehnt. Grund gespeichert: „${trimmed}“.`, {
          candidate_id,
          verdict: candidate.human_verdict ?? "rejected",
          reason: trimmed,
        });
      }),
  );

  server.registerTool(
    "revise_candidate",
    {
      title: "Kandidat anpassen",
      description:
        "Verlängert oder kürzt einen Kandidaten über Satzindizes (first_sent, last_sent) oder setzt eine Titelkarte (max. 8 Wörter, für fehlenden Kontext). Legt eine neue Version an, Gates werden neu berechnet, Scores gelten als veraltet. Schreibende Aktion: nur mit confirm: true, sonst Vorschau.",
      inputSchema: {
        candidate_id: idSchema.describe("ID des Kandidaten"),
        first_sent: z.number().int().min(0).optional().describe("Neuer erster Satzindex"),
        last_sent: z.number().int().min(0).optional().describe("Neuer letzter Satzindex"),
        title_card: z.string().max(120).optional().describe("Titelkarte mit höchstens 8 Wörtern, leer zum Entfernen"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ candidate_id, first_sent, last_sent, title_card, confirm }) =>
      guarded(async () => {
        if (first_sent === undefined && last_sent === undefined && title_card === undefined) {
          return textResult("Nichts zu ändern: first_sent, last_sent oder title_card angeben.", { error: "nothing_to_change" });
        }
        if (first_sent !== undefined && last_sent !== undefined && first_sent > last_sent) {
          return textResult("first_sent darf nicht größer als last_sent sein.", { error: "invalid_range" });
        }
        if (title_card !== undefined) {
          const words = title_card.trim().split(/\s+/).filter(Boolean);
          if (words.length > 8) return textResult(`Titelkarte hat ${words.length} Wörter, erlaubt sind höchstens 8.`, { error: "title_card_too_long", words: words.length });
        }
        const payload: Record<string, unknown> = {};
        if (first_sent !== undefined) payload.first_sent = first_sent;
        if (last_sent !== undefined) payload.last_sent = last_sent;
        if (title_card !== undefined) payload.title_card = title_card.trim();
        const parts: string[] = [];
        if (first_sent !== undefined) parts.push(`erster Satz ${first_sent}`);
        if (last_sent !== undefined) parts.push(`letzter Satz ${last_sent}`);
        if (title_card !== undefined) parts.push(`Titelkarte „${title_card.trim()}“`);
        if (confirm !== true) {
          return previewResult("revise_candidate", `Kandidat ${candidate_id} anpassen: ${parts.join(", ")}. Es entsteht eine neue Version, die alte wird als edited markiert.`, { candidate_id, payload });
        }
        const body = await api.post<unknown>(`/candidates/${encodeURIComponent(candidate_id)}/revise`, payload);
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const candidate = unwrapObject<Candidate>(record.candidate ?? record, "candidate");
        const gate = candidate.gate_passed === true ? "alle Gates bestanden" : candidate.gate_passed === false ? "mindestens ein Gate verletzt" : "Gates unbekannt";
        return textResult(
          `Neue Version angelegt: Kandidat ${candidate.id ?? "?"} (Version ${candidate.version ?? "?"}), ${formatSeconds(candidate.start_s ?? null)} bis ${formatSeconds(candidate.end_s ?? null)}, ${gate}. Scores stammen noch von der alten Version.`,
          { previous_id: candidate_id, candidate: candidateSummary(candidate) },
        );
      }),
  );
}
