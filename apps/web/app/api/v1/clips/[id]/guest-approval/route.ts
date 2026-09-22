import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { delegate } from "@/lib/api/delegate";
import { loadClip } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { POST as guestPost } from "@/app/api/projects/[id]/clips/[clipId]/guest-approval/route";

export const dynamic = "force-dynamic";

/* { guest_name, guest_email?, message? } → 201 { approval, link } (gleiche Logik wie die Clip-Übersicht) */
export const POST = apiRoute<{ id: string }>("write", async (request: NextRequest, { params }) => {
  const body = await readJsonBody(request, requestSchema("GuestApprovalRequest"), resolveRef);
  const { clip, source } = await loadClip(params.id);
  return delegate(guestPost, request, { id: source.id, clipId: clip.id }, { method: "POST", body });
});
