import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadSource } from "@/lib/api/lookup";
import { GET as projectEvents } from "@/app/api/projects/[id]/events/route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/* SSE: gleicher Strom wie /api/projects/[id]/events (hello, pipeline, status, done, error) */
export const GET = apiRoute<{ id: string }>("read", async (request: NextRequest, { params }) => {
  const source = await loadSource(params.id);
  return delegate(projectEvents, request, { id: source.id });
});
