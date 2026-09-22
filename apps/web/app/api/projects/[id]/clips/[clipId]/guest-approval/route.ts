import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { isEmail, normalizeEmail, randomToken } from "@/lib/auth/tokens";
import { appBaseUrl } from "@/lib/auth/url";
import { getQuota } from "@/lib/billing/quota";
import { GUEST_APPROVAL_TTL_MS } from "@/lib/guest/approval";
import { sendGuestApprovalMail } from "@/lib/guest/mail";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

interface Body {
  guest_name?: unknown;
  guest_email?: unknown;
  message?: unknown;
}

/* POST: Gast-Freigabe anfordern (PHASE4.md, Abschnitt 4). Token 32 Bytes base64url, 14 Tage gültig,
 * clips.guest_approval_required = true, E-Mail (oder Konsole), Audit guest_approval.requested.
 * Plan-Gate: plans.features.guest_approval, sonst 403 mit code plan_gate. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("guest_approval.request");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();

  const quota = await getQuota(repo);
  if (!quota.plan?.features?.guest_approval) {
    return Response.json(
      { error: `Gast-Freigaben sind im Tarif ${quota.plan?.name ?? "Starter"} nicht enthalten. Ab Pro verfügbar.`, code: "plan_gate", href: "/einstellungen/abrechnung" },
      { status: 403 },
    );
  }

  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const guestName = typeof body.guest_name === "string" ? body.guest_name.trim().slice(0, 120) : "";
  const guestEmail = normalizeEmail(body.guest_email);
  const message = typeof body.message === "string" ? body.message.trim().slice(0, 1000) : "";
  if (guestName.length < 2) return Response.json({ error: "Bitte den Namen des Gastes angeben." }, { status: 400 });
  if (guestEmail && !isEmail(guestEmail)) return Response.json({ error: "Die E-Mail-Adresse ist ungültig." }, { status: 400 });

  const token = randomToken(32);
  const expiresAt = new Date(Date.now() + GUEST_APPROVAL_TTL_MS).toISOString();
  const approval = await repo.createGuestApproval(clipId, { guest_name: guestName, guest_email: guestEmail || null, message, token, expires_at: expiresAt });
  const link = `${await appBaseUrl()}/freigabe/${token}`;

  let mail = { delivered: false, logged: false };
  if (guestEmail) {
    mail = await sendGuestApprovalMail({
      to: guestEmail,
      guestName,
      requestedBy: auth.displayName,
      workspaceName: auth.workspaceName,
      sourceTitle: source.title,
      message,
      link,
      expiresAt,
    });
  }
  await repo.audit({
    action: "guest_approval.requested",
    entity: "guest_approvals",
    entity_id: approval.id,
    payload: { clip_id: clipId, source_id: id, guest_name: guestName, guest_email: guestEmail || null, expires_at: expiresAt, mail_delivered: mail.delivered, mail_logged: mail.logged },
  });
  return Response.json({ ok: true, approval, link, mail }, { status: 201 });
}
