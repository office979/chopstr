import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadClip } from "@/lib/api/lookup";
import { POST as renderPost } from "@/app/api/projects/[id]/clips/[clipId]/render/route";

export const dynamic = "force-dynamic";

export const POST = apiRoute<{ id: string }>("write", async (request: NextRequest, { params }) => {
  const { clip, source } = await loadClip(params.id);
  const res = await delegate(renderPost, request, { id: source.id, clipId: clip.id }, { method: "POST", body: {} });
  if (!res.ok) return res;
  const body = (await res.json()) as { ok?: boolean; clip?: { status?: string }; signaled?: boolean };
  return Response.json({ ...body, status: body.clip?.status ?? "rendering" }, { status: 200 });
});
