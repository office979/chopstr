/* Streamable-HTTP-Transport mit Sitzungen über Node http. Pfad /mcp, Health unter /healthz.
 * Ein Bearer-Header mit chopstr-Schlüssel (chp_live_…) überschreibt je Sitzung den Schlüssel aus der Umgebung. */

import { randomUUID } from "node:crypto";
import http from "node:http";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { API_KEY_PREFIX } from "./config.js";
import { createServer, type CreateServerOptions } from "./server.js";

export interface HttpServerOptions extends CreateServerOptions {
  port: number;
  host: string;
  path?: string;
}

interface Session {
  transport: StreamableHTTPServerTransport;
  close: () => Promise<void>;
}

function bearerKey(req: http.IncomingMessage): string | null {
  const header = req.headers.authorization;
  if (!header || Array.isArray(header)) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  const token = match?.[1]?.trim();
  return token && token.startsWith(API_KEY_PREFIX) ? token : null;
}

function readBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const text = Buffer.concat(chunks).toString("utf8");
      if (!text) return resolve(undefined);
      try {
        resolve(JSON.parse(text));
      } catch {
        reject(new Error("Ungültiger JSON-Body"));
      }
    });
    req.on("error", reject);
  });
}

function isInitialize(body: unknown): boolean {
  const check = (m: unknown) => Boolean(m && typeof m === "object" && (m as { method?: unknown }).method === "initialize");
  return Array.isArray(body) ? body.some(check) : check(body);
}

export function startHttpServer(options: HttpServerOptions): Promise<http.Server> {
  const path = options.path ?? "/mcp";
  const sessions = new Map<string, Session>();

  const httpServer = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    if (url.pathname === "/healthz") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, sessions: sessions.size }));
      return;
    }
    if (url.pathname !== path) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { code: "not_found", message: `Unbekannter Pfad. MCP-Endpunkt ist ${path}.` } }));
      return;
    }
    try {
      const sessionHeader = req.headers["mcp-session-id"];
      const sessionId = Array.isArray(sessionHeader) ? sessionHeader[0] : sessionHeader;
      if (sessionId && sessions.has(sessionId)) {
        const body = req.method === "POST" ? await readBody(req) : undefined;
        await sessions.get(sessionId)!.transport.handleRequest(req, res, body);
        return;
      }
      if (req.method === "POST") {
        const body = await readBody(req);
        if (!sessionId && isInitialize(body)) {
          const apiKey = bearerKey(req) ?? options.apiKey;
          const { server } = createServer({ ...options, apiKey });
          const transport = new StreamableHTTPServerTransport({
            sessionIdGenerator: () => randomUUID(),
            onsessioninitialized: (id) => {
              sessions.set(id, { transport, close: async () => server.close() });
            },
            onsessionclosed: (id) => {
              sessions.delete(id);
            },
          });
          transport.onclose = () => {
            if (transport.sessionId) sessions.delete(transport.sessionId);
          };
          await server.connect(transport);
          await transport.handleRequest(req, res, body);
          return;
        }
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32000, message: "Keine gültige Sitzung. Zuerst initialize senden." }, id: null }));
        return;
      }
      res.writeHead(sessionId ? 404 : 400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32001, message: sessionId ? "Sitzung unbekannt oder abgelaufen." : "Mcp-Session-Id fehlt." }, id: null }));
    } catch (error) {
      if (!res.headersSent) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32603, message: error instanceof Error ? error.message : "Interner Fehler" }, id: null }));
      }
    }
  });

  httpServer.on("close", () => {
    for (const s of sessions.values()) void s.close();
    sessions.clear();
  });

  return new Promise((resolve, reject) => {
    httpServer.once("error", reject);
    httpServer.listen(options.port, options.host, () => resolve(httpServer));
  });
}
