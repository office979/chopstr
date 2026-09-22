#!/usr/bin/env node
/* Einstieg: stdio (Standard) oder Streamable HTTP mit --http <port>. Logs nur auf stderr, nie Transkriptinhalte. */

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ConfigError, HELP_TEXT, parseArgs, readConfig } from "./config.js";
import { startHttpServer } from "./http.js";
import { createServer } from "./server.js";

async function main(): Promise<void> {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof ConfigError ? error.message : String(error));
    console.error(HELP_TEXT);
    process.exit(2);
  }
  if (options.help) {
    console.error(HELP_TEXT);
    return;
  }
  let config;
  try {
    config = readConfig();
  } catch (error) {
    console.error(error instanceof ConfigError ? error.message : String(error));
    process.exit(2);
  }

  if (options.http !== null) {
    const httpServer = await startHttpServer({ ...config, port: options.http, host: options.host });
    console.error(`chopstr-mcp lauscht auf http://${options.host}:${options.http}/mcp (API ${config.apiUrl})`);
    const shutdown = () => {
      httpServer.close(() => process.exit(0));
      setTimeout(() => process.exit(0), 2000).unref();
    };
    process.on("SIGINT", shutdown);
    process.on("SIGTERM", shutdown);
    return;
  }

  const { server } = createServer(config);
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`chopstr-mcp über stdio verbunden (API ${config.apiUrl})`);
}

main().catch((error) => {
  console.error(`chopstr-mcp konnte nicht starten: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
