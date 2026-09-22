import "server-only";
import { NextRequest } from "next/server";
import { codeForStatus } from "@/lib/api/errors";

/* Wiederverwendung der bestehenden Routen unter app/api/projects/**: die v1-Handler rufen dieselben Handler
 * (und damit dieselben Repository-Methoden, Audit-Einträge und Temporal-Signale) im Sitzungskontext des
 * API-Schlüssels auf und passen nur die Fehlerform an ({ error: { code, message } }). */

type RouteHandler<P> = (request: NextRequest, ctx: { params: Promise<P> }) => Promise<Response> | Response;

export interface DelegateOptions {
  /* Ersetzt den Body (JSON); ohne Angabe wird die Original-Anfrage weitergereicht (GET, SSE) */
  body?: unknown;
  method?: string;
  /* Query-Parameter für die Unteranfrage */
  search?: Record<string, string>;
}

export async function delegate<P>(handler: RouteHandler<P>, request: NextRequest, params: P, options: DelegateOptions = {}): Promise<Response> {
  let req = request;
  if (options.body !== undefined || options.method || options.search) {
    const url = new URL(request.url);
    for (const [k, v] of Object.entries(options.search ?? {})) url.searchParams.set(k, v);
    const method = options.method ?? request.method;
    const headers = new Headers(request.headers);
    let body: string | undefined;
    if (options.body !== undefined && method !== "GET" && method !== "HEAD") {
      headers.set("content-type", "application/json");
      body = JSON.stringify(options.body);
    }
    req = new NextRequest(url, { method, headers, body });
  }
  const res = await handler(req, { params: Promise.resolve(params) });
  return adaptResponse(res);
}

/* { error: "Text", code? } → { error: { code, message } }; Erfolgsantworten bleiben unverändert */
export async function adaptResponse(res: Response): Promise<Response> {
  if (res.status < 400) return res;
  const type = res.headers.get("content-type") ?? "";
  if (!type.includes("application/json")) {
    const text = await res.text().catch(() => "");
    return Response.json({ error: { code: codeForStatus(res.status), message: text || "Fehler" } }, { status: res.status });
  }
  let body: Record<string, unknown> = {};
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch {
    body = {};
  }
  const err = body.error;
  if (err && typeof err === "object" && "message" in (err as Record<string, unknown>)) {
    return Response.json(body, { status: res.status });
  }
  const message = typeof err === "string" ? err : "Fehler";
  const code = typeof body.code === "string" ? body.code : codeForStatus(res.status);
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(body)) if (k !== "error" && k !== "code") rest[k] = v;
  return Response.json({ error: { code, message, ...rest } }, { status: res.status });
}
