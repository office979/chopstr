import type http from "node:http";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { startHttpServer } from "../src/http.js";
import { MOCK_API_KEY, startMockApi, type MockApi } from "./mock-api.js";

let mock: MockApi;
let server: http.Server;
let port: number;

beforeAll(async () => {
  mock = await startMockApi();
  port = 40000 + Math.floor(Math.random() * 10000);
  server = await startHttpServer({ apiUrl: mock.url, apiKey: MOCK_API_KEY, port, host: "127.0.0.1", retryDelayMs: 0, timeoutMs: 5000 });
});
afterAll(async () => {
  await new Promise<void>((r) => server.close(() => r()));
  await mock.close();
});

describe("Streamable HTTP", () => {
  it("beantwortet /healthz", async () => {
    const res = await fetch(`http://127.0.0.1:${port}/healthz`);
    expect(res.status).toBe(200);
    expect(((await res.json()) as { ok: boolean }).ok).toBe(true);
  });

  it("verbindet einen Client, listet Tools und führt ein Tool aus", async () => {
    const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`));
    const client = new Client({ name: "http-test", version: "0.0.0" });
    await client.connect(transport);
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name)).toContain("list_sources");
    const result = await client.callTool({ name: "get_usage", arguments: {} });
    expect(JSON.stringify(result.content)).toContain("Kontingent");
    await client.close();
  });

  it("nutzt einen Bearer-Schlüssel aus dem Request je Sitzung", async () => {
    const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`), {
      requestInit: { headers: { Authorization: "Bearer chp_live_anderer_schluessel" } },
    });
    const client = new Client({ name: "http-test-2", version: "0.0.0" });
    await client.connect(transport);
    const result = await client.callTool({ name: "get_usage", arguments: {} });
    expect(result.isError).toBe(true);
    expect(JSON.stringify(result.content)).toMatch(/API-Schlüssel/);
    await client.close();
  });

  it("lehnt Anfragen ohne Sitzung ab", async () => {
    const res = await fetch(`http://127.0.0.1:${port}/mcp`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", method: "tools/list", id: 1 }) });
    expect(res.status).toBe(400);
  });
});
