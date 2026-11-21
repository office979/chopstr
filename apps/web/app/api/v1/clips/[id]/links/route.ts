import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { ApiError, apiJson, conflict, notFound } from "@/lib/api/errors";
import { loadClip } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { serializePublication } from "@/lib/api/serializers";
import { loadClipContext } from "@/lib/publishing/clip-context";
import { gateReasons } from "@/lib/publishing/gates";
import { registerLinkForClip } from "@/lib/publishing/link-check-server";

export const dynamic = "force-dynamic";

interface LinkRegisterBody {
  url: string;
  track_days?: number;
}

/* Link zu einem Clip verfolgen: Linktest wie /links/test, dann eine Publikation (status manual, tracking link).
 * Das ist Buchhaltung wie „Als gepostet eintragen“ und prüft deshalb nur die Gates für den Zweck „eintragen“.
 * Dubletten (gleiche Plattform und ID im Workspace) gibt es mit 409. */
export const POST = apiRoute<{ id: string }>("publish", async (request: NextRequest, { params, auth }) => {
  const body = await readJsonBody<LinkRegisterBody>(request, requestSchema("LinkRegister"), resolveRef);
  const { clip, source } = await loadClip(params.id);
  const ctx = await loadClipContext(source.id, clip.id);
  if (!ctx) throw notFound("Clip nicht gefunden.");
  const sperre = gateReasons(ctx.eintragen);
  if (sperre.length) throw conflict(sperre[0].message, sperre[0].code);
  const result = await registerLinkForClip({ clip, url: body.url, trackDays: body.track_days, via: "api", apiKeyId: auth.key.id });
  if (!result.ok) {
    if (result.status === 409) {
      return apiJson({ error: { code: result.code, message: result.message }, duplicate_publication_id: result.duplicate_publication_id ?? null, check: result.check }, 409);
    }
    throw new ApiError(400, result.code, result.message);
  }
  return apiJson({ publication: serializePublication(result.publication), check: result.check, summary: result.summary }, 201);
});
