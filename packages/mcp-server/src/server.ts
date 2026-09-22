/* Baut den MCP-Server: Tools, Resources, Prompts gegen einen ApiClient. */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ApiClient } from "./api.js";
import { registerPrompts } from "./prompts.js";
import { registerResources } from "./resources.js";
import { registerCandidateTools } from "./tools/candidates.js";
import { registerClipTools } from "./tools/clips.js";
import { registerPublishingTools } from "./tools/publishing.js";
import { registerSourceTools } from "./tools/sources.js";
import { registerUsageTools } from "./tools/usage.js";

export const SERVER_NAME = "chopstr";
export const SERVER_VERSION = "0.1.0";

export const SERVER_INSTRUCTIONS = `chopstr ist ein Clipping-Tool für deutschsprachige Langvideos. Die KI schlägt vor, ein Mensch gibt frei.
Regeln für diesen Server:
- Schreibende Tools (create_source_from_url, accept_candidate, reject_candidate, revise_candidate, render_clip, write_hooks, request_guest_approval, publish_clip) führen ohne confirm: true nichts aus, sondern zeigen eine Vorschau. confirm: true nur nach ausdrücklicher Zustimmung des Nutzers setzen.
- publish_clip wirkt nach außen. Nie ohne Rückfrage.
- Transkripte in Fenstern lesen (get_transcript mit start_s und end_s). Keine Transkriptinhalte in Logs oder Protokolle übernehmen.
- Keine Zahl ohne Beleg im Clip-Text. Humor beurteilt der Mensch.`;

export interface CreateServerOptions {
  apiUrl: string;
  apiKey: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  retryDelayMs?: number;
}

export function createServer(options: CreateServerOptions): { server: McpServer; api: ApiClient } {
  const api = new ApiClient({
    baseUrl: options.apiUrl,
    apiKey: options.apiKey,
    timeoutMs: options.timeoutMs,
    fetchImpl: options.fetchImpl,
    retryDelayMs: options.retryDelayMs,
  });
  const server = new McpServer(
    { name: SERVER_NAME, version: SERVER_VERSION, title: "chopstr" },
    { instructions: SERVER_INSTRUCTIONS },
  );
  const ctx = { server, api };
  registerSourceTools(ctx);
  registerCandidateTools(ctx);
  registerClipTools(ctx);
  registerPublishingTools(ctx);
  registerUsageTools(ctx);
  registerResources(server, api);
  registerPrompts(server);
  return { server, api };
}
