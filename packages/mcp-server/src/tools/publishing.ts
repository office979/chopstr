/* Veröffentlichung: publish_clip mit Scope publish. Kein Autopublishing: jede Publikation ist eine Nutzeraktion. */

import { z } from "zod";
import { confirmSchema, guarded, idSchema, type ToolContext } from "./common.js";
import { previewResult, textResult, unwrapObject } from "../format.js";
import type { Publication } from "../types.js";

export function registerPublishingTools({ server, api }: ToolContext): void {
  server.registerTool(
    "publish_clip",
    {
      title: "Clip veröffentlichen",
      description:
        "Veröffentlicht einen gerenderten Clip über eine verbundene Plattform (connection_id) sofort oder zu einem Zeitpunkt (scheduled_for, ISO 8601 mit Zeitzone). Voraussetzungen: Clip rendered, Kandidat angenommen, Gast-Freigabe falls verlangt, Scope publish. Schreibende, nach außen wirksame Aktion: nur mit confirm: true, sonst Vorschau. Immer vorher den Nutzer fragen.",
      inputSchema: {
        clip_id: idSchema.describe("ID des Clips"),
        connection_id: idSchema.describe("ID der Plattform-Verbindung (platform_connections)"),
        scheduled_for: z.string().datetime({ offset: true }).optional().describe("Geplanter Zeitpunkt, ISO 8601 mit Zeitzone, zum Beispiel 2026-10-01T09:00:00+02:00; leer = sofort"),
        caption: z.string().max(3000).optional().describe("Post-Text, Standard ist der Post-Text der aktuellen Hook-Version"),
        title: z.string().max(200).optional().describe("Titel, sofern die Plattform einen führt"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async ({ clip_id, connection_id, scheduled_for, caption, title, confirm }) =>
      guarded(async () => {
        if (scheduled_for) {
          const when = new Date(scheduled_for);
          if (Number.isNaN(when.getTime())) return textResult("scheduled_for ist kein gültiger Zeitpunkt.", { error: "invalid_datetime" });
          if (when.getTime() < Date.now() - 60_000) return textResult("scheduled_for liegt in der Vergangenheit.", { error: "datetime_in_past" });
        }
        const payload: Record<string, unknown> = { connection_id };
        if (scheduled_for) payload.scheduled_for = scheduled_for;
        if (caption !== undefined) payload.caption = caption;
        if (title !== undefined) payload.title = title;
        if (confirm !== true) {
          return previewResult("publish_clip", `Clip ${clip_id} über Verbindung ${connection_id} ${scheduled_for ? `am ${scheduled_for} planen` : "sofort veröffentlichen"}${caption !== undefined ? " mit eigenem Post-Text" : ""}. Das ist nach außen sichtbar und lässt sich nicht über die API zurücknehmen.`, { clip_id, payload });
        }
        const body = await api.post<unknown>(`/clips/${encodeURIComponent(clip_id)}/publish`, payload);
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const publication = unwrapObject<Publication>(record.publication ?? record, "publication");
        const status = publication.status ?? "scheduled";
        return textResult(
          [
            `Publikation ${publication.id ?? "?"} für Clip ${clip_id} angelegt, Status ${status}.`,
            publication.scheduled_for ? `Geplant für ${publication.scheduled_for}.` : null,
            publication.external_url ? `Post-URL: ${publication.external_url}` : null,
            publication.error ? `Fehler: ${publication.error}` : null,
          ]
            .filter((l): l is string => Boolean(l))
            .join("\n"),
          { clip_id, publication: publication as Record<string, unknown> },
        );
      }),
  );
}
