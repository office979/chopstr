import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ApiClient, ApiError } from "../src/api.js";
import { MOCK_API_KEY, startMockApi, type MockApi } from "./mock-api.js";

let mock: MockApi;

beforeAll(async () => {
  mock = await startMockApi();
});
afterAll(async () => {
  await mock.close();
});
beforeEach(() => mock.reset());

function client(overrides: Partial<ConstructorParameters<typeof ApiClient>[0]> = {}) {
  return new ApiClient({ baseUrl: mock.url, apiKey: MOCK_API_KEY, retryDelayMs: 0, timeoutMs: 5000, ...overrides });
}

async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("Es wurde ein ApiError erwartet");
}

describe("ApiClient", () => {
  it("sendet Bearer-Header und Query-Parameter", async () => {
    const body = await client().get<{ sources: unknown[] }>("/sources", { status: "ready", limit: undefined });
    expect(body.sources).toHaveLength(2);
    expect(mock.requests[0]?.headers.authorization).toBe(`Bearer ${MOCK_API_KEY}`);
    expect(mock.requests[0]?.query).toEqual({ status: "ready" });
  });

  it("übersetzt 401 in eine Schlüssel-Meldung", async () => {
    const err = await expectApiError(client({ apiKey: "chp_live_falsch" }).get("/sources"));
    expect(err.kind).toBe("unauthorized");
    expect(err.message).toMatch(/API-Schlüssel/);
  });

  it("übersetzt 402 in Kontingent, ohne Retry", async () => {
    const err = await expectApiError(client().get("/quota"));
    expect(err.kind).toBe("quota");
    expect(err.status).toBe(402);
    expect(err.message).toMatch(/Kontingent erschöpft/);
    expect(err.message).toContain("Kontingent für September aufgebraucht");
    expect(mock.counters["/quota"]).toBe(1);
  });

  it("übersetzt 403 in Scope oder Rolle", async () => {
    const err = await expectApiError(client().get("/forbidden"));
    expect(err.kind).toBe("forbidden");
    expect(err.message).toMatch(/Scope/);
    expect(err.message).toContain("Scope write fehlt");
  });

  it("übersetzt 404", async () => {
    const err = await expectApiError(client().get("/sources/gibt_es_nicht"));
    expect(err.kind).toBe("not_found");
    expect(err.message).toMatch(/Nicht gefunden/);
  });

  it("übersetzt 409 bei fehlender Gast-Freigabe", async () => {
    const err = await expectApiError(client().post("/clips/clip_2/publish", { connection_id: "conn_1" }));
    expect(err.kind).toBe("conflict");
    expect(err.message).toMatch(/Gast-Freigabe/);
    expect(err.message).toMatch(/request_guest_approval/);
  });

  it("übersetzt 429", async () => {
    const err = await expectApiError(client().get("/rate"));
    expect(err.kind).toBe("rate_limited");
    expect(err.message).toMatch(/Rate-Limit/);
  });

  it("versteht auch Fehlerbodies mit String-error", async () => {
    const err = await expectApiError(client().get("/plain-error"));
    expect(err.kind).toBe("bad_request");
    expect(err.message).toContain("nur ein String");
  });

  it("wiederholt bei 5xx zweimal und gibt dann auf", async () => {
    const err = await expectApiError(client().get("/always-500"));
    expect(err.kind).toBe("server");
    expect(err.message).toMatch(/HTTP 500/);
    expect(mock.counters["/always-500"]).toBe(3);
  });

  it("gelingt nach zwei 5xx beim dritten Versuch", async () => {
    const body = await client().get<{ attempts: number }>("/flaky");
    expect(body.attempts).toBe(3);
  });

  it("bricht nach dem Zeitlimit ab", async () => {
    const err = await expectApiError(client({ timeoutMs: 150, maxRetries: 0 }).get("/slow"));
    expect(err.kind).toBe("timeout");
    expect(err.message).toMatch(/Zeitüberschreitung/);
  });

  it("meldet nicht erreichbare API", async () => {
    const err = await expectApiError(client({ baseUrl: "http://127.0.0.1:1/api/v1", maxRetries: 0 }).get("/sources"));
    expect(err.kind).toBe("network");
    expect(err.message).toMatch(/nicht erreichbar/);
  });

  it("meldet ungültiges JSON", async () => {
    const err = await expectApiError(client().get("/no-json"));
    expect(err.kind).toBe("invalid_response");
  });

  it("gibt bei 302 die Weiterleitung zurück statt ihr zu folgen", async () => {
    const body = await client().get<{ redirect: string; status: number }>("/clips/clip_1/download");
    expect(body.status).toBe(302);
    expect(body.redirect).toContain("signed");
  });
});
