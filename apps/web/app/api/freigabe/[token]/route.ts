import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { clientIp } from "@/lib/auth/guard";
import { isTokenShape } from "@/lib/auth/tokens";
import { guestMediaUrl } from "@/lib/clips/labels";
import { isLocalMedia } from "@/lib/env";
import { isExpired, isGuestDecision } from "@/lib/guest/approval";
import { emitOutbox } from "@/lib/outbox";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ token: string }> };

function publicView(view: NonNullable<Awaited<ReturnType<ReturnType<typeof getRepo>["getGuestApprovalByToken"]>>>) {
  const base = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;
  const mediaToken = isLocalMedia() ? view.approval.token : null;
  return {
    approval: { ...view.approval, token: undefined, expired: isExpired(view.approval) },
    workspace_name: view.workspace_name,
    source_title: view.source_title,
    clip: {
      ...view.clip,
      file_key: undefined,
      poster_key: undefined,
      video_url: guestMediaUrl(base, view.clip.file_key, mediaToken),
      poster_url: guestMediaUrl(base, view.clip.poster_key, mediaToken),
    },
    onscreen_hook: view.onscreen_hook,
    spoken_hook: view.spoken_hook,
    post_caption: view.post_caption,
  };
}

/* GET: Freigabe ohne Login (Token ist das Geheimnis), setzt viewed_at */
export async function GET(_request: NextRequest, { params }: Params) {
  const { token } = await params;
  if (!isTokenShape(token)) return Response.json({ error: "Link ungültig" }, { status: 404 });
  const repo = getRepo();
  const view = await repo.getGuestApprovalByToken(token);
  if (!view) return Response.json({ error: "Link ungültig oder zurückgezogen" }, { status: 404 });
  if (!view.approval.viewed_at) await repo.markGuestApprovalViewed(token);
  return Response.json(publicView(view), { headers: { "Cache-Control": "no-store" } });
}

/* POST { decision, comment }: Entscheidung des Gastes; Änderungen und Ablehnen brauchen einen Kommentar */
export async function POST(request: NextRequest, { params }: Params) {
  const { token } = await params;
  if (!isTokenShape(token)) return Response.json({ error: "Link ungültig" }, { status: 404 });
  let body: { decision?: unknown; comment?: unknown };
  try {
    body = (await request.json()) as { decision?: unknown; comment?: unknown };
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  if (!isGuestDecision(body.decision)) return Response.json({ error: "decision muss approved, changes oder rejected sein" }, { status: 400 });
  const comment = typeof body.comment === "string" ? body.comment.trim().slice(0, 2000) : "";
  if (body.decision !== "approved" && !comment) {
    return Response.json({ error: "Bitte kurz beschreiben, was geändert werden soll oder warum du ablehnst." }, { status: 400 });
  }
  const repo = getRepo();
  const view = await repo.getGuestApprovalByToken(token);
  if (!view) return Response.json({ error: "Link ungültig oder zurückgezogen" }, { status: 404 });
  if (view.approval.decision) return Response.json({ error: "Diese Freigabe wurde bereits entschieden.", code: "decided" }, { status: 409 });
  if (isExpired(view.approval)) return Response.json({ error: "Dieser Link ist abgelaufen. Bitte um einen neuen Link.", code: "expired" }, { status: 410 });

  const decided = await repo.decideGuestApproval(token, body.decision, comment || null, clientIp(request.headers));
  if (!decided) return Response.json({ error: "Diese Freigabe konnte nicht gespeichert werden." }, { status: 409 });
  /* Phase 5a: Webhook-Ereignis (nur IDs, Entscheidung, Name; kein Kommentar, kein Transkript) */
  await emitOutbox(view.workspace_id, "guest_approval.decided", "guest_approval", decided.id, {
    approval_id: decided.id,
    clip_id: decided.clip_id,
    source_title: view.source_title,
    decision: decided.decision,
    guest_name: decided.guest_name,
    decided_at: decided.decided_at,
  });
  const fresh = await repo.getGuestApprovalByToken(token);
  return Response.json({ ok: true, ...(fresh ? publicView(fresh) : {}) });
}
