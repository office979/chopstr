/* Tools rund um Quellen: Liste, Details, Anlage per URL, Transkript. */

import { z } from "zod";
import { confirmSchema, guarded, idSchema, platformSchema, type ToolContext } from "./common.js";
import { formatSeconds, limitList, previewResult, textResult, truncationNote, unwrapList, unwrapObject } from "../format.js";
import { renderTranscriptText, speakerNames, summarizeTranscript, windowWords } from "../transcript.js";
import type { Source, Transcript } from "../types.js";

function sourceLine(s: Source): string {
  const duration = s.duration_s ? `, ${formatSeconds(s.duration_s)}` : "";
  return `${s.id}  ${s.title ?? "(ohne Titel)"}  [${s.status ?? "?"}${duration}]`;
}

export function registerSourceTools({ server, api }: ToolContext): void {
  server.registerTool(
    "list_sources",
    {
      title: "Quellen auflisten",
      description:
        "Listet die Quellen (Langvideos) des Workspace mit Status und Dauer. Optional nach Status filtern. Höchstens 50 Einträge.",
      inputSchema: {
        status: z.string().optional().describe("Nur Quellen mit diesem Status, zum Beispiel ready, analyzing, failed"),
        limit: z.number().int().min(1).max(50).optional().describe("Höchstzahl der Einträge, Standard 50"),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ status, limit }) =>
      guarded(async () => {
        const body = await api.get<unknown>("/sources", { status, limit });
        let sources = unwrapList<Source>(body, "sources");
        if (status) sources = sources.filter((s) => !s.status || s.status === status);
        const t = limitList(sources, limit ?? 50);
        const summary =
          t.items.length === 0
            ? "Keine Quellen gefunden."
            : `${t.total} Quelle(n):\n` + t.items.map(sourceLine).join("\n") + truncationNote(t, "Quellen");
        return textResult(summary, {
          total: t.total,
          truncated: t.truncated,
          sources: t.items.map((s) => ({
            id: s.id,
            title: s.title ?? null,
            status: s.status ?? null,
            duration_s: s.duration_s ?? null,
            brand_profile_id: s.brand_profile_id ?? null,
            created_at: s.created_at ?? null,
          })),
        });
      }),
  );

  server.registerTool(
    "get_source",
    {
      title: "Quelle anzeigen",
      description: "Details einer Quelle: Titel, Status, Dauer, Rechte, Briefing, Markenprofil.",
      inputSchema: { source_id: idSchema.describe("ID der Quelle") },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ source_id }) =>
      guarded(async () => {
        const body = await api.get<unknown>(`/sources/${encodeURIComponent(source_id)}`);
        const source = unwrapObject<Source>(body, "source");
        const lines = [
          `Quelle ${source.id}: ${source.title ?? "(ohne Titel)"}`,
          `Status: ${source.status ?? "?"}${source.status_message ? ` (${source.status_message})` : ""}`,
          `Dauer: ${formatSeconds(source.duration_s ?? null)}`,
          `Rechte: ${source.rights_status ?? "?"}${source.source_owner ? `, Urheber ${source.source_owner}` : ""}`,
        ];
        return textResult(lines.join("\n"), { source: source as Record<string, unknown> });
      }),
  );

  server.registerTool(
    "create_source_from_url",
    {
      title: "Quelle per URL anlegen",
      description:
        "Legt eine neue Quelle aus einer Video-URL an und startet den Ingest. Verlangt rights_confirmed: true sowie source_owner und source_url (Rechteklärung, kein Fremdmaterial ohne Lizenz). Schreibende Aktion: nur mit confirm: true, sonst Vorschau. Verbraucht Stundenkontingent.",
      inputSchema: {
        title: z.string().min(1).max(200).describe("Titel des Projekts"),
        source_url: z.string().url().describe("Öffentlich erreichbare Video-URL (https)"),
        source_owner: z.string().min(1).max(200).describe("Urheber oder Rechteinhaber, wird als Quellen-Credit geführt"),
        rights_confirmed: z.boolean().describe("Muss true sein: Der Nutzer bestätigt, dass die Rechte für Schnitt und Veröffentlichung vorliegen"),
        rights_status: z.enum(["own", "licensed", "third_party"]).optional().describe("Rechtelage, Standard licensed"),
        brand_profile_id: idSchema.optional().describe("Markenprofil, das Anrede, Land und Plattform-Standard bestimmt"),
        source_title: z.string().max(200).optional().describe("Originaltitel des Videos"),
        brief: z
          .object({
            audience: z.string().max(500).optional(),
            wanted: z.string().max(500).optional(),
            exclude: z.string().max(500).optional(),
            platform: platformSchema.optional(),
            is_ad: z.boolean().optional(),
          })
          .optional()
          .describe("Briefing: Zielgruppe, gewünschte Themen, Ausschlüsse, Zielplattform, Werbekennzeichnung"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async (input) =>
      guarded(async () => {
        if (input.rights_confirmed !== true) {
          return textResult(
            "Abgebrochen: rights_confirmed muss true sein. Ohne bestätigte Rechte legt chopstr keine Quelle aus einer URL an. Bitte beim Nutzer klären, ob die Rechte am Material vorliegen.",
            { created: false, reason: "rights_not_confirmed" },
          );
        }
        const payload = {
          title: input.title,
          brand_profile_id: input.brand_profile_id ?? null,
          rights_status: input.rights_status ?? "licensed",
          rights_confirmed: true,
          source_owner: input.source_owner,
          source_url: input.source_url,
          source_title: input.source_title ?? null,
          brief: input.brief ?? {},
          upload: "url" as const,
        };
        if (input.confirm !== true) {
          return previewResult(
            "create_source_from_url",
            `Quelle „${input.title}“ aus ${input.source_url} anlegen (Urheber: ${input.source_owner}, Rechte: ${payload.rights_status}). Der Ingest startet sofort und verbraucht Stundenkontingent.`,
            { payload },
          );
        }
        const body = await api.post<unknown>("/sources", payload);
        const source = unwrapObject<Source>(body, "source");
        const record = body && typeof body === "object" ? (body as Record<string, unknown>) : {};
        return textResult(
          `Quelle angelegt: ${source.id ?? "?"} „${source.title ?? input.title}“, Status ${source.status ?? "?"}. Der Ingest läuft im Hintergrund; mit get_source den Status prüfen.`,
          { created: true, source: source as Record<string, unknown>, upload_token: record.upload_token ?? null, tus_endpoint: record.tus_endpoint ?? null },
        );
      }),
  );

  server.registerTool(
    "get_transcript",
    {
      title: "Transkript lesen",
      description:
        "Liest das aktuelle Transkript einer Quelle mit Sprechern und Timecodes. Ohne Fenster kommt eine Kurzfassung (Dauer, Sprecher, erste 200 Wörter); mit start_s und end_s der vollständige Text des Ausschnitts. Lange Transkripte bitte immer in Fenstern lesen.",
      inputSchema: {
        source_id: idSchema.describe("ID der Quelle"),
        start_s: z.number().min(0).optional().describe("Fensterbeginn in Sekunden"),
        end_s: z.number().min(0).optional().describe("Fensterende in Sekunden"),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ source_id, start_s, end_s }) =>
      guarded(async () => {
        if (start_s !== undefined && end_s !== undefined && end_s <= start_s) {
          return textResult("end_s muss größer als start_s sein.", { error: "invalid_window" });
        }
        const body = await api.get<unknown>(`/sources/${encodeURIComponent(source_id)}/transcript`);
        const transcript = unwrapObject<Transcript>(body, "transcript");
        const words = Array.isArray(transcript.words) ? transcript.words : [];
        const names = speakerNames(transcript);
        const windowed = start_s !== undefined || end_s !== undefined;
        if (windowed) {
          const slice = windowWords(words, start_s, end_s);
          const text = renderTranscriptText(slice, names);
          const from = formatSeconds(start_s ?? 0);
          const to = end_s !== undefined ? formatSeconds(end_s) : "Ende";
          const summary = slice.length === 0 ? `Keine Wörter im Fenster ${from} bis ${to}.` : `Transkript ${from} bis ${to} (${slice.length} Wörter):\n\n${text}`;
          return textResult(summary, {
            source_id,
            version: transcript.version ?? null,
            window: { start_s: start_s ?? 0, end_s: end_s ?? null },
            word_count: slice.length,
            speakers: names,
            text,
          });
        }
        const s = summarizeTranscript(transcript);
        const speakerLines = s.speakers.map((sp) => `  ${sp.name ? `${sp.name} (${sp.id})` : sp.id}: ${sp.words} Wörter, ${formatSeconds(sp.seconds)} Redezeit`);
        const summary = [
          `Transkript der Quelle ${source_id}${s.version ? ` (Version ${s.version})` : ""}: ${formatSeconds(s.duration_s)}, ${s.word_count} Wörter, ${s.speakers.length} Sprecher.`,
          ...speakerLines,
          "",
          `Anfang (erste ${SUMMARY_LABEL} Wörter):`,
          s.preview + (s.preview_truncated ? " …" : ""),
          "",
          "Hinweis: Das ist nur der Anfang. Für den vollständigen Text bitte Fenster mit start_s und end_s abrufen, zum Beispiel in Abschnitten von 5 bis 10 Minuten.",
        ].join("\n");
        return textResult(summary, {
          source_id,
          version: s.version,
          language: s.language,
          duration_s: s.duration_s,
          word_count: s.word_count,
          speakers: s.speakers,
          preview: s.preview,
          preview_truncated: s.preview_truncated,
          windowed: false,
        });
      }),
  );
}

const SUMMARY_LABEL = 200;
