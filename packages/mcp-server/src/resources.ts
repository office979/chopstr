/* Resources: Transkript als Text, Render-Plan als JSON, Kontingent als JSON. */

import { ResourceTemplate, type McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ApiClient } from "./api.js";
import { unwrapObject } from "./format.js";
import { renderTranscriptText, speakerNames } from "./transcript.js";
import type { Clip, Transcript, Usage } from "./types.js";

function single(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

export function registerResources(server: McpServer, api: ApiClient): void {
  server.registerResource(
    "transcript",
    new ResourceTemplate("chopstr://sources/{id}/transcript", { list: undefined }),
    {
      title: "Transkript einer Quelle",
      description: "Aktuelles Transkript mit Sprechern und Timecodes als Text. Für lange Quellen lieber get_transcript mit Fenster nutzen.",
      mimeType: "text/plain",
    },
    async (uri, variables) => {
      const id = single(variables.id);
      const body = await api.get<unknown>(`/sources/${encodeURIComponent(id)}/transcript`);
      const transcript = unwrapObject<Transcript>(body, "transcript");
      const words = Array.isArray(transcript.words) ? transcript.words : [];
      const header = `Transkript Quelle ${id}${transcript.version ? `, Version ${transcript.version}` : ""}${transcript.language ? `, Sprache ${transcript.language}` : ""}\n\n`;
      return { contents: [{ uri: uri.href, mimeType: "text/plain", text: header + renderTranscriptText(words, speakerNames(transcript)) }] };
    },
  );

  server.registerResource(
    "render-plan",
    new ResourceTemplate("chopstr://clips/{id}/render-plan", { list: undefined }),
    {
      title: "Render-Plan eines Clips",
      description: "Vollständiger, deterministischer Render-Plan (render_plan_v1) als JSON.",
      mimeType: "application/json",
    },
    async (uri, variables) => {
      const id = single(variables.id);
      const body = await api.get<unknown>(`/clips/${encodeURIComponent(id)}`);
      const clip = unwrapObject<Clip>(body, "clip");
      const plan = clip.render_plan ?? null;
      return { contents: [{ uri: uri.href, mimeType: "application/json", text: JSON.stringify(plan, null, 2) }] };
    },
  );

  server.registerResource(
    "usage",
    "chopstr://usage",
    {
      title: "Kontingent des Monats",
      description: "Stundenkontingent des laufenden Monats als JSON.",
      mimeType: "application/json",
    },
    async (uri) => {
      const body = await api.get<unknown>("/usage");
      const usage = unwrapObject<Usage>(body, "usage");
      return { contents: [{ uri: uri.href, mimeType: "application/json", text: JSON.stringify(usage, null, 2) }] };
    },
  );
}
