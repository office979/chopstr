/* Konfiguration aus Umgebungsvariablen und Kommandozeile. */

export const DEFAULT_API_URL = "http://localhost:3000/api/v1";
export const API_KEY_PREFIX = "chp_live_";

export interface ServerConfig {
  apiUrl: string;
  apiKey: string;
  timeoutMs: number;
}

export interface CliOptions {
  http: number | null;
  host: string;
  help: boolean;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

export function normalizeApiUrl(raw: string | undefined): string {
  const value = (raw ?? "").trim() || DEFAULT_API_URL;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(`CHOPSTR_API_URL ist keine gültige URL: ${value}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConfigError("CHOPSTR_API_URL muss mit http:// oder https:// beginnen");
  }
  return url.toString().replace(/\/+$/, "");
}

export function readConfig(env: NodeJS.ProcessEnv = process.env): ServerConfig {
  const apiKey = (env.CHOPSTR_API_KEY ?? "").trim();
  if (!apiKey) {
    throw new ConfigError(
      "CHOPSTR_API_KEY fehlt. Einen Schlüssel unter /entwickler anlegen und als Umgebungsvariable setzen.",
    );
  }
  if (!apiKey.startsWith(API_KEY_PREFIX)) {
    throw new ConfigError(`CHOPSTR_API_KEY hat nicht das erwartete Format (${API_KEY_PREFIX}…).`);
  }
  const timeoutRaw = Number(env.CHOPSTR_API_TIMEOUT_MS ?? "");
  const timeoutMs = Number.isFinite(timeoutRaw) && timeoutRaw > 0 ? timeoutRaw : 30_000;
  return { apiUrl: normalizeApiUrl(env.CHOPSTR_API_URL), apiKey, timeoutMs };
}

export function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = { http: null, host: "127.0.0.1", help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else if (arg === "--http") {
      const next = argv[i + 1];
      const port = Number(next);
      if (!next || !Number.isInteger(port) || port < 1 || port > 65535) {
        throw new ConfigError("--http erwartet eine Portnummer zwischen 1 und 65535");
      }
      options.http = port;
      i += 1;
    } else if (arg?.startsWith("--http=")) {
      const port = Number(arg.slice("--http=".length));
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        throw new ConfigError("--http erwartet eine Portnummer zwischen 1 und 65535");
      }
      options.http = port;
    } else if (arg === "--host") {
      const next = argv[i + 1];
      if (!next) throw new ConfigError("--host erwartet einen Hostnamen oder eine Adresse");
      options.host = next;
      i += 1;
    } else if (arg?.startsWith("--host=")) {
      options.host = arg.slice("--host=".length);
    } else {
      throw new ConfigError(`Unbekannte Option: ${arg}`);
    }
  }
  return options;
}

export const HELP_TEXT = `chopstr-mcp: MCP-Server für chopstr

Verwendung:
  chopstr-mcp                 stdio-Transport (Claude Desktop, Claude Code)
  chopstr-mcp --http <port>   Streamable HTTP unter http://127.0.0.1:<port>/mcp
  chopstr-mcp --http <port> --host 0.0.0.0   auf allen Schnittstellen lauschen (nur hinter einem Proxy)

Umgebungsvariablen:
  CHOPSTR_API_KEY         Pflicht. API-Schlüssel (chp_live_…), Bearer-Auth gegen /api/v1
  CHOPSTR_API_URL         Basis-URL der API, Standard ${DEFAULT_API_URL}
  CHOPSTR_API_TIMEOUT_MS  Zeitlimit je Anfrage, Standard 30000
`;
