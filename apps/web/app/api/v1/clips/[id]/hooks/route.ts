import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadClip } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { POST as hooksPost } from "@/app/api/projects/[id]/clips/[clipId]/hooks/route";

export const dynamic = "force-dynamic";

/* Manuelle Hook-Version; Linter und Claim-Check laufen im Repository → { ok, hook, needs_render } */
export const POST = apiRoute<{ id: string }>("write", async (request: NextRequest, { params }) => {
  const body = await readJsonBody(request, requestSchema("SaveHook"), resolveRef);
  const { clip, source } = await loadClip(params.id);
  return delegate(hooksPost, request, { id: source.id, clipId: clip.id }, { method: "POST", body });
});
