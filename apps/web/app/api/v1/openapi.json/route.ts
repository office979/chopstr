import { appBaseUrl } from "@/lib/auth/url";
import { buildOpenApiDocument } from "@/lib/api/openapi";

export const dynamic = "force-dynamic";

/* OpenAPI 3.1 der öffentlichen API, ohne Schlüssel abrufbar (Dokumentation) */
export async function GET() {
  const doc = buildOpenApiDocument(await appBaseUrl());
  return Response.json(doc, { headers: { "Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*" } });
}
