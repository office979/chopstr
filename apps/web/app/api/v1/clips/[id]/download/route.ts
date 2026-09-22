import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadClip } from "@/lib/api/lookup";
import { GET as downloadGet } from "@/app/api/projects/[id]/clips/[clipId]/download/route";

export const dynamic = "force-dynamic";

/* 302 auf die Medien-URL, 409 guest_approval_pending ohne Gast-Freigabe (bestehende Sperre) */
export const GET = apiRoute<{ id: string }>("read", async (request: NextRequest, { params }) => {
  const { clip, source } = await loadClip(params.id);
  return delegate(downloadGet, request, { id: source.id, clipId: clip.id });
});
