/* Gemeinsame Bausteine der Tools: Bestätigungspflicht, Fehlerübersetzung, Registrierungskontext. */

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import { ApiError, type ApiClient } from "../api.js";
import { errorResult } from "../format.js";

export interface ToolContext {
  server: McpServer;
  api: ApiClient;
}

export const confirmSchema = z
  .boolean()
  .optional()
  .describe("Muss true sein, damit die Aktion ausgeführt wird. Ohne confirm liefert das Tool nur eine Vorschau.");

export const idSchema = z.string().min(1).max(200);

export const platformSchema = z.enum(["tiktok", "reels", "shorts", "linkedin"]);

/* Führt einen Tool-Handler aus und übersetzt API- und Laufzeitfehler in eine Fehlerantwort für das Modell. */
export async function guarded(fn: () => Promise<CallToolResult>): Promise<CallToolResult> {
  try {
    return await fn();
  } catch (error) {
    if (error instanceof ApiError) {
      return errorResult(error.message, {
        error: { kind: error.kind, status: error.status, code: error.code, path: error.path },
      });
    }
    const message = error instanceof Error ? error.message : String(error);
    return errorResult(`Unerwarteter Fehler im MCP-Server: ${message}`);
  }
}
