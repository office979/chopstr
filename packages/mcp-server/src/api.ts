/* Dünner Fetch-Client für die öffentliche chopstr-API (/api/v1).
 * Bearer-Auth, Zeitlimit, kein Retry bei 4xx, zwei Wiederholungen bei 5xx und Netzfehlern.
 * Fehler kommen als ApiError mit einer verständlichen deutschen Meldung für das Modell. */

export interface ApiClientOptions {
  baseUrl: string;
  apiKey: string;
  timeoutMs?: number;
  maxRetries?: number;
  fetchImpl?: typeof fetch;
  retryDelayMs?: number;
}

export type ApiErrorKind =
  | "bad_request"
  | "unauthorized"
  | "quota"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "server"
  | "timeout"
  | "network"
  | "invalid_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string | null;
  readonly apiMessage: string | null;
  readonly path: string;

  constructor(kind: ApiErrorKind, message: string, details: { status?: number | null; code?: string | null; apiMessage?: string | null; path: string }) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = details.status ?? null;
    this.code = details.code ?? null;
    this.apiMessage = details.apiMessage ?? null;
    this.path = details.path;
  }
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions {
  query?: QueryParams;
  body?: unknown;
  redirect?: RequestInit["redirect"];
}

interface ErrorBody {
  error?: { code?: unknown; message?: unknown } | string;
}

const RETRY_DELAYS_MS = [500, 1500];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseErrorBody(text: string): { code: string | null; message: string | null } {
  if (!text) return { code: null, message: null };
  try {
    const parsed = JSON.parse(text) as ErrorBody;
    if (typeof parsed.error === "string") return { code: null, message: parsed.error };
    if (parsed.error && typeof parsed.error === "object") {
      const code = typeof parsed.error.code === "string" ? parsed.error.code : null;
      const message = typeof parsed.error.message === "string" ? parsed.error.message : null;
      return { code, message };
    }
  } catch {
    /* kein JSON, Rohtext weiter unten verwenden */
  }
  return { code: null, message: text.slice(0, 300) };
}

/* Übersetzt Status und Fehlerbody in eine Meldung, die das Modell dem Nutzer weitergeben kann. */
export function describeHttpError(status: number, code: string | null, apiMessage: string | null, path: string): { kind: ApiErrorKind; message: string } {
  const detail = apiMessage ? ` (${apiMessage})` : "";
  switch (status) {
    case 400:
    case 422:
      return { kind: "bad_request", message: `Die API hat die Anfrage abgelehnt${detail}. Bitte Eingaben prüfen.` };
    case 401:
      return {
        kind: "unauthorized",
        message: "Der API-Schlüssel wurde nicht akzeptiert: ungültig, abgelaufen oder widerrufen. CHOPSTR_API_KEY prüfen oder unter /entwickler einen neuen Schlüssel anlegen.",
      };
    case 402:
      return {
        kind: "quota",
        message: `Kontingent erschöpft${detail}. Das Stundenkontingent des Workspace für diesen Monat ist aufgebraucht oder der Plan enthält diese Funktion nicht. Mehrverbrauch freischalten oder Plan wechseln, dann erneut versuchen.`,
      };
    case 403:
      return {
        kind: "forbidden",
        message: `Keine Berechtigung${detail}. Der API-Schlüssel hat nicht den nötigen Scope (read, write, publish oder admin) oder die abgeleitete Rolle darf diese Aktion nicht ausführen. Einen Schlüssel mit passendem Scope verwenden.`,
      };
    case 404:
      return { kind: "not_found", message: `Nicht gefunden${detail}. Die ID existiert nicht oder gehört zu einem anderen Workspace.` };
    case 409: {
      const guest = /gast|freigabe|guest/i.test(apiMessage ?? "") || /guest/i.test(code ?? "") || /\/download$|\/publish$/.test(path);
      const hint = guest
        ? " Für diesen Clip ist eine Gast-Freigabe verlangt, die noch nicht vorliegt. Mit request_guest_approval anfordern oder auf die Entscheidung warten."
        : " Der aktuelle Zustand erlaubt diese Aktion nicht (zum Beispiel bereits ersetzt, nicht gerendert oder Freigabe fehlt).";
      return { kind: "conflict", message: `Konflikt${detail}.${hint}` };
    }
    case 429:
      return { kind: "rate_limited", message: "Rate-Limit erreicht (600 Anfragen pro Minute je Schlüssel). Kurz warten und erneut versuchen." };
    default:
      if (status >= 500) {
        return { kind: "server", message: `chopstr hat mit einem Serverfehler geantwortet (HTTP ${status})${detail}. Nach zwei Wiederholungen aufgegeben, bitte später erneut versuchen.` };
      }
      return { kind: "bad_request", message: `Unerwartete Antwort der API (HTTP ${status})${detail}.` };
  }
}

export class ApiClient {
  readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly fetchImpl: typeof fetch;
  private readonly retryDelayMs: number | null;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.maxRetries = options.maxRetries ?? 2;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.retryDelayMs = options.retryDelayMs ?? null;
  }

  get<T>(path: string, query?: QueryParams): Promise<T> {
    return this.request<T>("GET", path, { query });
  }

  post<T>(path: string, body?: unknown, query?: QueryParams): Promise<T> {
    return this.request<T>("POST", path, { body, query });
  }

  delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path, {});
  }

  buildUrl(path: string, query?: QueryParams): string {
    const url = new URL(`${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null || value === "") continue;
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  async request<T>(method: string, path: string, options: RequestOptions): Promise<T> {
    const url = this.buildUrl(path, options.query);
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      Accept: "application/json",
      "User-Agent": "chopstr-mcp/0.1",
    };
    let bodyText: string | undefined;
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      bodyText = JSON.stringify(options.body);
    }

    let lastError: ApiError | null = null;
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let response: Response;
      try {
        response = await this.fetchImpl(url, {
          method,
          headers,
          body: bodyText,
          signal: controller.signal,
          redirect: options.redirect ?? "manual",
        });
      } catch (error) {
        clearTimeout(timer);
        const aborted = error instanceof Error && error.name === "AbortError";
        lastError = aborted
          ? new ApiError("timeout", `Zeitüberschreitung: chopstr hat innerhalb von ${Math.round(this.timeoutMs / 1000)} s nicht geantwortet (${method} ${path}).`, { path })
          : new ApiError("network", `chopstr-API nicht erreichbar unter ${this.baseUrl}. Läuft die Web-App und stimmt CHOPSTR_API_URL?`, { path });
        if (attempt < this.maxRetries) {
          await this.backoff(attempt);
          continue;
        }
        throw lastError;
      }
      clearTimeout(timer);

      if (response.status >= 500) {
        const text = await safeText(response);
        const parsed = parseErrorBody(text);
        const described = describeHttpError(response.status, parsed.code, parsed.message, path);
        lastError = new ApiError(described.kind, described.message, { status: response.status, code: parsed.code, apiMessage: parsed.message, path });
        if (attempt < this.maxRetries) {
          await this.backoff(attempt);
          continue;
        }
        throw lastError;
      }

      if (response.status >= 300 && response.status < 400) {
        const location = response.headers.get("location");
        return { redirect: location, status: response.status } as T;
      }

      if (!response.ok) {
        const text = await safeText(response);
        const parsed = parseErrorBody(text);
        const described = describeHttpError(response.status, parsed.code, parsed.message, path);
        throw new ApiError(described.kind, described.message, { status: response.status, code: parsed.code, apiMessage: parsed.message, path });
      }

      if (response.status === 204) return undefined as T;
      const text = await safeText(response);
      if (!text) return undefined as T;
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new ApiError("invalid_response", `Die API hat kein gültiges JSON geliefert (${method} ${path}).`, { status: response.status, path });
      }
    }
    throw lastError ?? new ApiError("network", "Unbekannter Fehler beim Aufruf der chopstr-API.", { path });
  }

  private async backoff(attempt: number): Promise<void> {
    const delay = this.retryDelayMs ?? RETRY_DELAYS_MS[attempt] ?? 1500;
    if (delay > 0) await sleep(delay);
  }
}

async function safeText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return "";
  }
}
